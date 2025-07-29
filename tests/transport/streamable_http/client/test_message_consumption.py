import asyncio
from unittest.mock import MagicMock, patch

from conduit.transport.client import ServerMessage
from conduit.transport.streamable_http.client.transport import HttpClientTransport


class TestServerMessages:
    @patch("httpx.AsyncClient.post")
    async def test_server_messages_yields_json_response(self, mock_post):
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        await transport.add_server(server_id, {"endpoint": "https://example.com/mcp"})

        request_message = {"jsonrpc": "2.0", "method": "ping", "id": 1}
        response_payload = {"jsonrpc": "2.0", "result": "pong", "id": 1}

        # Mock JSON response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = response_payload
        mock_response.request.headers = {}
        mock_post.return_value = mock_response

        # Act - Send message (which queues response)
        await transport.send(server_id, request_message)

        # Get the message iterator
        message_iterator = transport.server_messages()
        server_message = await message_iterator.__anext__()

        # Assert
        assert server_message.server_id == server_id
        assert server_message.payload == response_payload

    async def test_server_messages_handles_multiple_servers(self):
        # Arrange
        transport = HttpClientTransport()

        # Manually add messages to the queue to simulate multiple servers
        message1 = ServerMessage(
            server_id="server-1",
            payload={"result": "from server 1"},
            timestamp=asyncio.get_event_loop().time(),
        )
        message2 = ServerMessage(
            server_id="server-2",
            payload={"result": "from server 2"},
            timestamp=asyncio.get_event_loop().time(),
        )

        await transport._message_queue.put(message1)
        await transport._message_queue.put(message2)

        # Act - Get messages from iterator
        message_iterator = transport.server_messages()
        received_message1 = await message_iterator.__anext__()
        received_message2 = await message_iterator.__anext__()

        # Assert
        assert received_message1.server_id == "server-1"
        assert received_message1.payload == {"result": "from server 1"}

        assert received_message2.server_id == "server-2"
        assert received_message2.payload == {"result": "from server 2"}
