from unittest.mock import AsyncMock

from conduit.client.managers.elicitation import ElicitationNotConfiguredError
from conduit.client.session import ClientSession
from conduit.protocol.base import INTERNAL_ERROR, METHOD_NOT_FOUND, Error
from conduit.protocol.elicitation import ElicitResult
from tests.client.session.conftest import ClientSessionTest


class TestElicitationRequestHandling(ClientSessionTest):
    """Test elicitation/create request handling."""

    elicitation_request = {
        "jsonrpc": "2.0",
        "id": "test-123",
        "method": "elicitation/create",
        "params": {
            "message": "Please provide your name",
            "requestedSchema": {
                "type": "object",
                "properties": {"name": {"minLength": 1, "maxLength": 100}},
            },
        },
    }

    async def test_returns_error_when_elicitation_capability_not_enabled(self):
        # Arrange
        self.config.capabilities.elicitation = False
        self.session = ClientSession(self.transport, self.config)

        request_payload = self.elicitation_request

        # Act
        result = await self.session._handle_session_request(request_payload)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert "does not support elicitation capability" in result.message

    async def test_delegates_to_elicitation_manager_when_capability_enabled(self):
        # Arrange
        self.config.capabilities.elicitation = True
        self.session = ClientSession(self.transport, self.config)

        request_payload = self.elicitation_request

        # Mock the elicitation manager
        mock_result = ElicitResult(
            content={"name": "John Doe"},
            action="accept",
        )
        self.session.elicitation.handle_elicitation = AsyncMock(
            return_value=mock_result
        )

        # Act
        result = await self.session._handle_session_request(request_payload)

        # Assert
        assert result == mock_result
        self.session.elicitation.handle_elicitation.assert_awaited_once()

    async def test_converts_elicitation_not_configured_error_to_method_not_found(self):
        # Arrange
        self.config.capabilities.elicitation = True
        self.session = ClientSession(self.transport, self.config)

        request_payload = self.elicitation_request

        # Mock manager to raise ElicitationNotConfiguredError
        self.session.elicitation.handle_elicitation = AsyncMock(
            side_effect=ElicitationNotConfiguredError("No handler registered")
        )

        # Act
        result = await self.session._handle_session_request(request_payload)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert "No handler registered" in result.message

    async def test_converts_elicitation_exceptions_to_internal_error(self):
        # Arrange
        self.config.capabilities.elicitation = True
        self.session = ClientSession(self.transport, self.config)

        request_payload = self.elicitation_request

        # Mock manager to raise unexpected exception
        self.session.elicitation.handle_elicitation = AsyncMock(
            side_effect=ValueError("Unexpected error")
        )

        # Act
        result = await self.session._handle_session_request(request_payload)

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR
        assert "Error in elicitation handler" in result.message
