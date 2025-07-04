from unittest.mock import AsyncMock

from conduit.client.managers.sampling import SamplingNotConfiguredError
from conduit.client.session import ClientSession
from conduit.protocol.base import INTERNAL_ERROR, METHOD_NOT_FOUND, Error
from conduit.protocol.content import TextContent
from conduit.protocol.sampling import CreateMessageResult
from tests.client.session.conftest import ClientSessionTest


class TestSamplingRequestHandling(ClientSessionTest):
    """Test sampling/createMessage request handling."""

    sampling_request = {
        "jsonrpc": "2.0",
        "id": "test-123",
        "method": "sampling/createMessage",
        "params": {
            "maxTokens": 100,
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": "Hello, how are you?"},
                },
            ],
        },
    }

    async def test_returns_error_when_sampling_capability_not_enabled(self):
        # Arrange
        self.config.capabilities.sampling = False
        self.session = ClientSession(self.transport, self.config)

        request_payload = self.sampling_request

        # Act
        result = await self.session._handle_session_request(request_payload)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert "does not support sampling capability" in result.message

    async def test_delegates_to_sampling_manager_when_capability_enabled(self):
        # Arrange
        self.config.capabilities.sampling = True
        self.session = ClientSession(self.transport, self.config)

        request_payload = self.sampling_request

        # Mock the sampling manager
        mock_result = CreateMessageResult(
            role="assistant",
            content=TextContent(text="test response"),
            model="test-model",
        )
        self.session.sampling.handle_create_message = AsyncMock(
            return_value=mock_result
        )

        # Act
        result = await self.session._handle_session_request(request_payload)

        # Assert
        assert result == mock_result
        self.session.sampling.handle_create_message.assert_awaited_once()

    async def test_converts_sampling_not_configured_error_to_method_not_found(self):
        # Arrange
        self.config.capabilities.sampling = True
        self.session = ClientSession(self.transport, self.config)

        request_payload = self.sampling_request

        # Mock manager to raise SamplingNotConfiguredError
        self.session.sampling.handle_create_message = AsyncMock(
            side_effect=SamplingNotConfiguredError("No handler registered")
        )

        # Act
        result = await self.session._handle_session_request(request_payload)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert "No handler registered" in result.message

    async def test_converts_sampling_exceptions_to_internal_error(self):
        # Arrange
        self.config.capabilities.sampling = True
        self.session = ClientSession(self.transport, self.config)

        request_payload = self.sampling_request

        # Mock manager to raise unexpected exception
        self.session.sampling.handle_create_message = AsyncMock(
            side_effect=ValueError("Unexpected error")
        )

        # Act
        result = await self.session._handle_session_request(request_payload)

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR
        assert "Error in sampling handler" in result.message
