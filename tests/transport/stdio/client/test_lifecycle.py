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
        assert server_process.process is None  # Not spawned yet (lazy connection)
        assert server_process._is_spawned is False

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
