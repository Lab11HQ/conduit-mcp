from conduit.protocol.base import METHOD_NOT_FOUND, Error
from conduit.protocol.common import EmptyResult, PingRequest
from tests.client.session.conftest import ClientSessionTest


class TestRequestRouting(ClientSessionTest):
    """Test request routing and unknown method handling."""

    async def test_returns_error_for_unknown_request_method(self):
        """Test that unknown request methods return METHOD_NOT_FOUND error."""

        # Arrange - create a mock request for unknown method
        class UnknownRequest:
            method = "unknown/method"

        unknown_request = UnknownRequest()

        # Act
        result = await self.session._handle_session_request(unknown_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert "Method not supported: unknown/method" in result.message

    async def test_returns_empty_result_for_ping_request(self):
        """Test that ping requests return EmptyResult."""
        # Arrange
        ping_request = PingRequest()

        # Act
        result = await self.session._handle_session_request(ping_request)

        # Assert
        assert isinstance(result, EmptyResult)
