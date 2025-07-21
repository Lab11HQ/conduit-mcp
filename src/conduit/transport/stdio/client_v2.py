import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

from conduit.transport.client_v2 import ClientTransport, ServerMessage
from conduit.transport.stdio.shared import parse_json_message, serialize_message

logger = logging.getLogger(__name__)


@dataclass
class ServerProcess:
    """Manages a single server subprocess with its full lifecycle."""

    server_command: list[str]
    stderr_file: str | None = None
    process: asyncio.subprocess.Process | None = None
    stderr_handle: Any = None
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
        self._shutdown_event = asyncio.Event()

    async def add_server(self, server_id: str, connection_info: dict[str, Any]) -> None:
        """Register how to reach a server (doesn't connect yet).

        Args:
            server_id: Unique identifier for this server connection
            connection_info: Transport-specific connection details
                Expected keys:
                - "command": list[str] - Command to spawn the server subprocess
                - "stderr_file": str | None (optional) - File to redirect stderr to

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

        stderr_file = connection_info.get("stderr_file")
        if stderr_file is not None and not isinstance(stderr_file, str):
            raise ValueError("'stderr_file' must be a string or None")

        # Create ServerProcess but don't spawn yet
        server_process = ServerProcess(
            server_command=server_command, stderr_file=stderr_file
        )

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

        # Lazy spawn - start the subprocess on first send
        if not server_process._is_spawned:
            await self._spawn_server(server_id, server_process)
            # Start background task to read messages from this server
            self._reader_tasks[server_id] = asyncio.create_task(
                self._read_from_server(server_id, server_process)
            )

        try:
            # Serialize message to JSON (reuse existing logic)
            json_str = serialize_message(message)

            # Add newline delimiter and encode to bytes
            message_bytes = (json_str + "\n").encode("utf-8")

            # Write to this server's stdin
            await self._write_to_server_stdin(server_process, message_bytes)

            logger.debug(f"Sent message to server '{server_id}': {json_str}")

        except ConnectionError:
            # Re-raise connection errors as-is
            raise
        except ValueError:
            # Re-raise serialization errors as-is
            raise
        except Exception as e:
            # Other errors (encoding, etc.)
            raise ConnectionError(
                f"Failed to send message to server '{server_id}': {e}"
            ) from e

    async def _spawn_server(
        self, server_id: str, server_process: ServerProcess
    ) -> None:
        """Spawn a server subprocess (extracted from old implementation)."""
        if server_process.stderr_file:
            server_process.stderr_handle = open(server_process.stderr_file, "w")
            stderr_target = server_process.stderr_handle
        else:
            stderr_target = None

        try:
            logger.debug(
                f"Starting server subprocess '{server_id}': "
                f"{server_process.server_command}"
            )
            server_process.process = await asyncio.create_subprocess_exec(
                *server_process.server_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=stderr_target,
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
        """Write data to a server's stdin (adapted from old implementation)."""
        if not server_process._is_spawned or server_process.process is None:
            raise ConnectionError("Server process is not running")

        if server_process.process.returncode is not None:
            raise ConnectionError("Server process has died")

        if server_process.process.stdin is None:
            raise ConnectionError("Server stdin is not available")

        try:
            server_process.process.stdin.write(data)
            await server_process.process.stdin.drain()  # Ensure data is flushed
        except (BrokenPipeError, ConnectionResetError) as e:
            server_process._is_spawned = False
            raise ConnectionError("Server process closed connection") from e

    def server_messages(self) -> AsyncIterator[ServerMessage]:
        """Stream of messages from all servers with explicit server context.

        Yields:
            ServerMessage: Message with server ID and metadata
        """
        return self._message_queue_iterator()

    async def _message_queue_iterator(self) -> AsyncIterator[ServerMessage]:
        """Async iterator that yields messages from the multiplexed queue."""
        while not self._shutdown_event.is_set():
            try:
                # Wait for next message with a timeout to check shutdown
                message = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                yield message
            except asyncio.TimeoutError:
                # Check if we should continue waiting
                continue
            except Exception as e:
                logger.error(f"Error reading from message queue: {e}")
                break

    async def _read_from_server(
        self, server_id: str, server_process: ServerProcess
    ) -> None:
        """Background task to read messages from one server."""
        try:
            while (
                server_process._is_spawned
                and server_process.process is not None
                and server_process.process.returncode is None
                and not self._shutdown_event.is_set()
            ):
                # Read one line from this server's stdout
                line = await self._read_line_from_server_stdout(server_process)
                if line is None:
                    # EOF - server closed stdout
                    logger.debug(f"Server '{server_id}' closed stdout")
                    break

                # Parse as JSON message
                message = parse_json_message(line)
                if message is None:
                    logger.warning(f"Invalid JSON from server '{server_id}': {line}")
                    continue

                # Wrap in ServerMessage with context
                server_message = ServerMessage(
                    server_id=server_id,
                    payload=message,
                    timestamp=time.time(),
                )

                await self._message_queue.put(server_message)
                logger.debug(
                    f"Received message from server '{server_id}': {line.strip()}"
                )

        except Exception as e:
            logger.error(f"Error reading from server '{server_id}': {e}")
        finally:
            # Mark server as no longer spawned
            server_process._is_spawned = False

    async def _read_line_from_server_stdout(
        self, server_process: ServerProcess
    ) -> str | None:
        """Read one line from a server's stdout.

        Returns:
            Decoded line string, or None if EOF

        Raises:
            ConnectionError: If process died or stdout unavailable
        """
        if not server_process._is_spawned or server_process.process is None:
            raise ConnectionError("Server process is not running")

        if server_process.process.returncode is not None:
            raise ConnectionError("Server process has died")

        if server_process.process.stdout is None:
            raise ConnectionError("Server stdout is not available")

        # Read line as bytes
        line_bytes = await server_process.process.stdout.readline()

        # Check for EOF
        if not line_bytes:
            return None

        # Decode to string
        return line_bytes.decode("utf-8")

    async def disconnect_server(self, server_id: str) -> None:
        """Disconnect from specific server.

        Safe to call multiple times - no-op if server is not registered.

        Args:
            server_id: Server connection ID to disconnect
        """
        if server_id not in self._servers:
            return  # No-op if not registered

        server_process = self._servers[server_id]

        # Cancel reader task if it exists
        if server_id in self._reader_tasks:
            self._reader_tasks[server_id].cancel()
            try:
                await self._reader_tasks[server_id]
            except asyncio.CancelledError:
                pass
            del self._reader_tasks[server_id]

        # Shutdown the subprocess
        await self._shutdown_server_process(server_id, server_process)

        # Remove from registry
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
                logger.error(
                    f"Server '{server_id}' didn't die after SIGKILL - "
                    "this should never happen!"
                )
                # At this point we've done everything we can
                # - just mark it as dead and move on

        except Exception as e:
            logger.error(f"Error during shutdown of server '{server_id}': {e}")
        finally:
            if server_process.stderr_handle:
                server_process.stderr_handle.close()
                server_process.stderr_handle = None
            server_process.process = None
            server_process._is_spawned = False
