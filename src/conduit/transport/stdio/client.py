import asyncio
import logging
from typing import Any, AsyncIterator

from conduit.transport.client import ClientTransport
from conduit.transport.stdio.shared import parse_json_message, serialize_message

logger = logging.getLogger(__name__)


class StdioClientTransport(ClientTransport):
    def __init__(self, server_command: list[str], stderr_file: str | None = None):
        self._server_command = server_command
        self._stderr_file = stderr_file
        self._stderr_handle = None  # Store the handle
        self._process: asyncio.subprocess.Process | None = None
        self._is_open = False

    async def open(self) -> None:
        """Open transport and start the server subprocess.

        Raises:
            ConnectionError: If server cannot be started
        """
        if self._process is not None:
            return  # Already started

        if self._stderr_file:
            self._stderr_handle = open(self._stderr_file, "w")
            stderr_target = self._stderr_handle
        else:
            stderr_target = None

        try:
            logger.debug(f"Starting server subprocess: {self._server_command}")
            self._process = await asyncio.create_subprocess_exec(
                *self._server_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=stderr_target,  # None or file handle
            )

            # Process started successfully - don't check for immediate exit
            # A process that exits quickly might be perfectly valid
            self._is_open = True
            logger.debug(
                f"Server subprocess started successfully (PID: {self._process.pid})"
            )

        except Exception as e:
            logger.error(f"Failed to start server subprocess: {e}")
            self._process = None
            self._is_open = False
            raise ConnectionError(f"Failed to start server: {e}") from e

    @property
    def is_open(self) -> bool:
        return self._is_open and self._is_process_alive()

    def _is_process_alive(self) -> bool:
        """Check if subprocess is still running."""
        if self._process is None:
            return False
        return self._process.returncode is None

    async def _shutdown_process(self) -> None:
        """Execute shutdown sequence: close stdin → wait → terminate → kill."""
        if self._process is None:
            return

        logger.debug("Starting graceful shutdown sequence")

        try:
            # Step 1: Close stdin to signal shutdown
            if self._process.stdin and not self._process.stdin.is_closing():
                self._process.stdin.close()
                await self._process.stdin.wait_closed()

            # Step 2: Wait for process to exit gracefully
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
                logger.debug("Process exited gracefully")
                return
            except asyncio.TimeoutError:
                logger.debug("Process didn't exit gracefully, sending SIGTERM")

            # Step 3: Send SIGTERM (or terminate() on Windows)
            try:
                self._process.terminate()
            except ProcessLookupError:
                logger.debug("Process already dead, skipping SIGTERM")
                return

            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
                logger.debug("Process exited after SIGTERM")
                return
            except asyncio.TimeoutError:
                logger.debug("Process didn't exit after SIGTERM, sending SIGKILL")

            # Step 4: Send SIGKILL (or kill() on Windows)
            try:
                self._process.kill()
            except ProcessLookupError:
                logger.debug("Process already dead, skipping SIGKILL")
                return

            await self._process.wait()
            logger.debug("Process killed")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        finally:
            if self._stderr_handle:
                self._stderr_handle.close()
                self._stderr_handle = None
            self._process = None
            self._is_open = False

    async def _write_to_stdin(self, data: bytes) -> None:
        """Write data to subprocess stdin with error handling.

        Args:
            data: Bytes to write to stdin

        Raises:
            ConnectionError: If process died or stdin unavailable
        """
        if not self._is_process_alive():
            raise ConnectionError("Server process has died")

        if self._process is None or self._process.stdin is None:
            raise ConnectionError("Server stdin is not available")

        try:
            self._process.stdin.write(data)
            await self._process.stdin.drain()  # Ensure data is flushed
        except (BrokenPipeError, ConnectionResetError) as e:
            self._is_open = False
            raise ConnectionError("Server process closed connection") from e

    async def _read_line_from_stdout(self) -> str | None:
        """Read one line from server stdout.

        Returns:
            Decoded line string, or None if EOF

        Raises:
            ConnectionError: If process died or stdout unavailable
        """
        if not self._is_process_alive():
            raise ConnectionError("Server process has died")

        if self._process is None or self._process.stdout is None:
            raise ConnectionError("Server stdout is not available")

        # Read line as bytes
        line_bytes = await self._process.stdout.readline()

        # Check for EOF
        if not line_bytes:
            return None

        # Decode to string (asyncio handles encoding, so this should always work)
        return line_bytes.decode("utf-8")

    async def send(self, message: dict[str, Any]) -> None:
        """Send message to the server.

        Args:
            message: JSON-RPC message to send

        Raises:
            ConnectionError: If transport is closed or connection failed
            ValueError: If message is invalid or contains embedded newlines
        """
        if not self.is_open:
            raise ConnectionError("Transport is not open")

        try:
            # Serialize message to JSON
            json_str = serialize_message(message)

            # Add newline delimiter and encode to bytes
            message_bytes = (json_str + "\n").encode("utf-8")

            # Write to subprocess stdin
            await self._write_to_stdin(message_bytes)

            logger.debug(f"Sent message: {json_str}")

        except ConnectionError:
            # Re-raise connection errors as-is
            raise
        except ValueError:
            raise
        except Exception as e:
            # Other errors (serialization, etc.)
            raise ConnectionError(f"Failed to send message: {e}") from e

    def server_messages(self) -> AsyncIterator[dict[str, Any]]:
        """Stream of messages from the server."""
        return self._server_message_iterator()

    async def _server_message_iterator(self) -> AsyncIterator[dict[str, Any]]:
        """Async iterator implementation for server messages."""
        if not self.is_open:
            raise ConnectionError("Transport is not open")

        try:
            while self._is_process_alive():
                # Read one line from stdout
                line = await self._read_line_from_stdout()
                if line is None:
                    # EOF - server closed stdout
                    logger.debug("Server closed stdout, ending message stream")
                    break

                # Parse as JSON message
                message = parse_json_message(line)
                if message is None:
                    logger.warning(f"Invalid JSON received: {line}")
                    continue

                logger.debug(f"Received message: {line.strip()}")
                yield message

        except ConnectionError:
            # Process died or connection lost
            self._is_open = False
            raise
        finally:
            # Ensure we're marked as closed
            self._is_open = False

    async def close(self) -> None:
        await self._shutdown_process()
