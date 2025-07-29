import pytest

from conduit.transport.streamable_http.client.transport import HttpClientTransport


class TestAddServer:
    async def test_add_server_happy_path(self):
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        connection_info = {
            "endpoint": "https://example.com/mcp",
            "headers": {"Authorization": "Bearer token123"},
        }

        # Act
        await transport.add_server(server_id, connection_info)

        # Assert
        assert server_id in transport._servers
        server_config = transport._servers[server_id]
        assert server_config["endpoint"] == "https://example.com/mcp"
        assert server_config["headers"] == {"Authorization": "Bearer token123"}

    async def test_add_server_missing_endpoint(self):
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        connection_info = {"headers": {"Authorization": "Bearer token123"}}

        # Act & Assert
        with pytest.raises(ValueError):
            await transport.add_server(server_id, connection_info)

    async def test_add_server_invalid_endpoint_url(self):
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        connection_info = {"endpoint": "ftp://invalid.com/path"}

        # Act & Assert
        with pytest.raises(ValueError):
            await transport.add_server(server_id, connection_info)
