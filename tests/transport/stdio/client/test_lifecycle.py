import asyncio

import pytest

from conduit.transport.stdio.client import StdioClientTransport


class TestAddServer:
    async def test_add_server_happy_path(self):
        """Test successful server registration with valid command."""
        # Arrange
        transport = StdioClientTransport()
        server_id = "test-server"
        connection_info = {"command": ["python", "-m", "some.server"]}

        # Act
        await transport.add_server(server_id, connection_info)

        # Assert
        assert server_id in transport._servers
        server_process = transport._servers[server_id]
        assert server_process.server_command == ["python", "-m", "some.server"]
        assert not server_process.is_running

    async def test_add_server_missing_command_key(self):
        """Test that missing 'command' key raises ValueError."""
        # Arrange
        transport = StdioClientTransport()
        server_id = "test-server"
        connection_info = {"other_key": "some_value"}  # Missing 'command'

        # Act & Assert
        with pytest.raises(
            ValueError, match="connection_info must contain 'command' key"
        ):
            await transport.add_server(server_id, connection_info)

        # Verify server wasn't registered
        assert server_id not in transport._servers

    async def test_add_server_invalid_command_format(self):
        """Test that invalid command format raises ValueError."""
        # Arrange
        transport = StdioClientTransport()
        server_id = "test-server"

        # Test cases for invalid command formats
        invalid_commands = [
            {"command": "not_a_list"},  # String instead of list
            {"command": []},  # Empty list
            {"command": None},  # None value
            {
                "command": [123, 456]
            },  # Non-string elements (would fail later but let's be strict)
        ]

        for connection_info in invalid_commands:
            # Act & Assert
            with pytest.raises(
                ValueError, match="'command' must be a non-empty list of strings"
            ):
                await transport.add_server(server_id, connection_info)

            # Verify server wasn't registered
            assert server_id not in transport._servers


class TestSend:
    async def test_send_message_reaches_server(self):
        """Test that sent messages actually reach the server."""
        # Arrange
        transport = StdioClientTransport()
        server_id = "echo-server"
        connection_info = {
            "command": [
                "python",
                "-c",
                """
import sys
for line in sys.stdin:
    line = line.strip()
    if line:
        print(line, flush=True)
""",
            ]
        }

        await transport.add_server(server_id, connection_info)

        # Act
        test_message = {"jsonrpc": "2.0", "method": "test", "id": 1}
        await transport.send(server_id, test_message)

        # Assert by reading from transport's message stream with timeout
        message_iterator = transport.server_messages()
        received_message = await asyncio.wait_for(
            message_iterator.__anext__(), timeout=1.0
        )

        assert received_message.server_id == server_id
        assert received_message.payload == test_message

        # Cleanup
        process = transport._servers[server_id].process
        await transport.disconnect_server(server_id)
        await process.wait()

    async def test_send_to_unregistered_server_raises_value_error(self):
        # Arrange
        transport = StdioClientTransport()
        unregistered_server_id = "nonexistent-server"
        test_message = {"jsonrpc": "2.0", "method": "test", "id": 1}

        # Act & Assert
        with pytest.raises(ValueError):
            await transport.send(unregistered_server_id, test_message)

    async def test_subprocess_spawn_failure_raises_connection_error(self):
        # Arrange
        transport = StdioClientTransport()
        server_id = "failing-server"
        connection_info = {"command": ["nonexistent-command-that-will-fail"]}

        await transport.add_server(server_id, connection_info)
        test_message = {"jsonrpc": "2.0", "method": "test", "id": 1}

        # Act & Assert
        with pytest.raises(ConnectionError):
            await transport.send(server_id, test_message)

        # Verify server state is properly cleaned up
        assert server_id in transport._servers
        server_process = transport._servers[server_id]
        assert not server_process.is_running

    async def test_send_to_respawns_server_and_gets_response(self):
        """Test that client handles server crashes and can recover."""
        # Arrange - server that crashes after first message
        transport = StdioClientTransport()
        server_id = "crash-server"
        connection_info = {
            "command": [
                "python",
                "-c",
                """
import sys
line = sys.stdin.readline()  # Read one message
print(line.strip(), flush=True)  # Echo it back
sys.exit(1)  # Then crash
""",
            ]
        }

        await transport.add_server(server_id, connection_info)

        # Act 1: Send message, server crashes after responding
        test_message = {"jsonrpc": "2.0", "method": "test", "id": 1}
        await transport.send(server_id, test_message)

        # Wait for response
        message_iterator = transport.server_messages()
        received_message = await asyncio.wait_for(
            message_iterator.__anext__(), timeout=1.0
        )
        assert received_message.payload == test_message

        # Wait a bit for crash to be detected
        await asyncio.sleep(0.1)

        # Assert server is marked as dead
        server_process = transport._servers[server_id]
        assert not server_process.is_running
        assert server_id not in transport._reader_tasks

        # Act 2: Send another message - should respawn server and get response
        test_message_2 = {"jsonrpc": "2.0", "method": "test2", "id": 2}
        await transport.send(server_id, test_message_2)

        # Assert we get the second message back (proving respawn worked)
        received_message_2 = await asyncio.wait_for(
            message_iterator.__anext__(), timeout=1.0
        )
        assert received_message_2.payload == test_message_2

        # Wait for crash detection and automatic cleanup
        await asyncio.sleep(0.05)

        # Verify automatic cleanup happened (no manual disconnect needed)
        server_process = transport._servers[server_id]
        assert server_process.process is None

    async def test_send_serialization_failure_keeps_server_alive(self):
        # Arrange
        transport = StdioClientTransport()
        server_id = "echo-server"
        connection_info = {
            "command": [
                "python",
                "-c",
                """
import sys
for line in sys.stdin:
    line = line.strip()
    if line:
        print(line, flush=True)
""",
            ]
        }

        await transport.add_server(server_id, connection_info)

        # Send valid message first to spawn server
        valid_message = {"jsonrpc": "2.0", "method": "test", "id": 1}
        await transport.send(server_id, valid_message)

        # Get reference to spawned process
        process = transport._servers[server_id].process

        # Try to send unserializable message
        bad_message = {
            "jsonrpc": "2.0",
            "method": lambda: None,
        }  # Functions aren't JSON serializable

        with pytest.raises(ValueError):
            await transport.send(server_id, bad_message)

        # Assert server is still alive
        server_process = transport._servers[server_id]
        assert server_process.process is process  # Same process instance
        assert server_process.is_running

        # Verify we can still send valid messages
        valid_message_2 = {"jsonrpc": "2.0", "method": "test2", "id": 2}
        await transport.send(server_id, valid_message_2)

        # Cleanup
        await transport.disconnect_server(server_id)
        await process.wait()
