from conduit.protocol.base import INTERNAL_ERROR, METHOD_NOT_FOUND, Error, Result
from conduit.protocol.common import PingRequest
from conduit.protocol.content import TextContent
from conduit.protocol.elicitation import (
    ElicitRequest,
    ElicitResult,
)
from conduit.protocol.initialization import RootsCapability
from conduit.protocol.roots import Root
from conduit.protocol.sampling import (
    CreateMessageRequest,
    CreateMessageResult,
    SamplingMessage,
)

from .conftest import BaseSessionTest


class TestRequestHandler(BaseSessionTest):
    # Core request handling flow
    async def test_sends_success_response_for_valid_ping_request(self):
        # Arrange
        request_payload = {"jsonrpc": "2.0", "id": "42", "method": "ping"}

        # Ensure no messages sent yet
        assert len(self.transport.client_sent_messages) == 0

        # Act
        await self.session._handle_request(request_payload)

        # Assert
        assert len(self.transport.client_sent_messages) == 1

        response_payload = self.transport.client_sent_messages[0]

        # Verify JSON-RPC response structure
        assert response_payload["jsonrpc"] == "2.0"
        assert response_payload["id"] == "42"
        assert "result" in response_payload
        assert response_payload["result"] == {}
        assert "error" not in response_payload

    # Error handling
    async def test_sends_method_not_found_for_unknown_request_method(self):
        # Arrange
        request_payload = {"jsonrpc": "2.0", "id": "123", "method": "unknown/method"}

        # Ensure no messages sent yet
        assert len(self.transport.client_sent_messages) == 0

        # Act
        await self.session._handle_request(request_payload)

        # Assert
        assert len(self.transport.client_sent_messages) == 1

        response_payload = self.transport.client_sent_messages[0]

        # Verify JSON-RPC error response structure
        assert response_payload["jsonrpc"] == "2.0"
        assert response_payload["id"] == "123"
        assert "error" in response_payload
        assert "result" not in response_payload

        # Verify METHOD_NOT_FOUND error
        error = response_payload["error"]
        assert error["code"] == METHOD_NOT_FOUND
        assert "Unknown request method: unknown/method" in error["message"]

    async def test_sends_internal_error_when_handler_raises_exception(
        self, monkeypatch
    ):
        # Arrange
        request_payload = {"jsonrpc": "2.0", "id": "456", "method": "ping"}

        # Mock the ping handler to raise an exception
        async def failing_handler(request: PingRequest):
            raise ValueError("Something went wrong in handler")

        monkeypatch.setattr(self.session, "_handle_ping", failing_handler)

        # Ensure no messages sent yet
        assert len(self.transport.client_sent_messages) == 0

        # Act
        await self.session._handle_request(request_payload)

        # Assert
        assert len(self.transport.client_sent_messages) == 1

        response_payload = self.transport.client_sent_messages[0]

        # Verify JSON-RPC error response structure
        assert response_payload["jsonrpc"] == "2.0"
        assert response_payload["id"] == "456"
        assert "error" in response_payload
        assert "result" not in response_payload

        # Verify INTERNAL_ERROR
        error = response_payload["error"]
        assert error["code"] == INTERNAL_ERROR
        assert "Internal error processing request" in error["message"]

    # Capability-specific handling
    async def test_sends_success_response_for_list_roots_with_capability(self):
        # Arrange
        # Set up session with roots capability
        self.session.capabilities.roots = RootsCapability()
        self.session.roots.register_root(Root(uri="file:///tmp", name="temp"))

        request_payload = {"jsonrpc": "2.0", "id": "789", "method": "roots/list"}

        # Act
        await self.session._handle_request(request_payload)

        # Assert
        assert len(self.transport.client_sent_messages) == 1

        response_payload = self.transport.client_sent_messages[0]

        # Verify successful response
        assert response_payload["jsonrpc"] == "2.0"
        assert response_payload["id"] == "789"
        assert "result" in response_payload
        assert "error" not in response_payload

        # Verify roots are included in result
        result = response_payload["result"]
        assert "roots" in result
        assert len(result["roots"]) == 1
        assert result["roots"][0]["uri"] == "file:///tmp"
        assert result["roots"][0]["name"] == "temp"

    async def test_sends_method_not_found_for_list_roots_without_capability(self):
        # Arrange
        # Ensure session has no roots capability
        self.session.capabilities.roots = None

        request_payload = {"jsonrpc": "2.0", "id": "101", "method": "roots/list"}

        # Act
        await self.session._handle_request(request_payload)

        # Assert
        assert len(self.transport.client_sent_messages) == 1

        response_payload = self.transport.client_sent_messages[0]

        # Verify error response
        assert response_payload["jsonrpc"] == "2.0"
        assert response_payload["id"] == "101"
        assert "error" in response_payload
        assert "result" not in response_payload

        # Verify METHOD_NOT_FOUND error with capability message
        error = response_payload["error"]
        assert error["code"] == METHOD_NOT_FOUND
        assert "Client does not support roots capability" in error["message"]

    async def test_sends_method_not_found_for_create_message_without_capability(self):
        # Arrange
        # Ensure session has no sampling capability
        self.session.capabilities.sampling = False

        request_payload = {
            "jsonrpc": "2.0",
            "id": "202",
            "method": "sampling/createMessage",
            "params": {
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": "Hello"}}
                ],
                "maxTokens": 100,
            },
        }

        # Act
        await self.session._handle_request(request_payload)

        # Assert
        assert len(self.transport.client_sent_messages) == 1

        response_payload = self.transport.client_sent_messages[0]

        # Verify error response
        assert response_payload["jsonrpc"] == "2.0"
        assert response_payload["id"] == "202"
        assert "error" in response_payload
        assert "result" not in response_payload

        # Verify METHOD_NOT_FOUND error with capability message
        error = response_payload["error"]
        assert error["code"] == METHOD_NOT_FOUND
        assert "Client does not support sampling capability" in error["message"]

    async def test_sends_success_response_for_create_message_with_capability(self):
        # Arrange
        # Set up session with sampling capability
        self.session.capabilities.sampling = True

        # Mock the create message handler to return a successful result
        mock_result = CreateMessageResult(
            model="test-model",
            role="assistant",
            content=TextContent(type="text", text="Hello! How can I help you?"),
        )

        async def mock_handler(request: CreateMessageRequest) -> Result | Error:
            return mock_result

        self.session.sampling.set_handler(mock_handler)

        request = CreateMessageRequest(
            messages=[SamplingMessage(role="user", content=TextContent(text="Hello"))],
            max_tokens=100,
        )

        request_payload = {
            "jsonrpc": "2.0",
            "id": "303",
            "method": "sampling/createMessage",
            "params": {
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": "Hello"}}
                ],
                "maxTokens": 100,
            },
        }

        # Act
        await self.session._handle_request(request_payload)

        # Assert
        assert len(self.transport.client_sent_messages) == 1

        response_payload = self.transport.client_sent_messages[0]

        # Verify successful response
        assert response_payload["jsonrpc"] == "2.0"
        assert response_payload["id"] == "303"
        assert "result" in response_payload
        assert "error" not in response_payload

        # Verify the result contains expected fields
        result = response_payload["result"]
        assert result["model"] == "test-model"
        assert result["role"] == "assistant"
        assert result["content"]["type"] == "text"
        assert result["content"]["text"] == "Hello! How can I help you?"

    async def test_success_response_for_elicitation_with_capability(self):
        # Arrange
        # Set up session with elicitation capability
        self.session.capabilities.elicitation = True

        mock_result = ElicitResult(
            action="accept",
            content={"number": 1},
        )

        async def mock_handler(request: ElicitRequest) -> Result | Error:
            return mock_result

        self.session.set_elicitation_handler(mock_handler)

        payload = {
            "jsonrpc": "2.0",
            "id": "42",
            "method": "elicitation/create",
            "params": {
                "message": "Please enter a number",
                "requestedSchema": {
                    "type": "object",
                    "properties": {
                        "number_schema": {
                            "type": "integer",
                        },
                    },
                },
            },
        }

        # Act
        await self.session._handle_request(payload)

        # Assert: Verify response was sent
        assert len(self.transport.client_sent_messages) == 1
        response_payload = self.transport.client_sent_messages[0]

        # Assert: Verify successful response
        assert "result" in response_payload
        assert response_payload["result"]["action"] == "accept"
        assert response_payload["result"]["content"]["number"] == 1

    async def test_sends_method_not_found_for_elicitation_without_capability(self):
        # Arrange
        # Ensure session has no elicitation capability
        self.session.capabilities.elicitation = False

        payload = {
            "jsonrpc": "2.0",
            "id": "42",
            "method": "elicitation/create",
            "params": {
                "message": "Please enter a number",
                "requestedSchema": {
                    "type": "object",
                    "properties": {
                        "number_schema": {
                            "type": "integer",
                        },
                    },
                },
            },
        }

        # Act
        await self.session._handle_request(payload)

        # Assert: Verify response was sent
        assert len(self.transport.client_sent_messages) == 1
        response_payload = self.transport.client_sent_messages[0]

        # Assert: Verify METHOD_NOT_FOUND error with capability message
        error = response_payload["error"]
        assert error["code"] == METHOD_NOT_FOUND
        assert "Client does not support elicitation capability" in error["message"]


class TestRequestValidator(BaseSessionTest):
    def test_is_valid_request_identifies_valid_requests(self):
        # Arrange
        valid_request = {"jsonrpc": "2.0", "method": "ping", "id": "42", "params": {}}

        # Act & Assert
        assert self.session._is_valid_request(valid_request) is True

    def test_is_valid_request_rejects_missing_method(self):
        # Arrange
        invalid_request = {
            "jsonrpc": "2.0",
            "id": "42",
            "params": {},
            # Missing method
        }

        # Act & Assert
        assert self.session._is_valid_request(invalid_request) is False

    def test_is_valid_request_rejects_missing_id(self):
        # Arrange
        invalid_request = {
            "jsonrpc": "2.0",
            "method": "ping",
            "params": {},
            # Missing id
        }

        # Act & Assert
        assert self.session._is_valid_request(invalid_request) is False

    def test_is_valid_request_rejects_null_id(self):
        # Arrange
        invalid_request = {
            "jsonrpc": "2.0",
            "method": "ping",
            "id": None,  # Null id
            "params": {},
        }

        # Act & Assert
        assert self.session._is_valid_request(invalid_request) is False

    def test_is_valid_request_rejects_non_int_or_string_ids(self):
        # Arrange
        invalid_request_1 = {
            "jsonrpc": "2.0",
            "method": "ping",
            "id": 1.9,
            "params": {},
        }
        invalid_request_2 = {
            "jsonrpc": "2.0",
            "method": "ping",
            "id": [1, 2, 3],
            "params": {},
        }

        # Act & Assert
        assert self.session._is_valid_request(invalid_request_1) is False
        assert self.session._is_valid_request(invalid_request_2) is False
