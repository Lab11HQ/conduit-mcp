import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

from conduit.transport.client import ClientTransport, ServerMessage
from conduit.transport.stdio.shared import parse_json_message, serialize_message

logger = logging.getLogger(__name__)


@dataclass
class ServerProcess:
    """Manages a single server subprocess with its full lifecycle."""

    server_command: list[str]
    process: asyncio.subprocess.Process | None = None
    _is_spawned: bool = False


class StdioClientTransport(ClientTransport):
    """Multi-server stdio client transport.

    Manages multiple server subprocesses, each identified by a server_id.
    Supports lazy connection - servers are registered but not spawned until
    the first message is sent to them.
    """

    def __init__(self) -> None:
        """Initialize multi-server stdio transport.

        No parameters needed in constructor - servers are registered
        individually via add_server().
        """
        self._servers: dict[str, ServerProcess] = {}
        self._message_queue: asyncio.Queue[ServerMessage] = asyncio.Queue()
        self._reader_tasks: dict[str, asyncio.Task] = {}

    async def add_server(self, server_id: str, connection_info: dict[str, Any]) -> None:
        """Register how to reach a server (doesn't connect yet).

        Args:
            server_id: Unique identifier for this server connection
            connection_info: Transport-specific connection details
                Expected keys:
                - "command": list[str] - Command to spawn the server subprocess

        Raises:
            ValueError: If server_id already registered or connection_info invalid
        """
        if server_id in self._servers:
            raise ValueError(f"Server '{server_id}' is already registered")

        # Validate required connection info
        if "command" not in connection_info:
            raise ValueError("connection_info must contain 'command' key")

        server_command = connection_info["command"]
        if not isinstance(server_command, list) or not server_command:
            raise ValueError("'command' must be a non-empty list of strings")

        server_process = ServerProcess(server_command=server_command)
        self._servers[server_id] = server_process
        logger.debug(f"Registered server '{server_id}' with command: {server_command}")

    async def send(self, server_id: str, message: dict[str, Any]) -> None:
        """Send message to specific server.

        Establishes connection if needed, then sends the message.

        Args:
            server_id: Target server connection ID
            message: JSON-RPC message to send

        Raises:
            ValueError: If server_id is not registered
            ConnectionError: If connection cannot be established or send fails
        """
        if server_id not in self._servers:
            raise ValueError(f"Server '{server_id}' is not registered")

        server_process = self._servers[server_id]

        await self._ensure_server_running(server_id, server_process)

        try:
            json_str = serialize_message(message)
            message_bytes = (json_str + "\n").encode("utf-8")
            await self._write_to_server_stdin(server_process, message_bytes)
            logger.debug(f"Sent message to server '{server_id}': {json_str}")
        except ConnectionError:
            await self._mark_server_dead(server_id, server_process)
            raise
        except ValueError:
            raise
        except Exception as e:
            raise ConnectionError(
                f"Failed to send message to server '{server_id}': {e}"
            ) from e

    async def _ensure_server_running(
        self, server_id: str, server_process: ServerProcess
    ) -> None:
        """Ensure server is spawned and running, spawn if needed."""
        if server_process._is_spawned and server_process.process is not None:
            return

        await self._spawn_server(server_id, server_process)

        task = asyncio.create_task(
            self._read_from_server(server_id, server_process),
            name=f"reader_task_{server_id}",
        )
        task.add_done_callback(
            lambda t: asyncio.create_task(
                self._on_reader_done(server_id, server_process, t)
            )
        )
        self._reader_tasks[server_id] = task

    async def _on_reader_done(
        self, server_id: str, server_process: ServerProcess, task: asyncio.Task
    ) -> None:
        """Handle reader task completion - always mark server as dead."""
        if server_id in self._reader_tasks:
            del self._reader_tasks[server_id]

        if task.cancelled():
            logger.debug(f"Reader task for server '{server_id}' was cancelled")
        elif task.exception():
            logger.error(
                f"Reader task for server '{server_id}' failed: {task.exception()}"
            )
        else:
            logger.debug(f"Reader task for server '{server_id}' completed normally")

        await self._mark_server_dead(server_id, server_process)

    async def _mark_server_dead(
        self, server_id: str, server_process: ServerProcess
    ) -> None:
        """Handle server death - cleanup state but keep registration."""
        server_process._is_spawned = False
        server_process.process = None

        if server_id in self._reader_tasks:
            self._reader_tasks[server_id].cancel()
            try:
                await self._reader_tasks[server_id]
            except asyncio.CancelledError:
                pass
            del self._reader_tasks[server_id]

    async def _spawn_server(
        self, server_id: str, server_process: ServerProcess
    ) -> None:
        """Spawn a server subprocess."""

        try:
            logger.debug(
                f"Starting server subprocess '{server_id}': "
                f"{server_process.server_command}"
            )
            server_process.process = await asyncio.create_subprocess_exec(
                *server_process.server_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=None,
            )

            server_process._is_spawned = True
            logger.debug(
                f"Server '{server_id}' subprocess started"
                f"(PID: {server_process.process.pid})"
            )

        except Exception as e:
            logger.error(f"Failed to start server '{server_id}': {e}")
            server_process.process = None
            server_process._is_spawned = False
            raise ConnectionError(f"Failed to start server '{server_id}': {e}") from e

    async def _write_to_server_stdin(
        self, server_process: ServerProcess, data: bytes
    ) -> None:
        """Write data to a server's stdin."""
        try:
            server_process.process.stdin.write(data)
            await server_process.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            raise ConnectionError("Server process closed connection") from e

    def server_messages(self) -> AsyncIterator[ServerMessage]:
        """Stream of messages from all servers with explicit server context.

        Yields:
            ServerMessage: Message with server ID and metadata
        """
        return self._message_queue_iterator()

    async def _message_queue_iterator(self) -> AsyncIterator[ServerMessage]:
        """Async iterator that yields messages from the multiplexed queue."""
        while True:
            try:
                message = await self._message_queue.get()
                yield message
            except Exception as e:
                logger.error(f"Error reading from message queue: {e}")
                break

    async def _read_from_server(
        self, server_id: str, server_process: ServerProcess
    ) -> None:
        """Background task to read messages from one server."""
        while (
            server_process._is_spawned
            and server_process.process is not None
            and server_process.process.returncode is None
        ):
            line = await self._read_line_from_server_stdout(server_process)
            if line is None:
                logger.debug(f"Server '{server_id}' closed stdout")
                break

            message = parse_json_message(line)
            if message is None:
                logger.warning(f"Invalid JSON from server '{server_id}': {line}")
                continue

            server_message = ServerMessage(
                server_id=server_id,
                payload=message,
                timestamp=time.time(),
            )

            await self._message_queue.put(server_message)
            logger.debug(f"Received message from server '{server_id}': {line.strip()}")

    async def _read_line_from_server_stdout(
        self, server_process: ServerProcess
    ) -> str | None:
        """Read one line from a server's stdout.

        Returns:
            Decoded line string, or None if EOF

        Raises:
            ConnectionError: If read fails
        """
        try:
            line_bytes = await server_process.process.stdout.readline()
            if not line_bytes:
                return None
            return line_bytes.decode("utf-8")
        except Exception as e:
            raise ConnectionError(f"Failed to read from server stdout: {e}") from e

    async def disconnect_server(self, server_id: str) -> None:
        """Disconnect from specific server.

        Safe to call multiple times - no-op if server is not registered.

        Args:
            server_id: Server connection ID to disconnect
        """
        if server_id not in self._servers:
            return

        server_process = self._servers[server_id]

        if server_id in self._reader_tasks:
            self._reader_tasks[server_id].cancel()
            try:
                await self._reader_tasks[server_id]
            except asyncio.CancelledError:
                pass
            del self._reader_tasks[server_id]

        await self._shutdown_server_process(server_id, server_process)

        del self._servers[server_id]
        logger.debug(f"Disconnected from server '{server_id}'")

    async def _shutdown_server_process(
        self, server_id: str, server_process: ServerProcess
    ) -> None:
        """Execute graceful shutdown sequence for one server."""
        if server_process.process is None:
            return

        logger.debug(f"Starting graceful shutdown for server '{server_id}'")

        try:
            # Step 1: Close stdin to signal shutdown
            if (
                server_process.process.stdin
                and not server_process.process.stdin.is_closing()
            ):
                server_process.process.stdin.close()
                await server_process.process.stdin.wait_closed()

            # Step 2: Wait for process to exit gracefully
            try:
                await asyncio.wait_for(server_process.process.wait(), timeout=5.0)
                logger.debug(f"Server '{server_id}' exited gracefully")
                return
            except asyncio.TimeoutError:
                logger.debug(
                    f"Server '{server_id}' didn't exit gracefully, sending SIGTERM"
                )

            # Step 3: Send SIGTERM
            try:
                server_process.process.terminate()
            except ProcessLookupError:
                logger.debug(f"Server '{server_id}' already dead, skipping SIGTERM")
                return

            try:
                await asyncio.wait_for(server_process.process.wait(), timeout=5.0)
                logger.debug(f"Server '{server_id}' exited after SIGTERM")
                return
            except asyncio.TimeoutError:
                logger.debug(
                    f"Server '{server_id}' didn't exit after SIGTERM, sending SIGKILL"
                )

            # Step 4: Send SIGKILL
            try:
                server_process.process.kill()
            except ProcessLookupError:
                logger.debug(f"Server '{server_id}' already dead, skipping SIGKILL")
                return

            try:
                await asyncio.wait_for(server_process.process.wait(), timeout=2.0)
                logger.debug(f"Server '{server_id}' killed")
            except asyncio.TimeoutError:
                logger.error(f"Server '{server_id}' didn't die after SIGKILL ")
                # At this point we've done everything we can
                # - just mark it as dead and move on

        except Exception as e:
            logger.error(f"Error during shutdown of server '{server_id}': {e}")
        finally:
            server_process.process = None
            server_process._is_spawned = False
