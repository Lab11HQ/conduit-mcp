import sys
from unittest.mock import patch

import pytest

from conduit.transport.stdio.server import StdioServerTransport


class TestSend:
    @patch("builtins.print")
    async def test_send_writes_message_to_stdout(self, mock_print):
        """Test that send writes JSON message to stdout."""
        # Arrange
        transport = StdioServerTransport()
        message = {"jsonrpc": "2.0", "method": "test", "id": 1}

        # Act
        await transport.send("any-client-id", message)

        # Assert
        mock_print.assert_called_once_with(
            '{"jsonrpc":"2.0","method":"test","id":1}', file=sys.stdout, flush=True
        )

    async def test_send_raises_value_error_for_invalid_message(self):
        """Test that send raises ValueError for unserializable messages."""
        transport = StdioServerTransport()

        # Message that can't be JSON serialized
        bad_message = {"method": lambda: None}  # Functions aren't JSON serializable

        with pytest.raises(ValueError):
            await transport.send("client-id", bad_message)


class TestClientMessages:
    async def test_client_messages_basic_flow(self):
        """Test that client_messages can be instantiated and is an async iterator."""
        transport = StdioServerTransport()

        # Just verify it returns an async iterator
        message_iter = transport.client_messages()
        assert hasattr(message_iter, "__anext__")
        assert hasattr(message_iter, "__aiter__")


class TestDisconnectClient:
    @patch("sys.exit")
    @patch("sys.stdout")
    async def test_disconnect_closes_stdout_and_exits(self, mock_stdout, mock_exit):
        """Test that disconnect_client closes stdout and exits."""
        # Arrange
        transport = StdioServerTransport()

        # Act
        await transport.disconnect_client("any-client-id")

        # Assert invariants
        mock_stdout.close.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @patch("sys.exit")
    @patch("sys.stdout")
    async def test_disconnect_exits_even_if_stdout_close_fails(
        self, mock_stdout, mock_exit
    ):
        """Test that disconnect_client exits even if closing stdout fails."""
        # Arrange
        transport = StdioServerTransport()
        mock_stdout.close.side_effect = Exception("stdout close failed")

        # Act
        await transport.disconnect_client("client-id")

        # Assert - still exits despite stdout error
        mock_exit.assert_called_once_with(0)

    @patch("sys.exit")
    @patch("sys.stdout")
    async def test_disconnect_ignores_client_id(self, mock_stdout, mock_exit):
        """Test that disconnect_client works with any client_id."""
        transport = StdioServerTransport()

        # Act with different client IDs
        await transport.disconnect_client("ignored-id")
        await transport.disconnect_client("")
        await transport.disconnect_client("whatever")

        # Assert - same behavior regardless
        assert mock_stdout.close.call_count == 3
        assert mock_exit.call_count == 3
