import pytest

from conduit.protocol.common import EmptyResult
from conduit.shared.exceptions import UnknownRequestError
from tests.client.session.conftest import ClientSessionTest


class TestRequestRouting(ClientSessionTest):
    """Test request routing and unknown method handling."""

    async def test_raises_error_for_unknown_request_method(self):
        """Test that unknown request methods raise UnknownRequestError."""
        # Arrange
        unknown_request = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "unknown/method",
            "params": {},
        }

        # Act & Assert
        with pytest.raises(UnknownRequestError, match="unknown/method"):
            await self.session._handle_session_request(unknown_request)

    async def test_returns_empty_result_for_ping_request(self):
        """Test that ping requests return EmptyResult."""
        # Arrange
        request_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "ping",
            "params": {},
        }

        # Act
        result = await self.session._handle_session_request(request_payload)

        # Assert
        assert isinstance(result, EmptyResult)
