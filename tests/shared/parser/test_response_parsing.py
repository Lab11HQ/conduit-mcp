from conduit.protocol.base import INTERNAL_ERROR, Error
from conduit.protocol.common import EmptyResult, PingRequest
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    InitializeRequest,
)
from conduit.shared.message_parser import MessageParser


class TestPayloadValidation:
    def test_returns_true_for_valid_response(self):
        parser = MessageParser()

        # Valid response with result and string ID
        valid_result_str_id = {"jsonrpc": "2.0", "id": "test-123", "result": {}}
        assert parser.is_valid_response(valid_result_str_id) is True

        # Valid response with result and integer ID
        valid_result_int_id = {"jsonrpc": "2.0", "id": 42, "result": {"tools": []}}
        assert parser.is_valid_response(valid_result_int_id) is True

        # Valid response with error and string ID
        valid_error_str_id = {
            "jsonrpc": "2.0",
            "id": "test-456",
            "error": {"code": -32601, "message": "Method not found"},
        }
        assert parser.is_valid_response(valid_error_str_id) is True

        # Valid response with error and integer ID
        valid_error_int_id = {
            "jsonrpc": "2.0",
            "id": 99,
            "error": {"code": -32602, "message": "Invalid params"},
        }
        assert parser.is_valid_response(valid_error_int_id) is True

    def test_returns_false_for_invalid_response(self):
        parser = MessageParser()

        # Missing id field
        missing_id = {"jsonrpc": "2.0", "result": {}}
        assert parser.is_valid_response(missing_id) is False

        # None id (invalid)
        none_id = {"jsonrpc": "2.0", "id": None, "result": {}}
        assert parser.is_valid_response(none_id) is False

        # Invalid id type (boolean)
        bool_id = {"jsonrpc": "2.0", "id": True, "result": {}}
        assert parser.is_valid_response(bool_id) is False

        # Invalid id type (list)
        list_id = {"jsonrpc": "2.0", "id": [1, 2, 3], "result": {}}
        assert parser.is_valid_response(list_id) is False

        # Missing both result and error
        missing_both = {"jsonrpc": "2.0", "id": "test-123"}
        assert parser.is_valid_response(missing_both) is False

        # Has both result and error (should be exactly one)
        has_both = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "result": {},
            "error": {"code": -32601, "message": "Method not found"},
        }
        assert parser.is_valid_response(has_both) is False

        # Empty payload
        empty_payload = {}
        assert parser.is_valid_response(empty_payload) is False


class TestResponseParsing:
    def test_returns_empty_result_for_case_with_empty_result(self):
        # Arrange
        parser = MessageParser()
        original_request = PingRequest()
        response_payload = {"jsonrpc": "2.0", "id": "test-123", "result": {}}

        # Act
        result = parser.parse_response(response_payload, original_request)

        # Assert
        assert isinstance(result, EmptyResult)

    def test_returns_error_for_case_with_type_mismatch(self):
        # Arrange
        parser = MessageParser()
        # InitializeRequest expects InitializeResult, not EmptyResult
        original_request = InitializeRequest(
            client_info=Implementation(name="Test", version="1.0"),
            capabilities=ClientCapabilities(),
        )
        # But we're giving it a ping-style empty result payload
        response_payload = {"jsonrpc": "2.0", "id": "test-123", "result": {}}

        # Act
        result = parser.parse_response(response_payload, original_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR
        assert "Failed to parse InitializeResult response" in result.message
        assert result.data["expected_type"] == "InitializeResult"
        assert result.data["full_response"] == response_payload

    def test_returns_error_for_case_with_error(self):
        # Arrange
        parser = MessageParser()
        original_request = InitializeRequest(
            client_info=Implementation(name="Test", version="1.0"),
            capabilities=ClientCapabilities(),
            protocol_version="2025-06-18",
        )
        error_response_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "error": {
                "code": -32601,
                "message": "Method not found",
                "data": {"additional": "info"},
            },
        }

        # Act
        result = parser.parse_response(error_response_payload, original_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == -32601
        assert result.message == "Method not found"
        assert result.data == {"additional": "info"}

    def test_returns_error_for_case_with_malformed_error(self):
        # Arrange
        parser = MessageParser()
        original_request = InitializeRequest(
            client_info=Implementation(name="Test", version="1.0"),
            capabilities=ClientCapabilities(),
        )
        # Malformed error - missing required "code" field
        error_response_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "error": {
                "message": "Method not found"
                # Missing required "code" field
            },
        }

        # Act
        result = parser.parse_response(error_response_payload, original_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR
        assert result.message == "Failed to parse response"

    def test_returns_error_for_case_with_no_result_or_error(self):
        # Arrange
        parser = MessageParser()
        original_request = PingRequest()
        # Strange payload with neither result nor error
        strange_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            # No result or error field!
        }

        # Act
        result = parser.parse_response(strange_payload, original_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR
        assert result.message == "Failed to parse response"
        assert result.data["full_response"] == strange_payload
        assert "parse_error" in result.data
        assert "error_type" in result.data
