from unittest.mock import AsyncMock

from conduit.client.managers.sampling import SamplingNotConfiguredError
from conduit.client.session import ClientSession
from conduit.protocol.base import INTERNAL_ERROR, METHOD_NOT_FOUND, Error
from conduit.protocol.content import TextContent
from conduit.protocol.sampling import CreateMessageRequest, CreateMessageResult
from tests.client.session.conftest import ClientSessionTest


class TestSamplingRequestHandling(ClientSessionTest):
    """Test sampling/createMessage request handling."""

    _sampling_request = {
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
    sampling_request = CreateMessageRequest.from_protocol(_sampling_request)

    async def test_delegates_to_sampling_manager_when_capability_enabled(self):
        # Arrange
        self.config.capabilities.sampling = True
        self.session = ClientSession(self.transport, self.config)

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
        result = await self.session._handle_sampling(self.sampling_request)

        # Assert
        assert result == mock_result
        self.session.sampling.handle_create_message.assert_awaited_once()

    async def test_returns_error_when_sampling_not_enabled(self):
        # Arrange
        self.config.capabilities.sampling = False
        self.session = ClientSession(self.transport, self.config)

        # Act
        result = await self.session._handle_sampling(self.sampling_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert "does not support sampling capability" in result.message

    async def test_returns_error_when_sampling_not_configured(self):
        # Arrange
        self.config.capabilities.sampling = True
        self.session = ClientSession(self.transport, self.config)

        # Mock manager to raise SamplingNotConfiguredError
        self.session.sampling.handle_create_message = AsyncMock(
            side_effect=SamplingNotConfiguredError("No handler registered")
        )

        # Act
        result = await self.session._handle_sampling(self.sampling_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert "No handler registered" in result.message

    async def test_returns_error_when_sampling_exceptions_raised(self):
        # Arrange
        self.config.capabilities.sampling = True
        self.session = ClientSession(self.transport, self.config)

        # Mock manager to raise unexpected exception
        self.session.sampling.handle_create_message = AsyncMock(
            side_effect=ValueError("Unexpected error")
        )

        # Act
        result = await self.session._handle_sampling(self.sampling_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR
        assert "Error in sampling handler" in result.message
