from conduit.protocol.base import INVALID_PARAMS, METHOD_NOT_FOUND, Error
from conduit.protocol.common import PingRequest
from conduit.shared.message_parser import MessageParser


class TestRequestParsing:
    def test_happy_path_ping_request(self):
        # Arrange
        parser = MessageParser()
        payload = {"jsonrpc": "2.0", "id": "test-123", "method": "ping"}

        # Act
        result = parser.parse_request(payload)

        # Assert
        assert isinstance(result, PingRequest)
        assert result.method == "ping"

    def test_unknown_method_returns_method_not_found_error(self):
        # Arrange
        parser = MessageParser()
        payload = {"jsonrpc": "2.0", "id": "test-123", "method": "unknown/method"}

        # Act
        result = parser.parse_request(payload)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

    def test_from_protocol_exception_returns_invalid_params_error(self):
        # Arrange
        parser = MessageParser()
        # InitializeRequest requires clientInfo field - this will fail from_protocol
        payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                # Missing required clientInfo field
            },
        }

        # Act
        result = parser.parse_request(payload)

        # Assert
        assert isinstance(result, Error)
        assert result.code == INVALID_PARAMS


class TestPayloadValidation:
    def test_returns_true_for_valid_request(self):
        parser = MessageParser()

        # Valid with string ID
        valid_payload_str_id = {"method": "tools/list", "id": "test-123"}
        assert parser.is_valid_request(valid_payload_str_id) is True

        # Valid with integer ID
        valid_payload_int_id = {"method": "resources/list", "id": 42}
        assert parser.is_valid_request(valid_payload_int_id) is True

        # Valid with additional fields (should still be valid)
        valid_payload_with_params = {
            "method": "tools/call",
            "id": "call-1",
            "params": {"name": "test_tool", "arguments": {}},
        }
        assert parser.is_valid_request(valid_payload_with_params) is True

    def test_returns_false_for_invalid_request(self):
        parser = MessageParser()

        # Missing method field
        missing_method = {"id": "test-123"}
        assert parser.is_valid_request(missing_method) is False

        # Missing id field
        missing_id = {"method": "tools/list"}
        assert parser.is_valid_request(missing_id) is False

        # None id (invalid)
        none_id = {"method": "tools/list", "id": None}
        assert parser.is_valid_request(none_id) is False

        # Invalid id type (not int or str)
        invalid_id_type = {"method": "tools/list", "id": [1, 2, 3]}
        assert parser.is_valid_request(invalid_id_type) is False

        # Invalid id type (boolean)
        bool_id = {"method": "tools/list", "id": True}
        assert parser.is_valid_request(bool_id) is False

        # Invalid id type (float)
        float_id = {"method": "tools/list", "id": 3.14}
        assert parser.is_valid_request(float_id) is False

        # Empty payload
        empty_payload = {}
        assert parser.is_valid_request(empty_payload) is False
