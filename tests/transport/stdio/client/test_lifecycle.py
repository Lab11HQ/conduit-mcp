import asyncio

import pytest

from conduit.transport.stdio.client import StdioClientTransport


class TestStdioClientLifecycle:
    """Test stdio client transport lifecycle management."""

    async def test_open_spawns_subprocess(self):
        # Arrange
        transport = StdioClientTransport(
            ["python", "-c", "import sys; sys.stdin.read()"]
        )

        # Act
        await transport.open()

        # Assert
        assert transport._process is not None
        assert transport.is_open
        assert transport._is_process_alive()

        # Cleanup
        await transport.close()

    async def test_open_is_idempotent(self):
        # Arrange
        transport = StdioClientTransport(
            ["python", "-c", "import sys; sys.stdin.read()"]
        )

        # Act - start multiple times
        await transport.open()
        process1 = transport._process

        await transport.open()
        process2 = transport._process

        # Assert - same process instance
        assert process1 is process2
        assert transport.is_open

        # Cleanup
        await transport.close()

    async def test_open_raises_on_invalid_command(self):
        # Arrange
        transport = StdioClientTransport(["nonexistent-command-12345"])

        # Act & Assert
        with pytest.raises(ConnectionError, match="Failed to start server"):
            await transport.open()

        assert transport._process is None
        assert not transport.is_open

    async def test_is_process_alive_reflects_actual_state(self):
        # Arrange
        transport = StdioClientTransport(
            ["python", "-c", "import sys; sys.stdin.read()"]
        )

        # Act & Assert - before starting
        assert not transport._is_process_alive()

        # Act & Assert - after starting
        await transport.open()
        assert transport._is_process_alive()

        # Act & Assert - after explicit shutdown
        await transport.close()
        assert not transport._is_process_alive()

    async def test_close_is_idempotent(self):
        # Arrange
        transport = StdioClientTransport(
            ["python", "-c", "import sys; sys.stdin.read()"]
        )
        await transport.open()

        # Act - shutdown multiple times
        await transport.close()
        await transport.close()  # Should be safe

        # Assert
        assert not transport.is_open

    async def test_close_does_not_raise_on_already_dead_process(self):
        # Arrange - process that exits immediately (this is fine!)
        transport = StdioClientTransport(["python", "-c", "exit(0)"])
        await transport.open()
        await transport._process.wait()
        assert not transport._is_process_alive()

        # Act & Assert - should not raise even if process already exited
        await transport.close()
        assert not transport.is_open

    async def test_is_open_combines_flags_and_process_state(self):
        # Arrange
        transport = StdioClientTransport(
            ["python", "-c", "import sys; sys.stdin.read()"]
        )

        # Act & Assert - both false initially
        assert not transport._is_open
        assert not transport._is_process_alive()
        assert not transport.is_open

        # Act & Assert - after open, both true
        await transport.open()
        assert transport._is_open
        assert transport._is_process_alive()
        assert transport.is_open

        # Act & Assert - manually set _is_open to False (simulating internal error)
        transport._is_open = False
        assert not transport._is_open
        assert transport._is_process_alive()  # Process still alive
        assert not transport.is_open  # But is_open is False

        # Cleanup
        await transport.close()

    async def test_detects_process_exit(self):
        # Arrange - process that will exit after a short time
        transport = StdioClientTransport(
            ["python", "-c", "import time; time.sleep(0.01); exit(1)"]
        )
        await transport.open()

        # Act & Assert - initially alive
        assert transport.is_open
        assert transport._is_process_alive()

        # Act - wait for process to exit naturally
        await asyncio.sleep(0.1)

        # Assert - process exit is detected
        assert not transport._is_process_alive()
        assert not transport.is_open  # Should reflect process exit

    async def test_multiple_transports_independent_processes(self):
        # Arrange
        transport1 = StdioClientTransport(
            ["python", "-c", "import sys; sys.stdin.read()"]
        )
        transport2 = StdioClientTransport(
            ["python", "-c", "import sys; sys.stdin.read()"]
        )

        # Act
        await transport1.open()
        await transport2.open()

        # Assert - different processes
        assert transport1._process is not transport2._process
        assert transport1._process.pid != transport2._process.pid

        # Cleanup
        await transport1.close()
        await transport2.close()
