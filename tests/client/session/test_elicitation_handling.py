from unittest.mock import AsyncMock

from conduit.client.protocol.elicitation import ElicitationNotConfiguredError
from conduit.client.session_v2 import ClientConfig, ClientSession
from conduit.protocol.base import INTERNAL_ERROR, METHOD_NOT_FOUND, Error
from conduit.protocol.elicitation import ElicitRequest, ElicitResult
from conduit.protocol.initialization import ClientCapabilities, Implementation


class TestElicitationRequestHandling:
    """Test elicitation/create request handling."""

    def setup_method(self):
        self.transport = AsyncMock()
        self.config_with_elicitation = ClientConfig(
            client_info=Implementation(name="test-client", version="1.0.0"),
            capabilities=ClientCapabilities(elicitation=True),
        )
        self.config_without_elicitation = ClientConfig(
            client_info=Implementation(name="test-client", version="1.0.0"),
            capabilities=ClientCapabilities(elicitation=False),
        )

    _elicitation_wire_message = {
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
    elicitation_request = ElicitRequest.from_protocol(_elicitation_wire_message)

    async def test_delegates_to_manager_when_capability_enabled(self):
        # Arrange
        self.session = ClientSession(self.transport, self.config_with_elicitation)

        # Mock the elicitation manager
        mock_result = ElicitResult(
            content={"name": "John Doe"},
            action="accept",
        )
        self.session.elicitation.handle_elicitation = AsyncMock(
            return_value=mock_result
        )

        # Act
        result = await self.session._handle_elicitation(
            "server_id", self.elicitation_request
        )

        # Assert
        assert result == mock_result
        self.session.elicitation.handle_elicitation.assert_awaited_once()

    async def test_returns_error_when_elicitation_not_enabled(self):
        # Arrange
        self.session = ClientSession(self.transport, self.config_without_elicitation)

        # Act
        result = await self.session._handle_elicitation(
            "server_id", self.elicitation_request
        )

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

    async def test_returns_error_when_elicitation_not_configured(self):
        # Arrange
        self.session = ClientSession(self.transport, self.config_with_elicitation)

        # Mock manager to raise ElicitationNotConfiguredError
        self.session.elicitation.handle_elicitation = AsyncMock(
            side_effect=ElicitationNotConfiguredError("No handler registered")
        )

        # Act
        result = await self.session._handle_elicitation(
            "server_id", self.elicitation_request
        )

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

    async def test_returns_error_when_elicitation_exceptions_raised(self):
        # Arrange
        self.session = ClientSession(self.transport, self.config_with_elicitation)

        # Mock manager to raise unexpected exception
        self.session.elicitation.handle_elicitation = AsyncMock(
            side_effect=ValueError("Unexpected error")
        )

        # Act
        result = await self.session._handle_elicitation(
            "server_id", self.elicitation_request
        )

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR
