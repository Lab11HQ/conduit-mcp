from unittest.mock import AsyncMock

from conduit.client.protocol.sampling import SamplingNotConfiguredError
from conduit.client.session import ClientConfig, ClientSession
from conduit.protocol.base import INTERNAL_ERROR, METHOD_NOT_FOUND, Error
from conduit.protocol.content import TextContent
from conduit.protocol.initialization import ClientCapabilities, Implementation
from conduit.protocol.sampling import CreateMessageRequest, CreateMessageResult


class TestSamplingRequestHandling:
    """Test sampling/createMessage request handling."""

    def setup_method(self):
        self.transport = AsyncMock()
        self.config_with_sampling = ClientConfig(
            client_info=Implementation(name="test-client", version="1.0.0"),
            capabilities=ClientCapabilities(sampling=True),
        )
        self.config_without_sampling = ClientConfig(
            client_info=Implementation(name="test-client", version="1.0.0"),
            capabilities=ClientCapabilities(sampling=False),
        )

    _sampling_wire_message = {
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
    sampling_request = CreateMessageRequest.from_protocol(_sampling_wire_message)

    async def test_delegates_to_sampling_manager_when_capability_enabled(self):
        # Arrange
        self.session = ClientSession(self.transport, self.config_with_sampling)

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
        result = await self.session._handle_sampling("server_id", self.sampling_request)

        # Assert
        assert result == mock_result
        self.session.sampling.handle_create_message.assert_awaited_once()

    async def test_returns_error_when_sampling_not_enabled(self):
        # Arrange
        self.session = ClientSession(self.transport, self.config_without_sampling)

        # Act
        result = await self.session._handle_sampling("server_id", self.sampling_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

    async def test_returns_error_when_sampling_not_configured(self):
        # Arrange
        self.session = ClientSession(self.transport, self.config_with_sampling)

        # Mock manager to raise SamplingNotConfiguredError
        self.session.sampling.handle_create_message = AsyncMock(
            side_effect=SamplingNotConfiguredError("No handler registered")
        )

        # Act
        result = await self.session._handle_sampling("server_id", self.sampling_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

    async def test_returns_error_when_sampling_exceptions_raised(self):
        # Arrange
        self.session = ClientSession(self.transport, self.config_with_sampling)

        # Mock manager to raise unexpected exception
        self.session.sampling.handle_create_message = AsyncMock(
            side_effect=ValueError("Unexpected error")
        )

        # Act
        result = await self.session._handle_sampling("server_id", self.sampling_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR
