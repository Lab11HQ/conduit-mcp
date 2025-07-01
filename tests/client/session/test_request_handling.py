from unittest.mock import AsyncMock

import pytest

from conduit.client.managers.elicitation import ElicitationNotConfiguredError
from conduit.client.managers.sampling import SamplingNotConfiguredError
from conduit.client.session import ClientSession
from conduit.protocol.base import INTERNAL_ERROR, METHOD_NOT_FOUND, Error
from conduit.protocol.common import EmptyResult
from conduit.protocol.content import TextContent
from conduit.protocol.elicitation import ElicitResult
from conduit.protocol.initialization import RootsCapability
from conduit.protocol.roots import ListRootsResult
from conduit.protocol.sampling import CreateMessageResult
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


class TestRootsRequestHandling(ClientSessionTest):
    """Test roots/list request handling."""

    async def test_returns_error_when_roots_capability_not_advertised(self):
        """Test that roots requests return METHOD_NOT_FOUND when capability missing."""
        # Arrange
        self.config.capabilities.roots = None
        self.session = ClientSession(self.transport, self.config)

        request_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "roots/list",
            "params": {},
        }

        # Act
        result = await self.session._handle_session_request(request_payload)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert "does not support roots capability" in result.message

    async def test_delegates_to_roots_manager_when_capability_advertised(self):
        """Test that roots requests delegate to manager when capability exists."""
        # Arrange
        self.config.capabilities.roots = RootsCapability(list_changed=True)
        self.session = ClientSession(self.transport, self.config)

        request_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "roots/list",
            "params": {},
        }

        # Mock the roots manager
        mock_result = ListRootsResult(roots=[])
        self.session.roots.handle_list_roots = AsyncMock(return_value=mock_result)

        # Act
        result = await self.session._handle_session_request(request_payload)

        # Assert
        assert result == mock_result
        self.session.roots.handle_list_roots.assert_awaited_once()


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
