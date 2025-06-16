"""
Tests for the base Request, Result, Error, and Notification classes.
"""

import copy

import pytest
from pydantic import ValidationError

from conduit.protocol.base import Error, Notification, Request


class TestBaseClassSerialization:
    """
    Serialization is when we convert our types to dicts.
    Deserialization is when we convert dicts into our types.
    """

    def test_request_gets_progress_token_from_data(self):
        # Arrange
        protocol_data = {"method": "test", "params": {"_meta": {"progressToken": 1}}}

        # Act
        req = Request.from_protocol(protocol_data)

        # Assert
        assert req.method == "test"
        assert req.progress_token == 1

    def test_request_serialization_does_not_mutate_input(self):
        # Arrange
        payload = {
            "method": "test",
            "params": {"_meta": {"progressToken": "123"}},
        }
        wire_format = {
            "jsonrpc": "2.0",
            "id": 1,
            **payload,
        }
        original_data = copy.deepcopy(wire_format)

        # Act
        req = Request.from_protocol(wire_format)
        serialized = req.to_protocol()

        # Assert
        assert req.method == "test"
        assert req.progress_token == "123"
        assert serialized == payload
        assert wire_format == original_data

    def test_request_accepts_progress_token_in_metadata(self):
        # Arrange
        protocol_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "test",
            "params": {"_meta": {"progressToken": "123"}},
        }
        req = Request.from_protocol(protocol_data)
        assert req.progress_token == "123"

    def test_request_rejects_bad_progress_token_in_metadata(self):
        # Arrange
        protocol_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "test",
            "params": {"_meta": {"progressToken": 1.9}},  # BAD! Should be int or str.
        }

        # Act and Assert
        with pytest.raises(ValidationError):
            Request.from_protocol(protocol_data)

    def test_request_gets_non_progress_token_metadata(self):
        # Arrange
        protocol_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "req",
            "params": {"testing": "hi", "_meta": {"not_a_progress_token": "not"}},
        }
        req = Request.from_protocol(protocol_data)
        assert req.metadata == {"not_a_progress_token": "not"}
        serialized = req.to_protocol()
        assert serialized["method"] == "req"
        assert serialized["params"]["_meta"]["not_a_progress_token"] == "not"

    def test_request_converts_snake_case_to_camelCase_output(self):
        # Arrange
        req = Request(
            method="test",
            progress_token="123",
        )

        # Act
        serialized = req.to_protocol()

        # Assert
        assert serialized["method"] == "test"
        assert serialized["params"]["_meta"]["progressToken"] == "123"

    def test_request_ignores_unknown_fields_without_error(self):
        # Arrange
        wire_format = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "test",
            "params": {"unknown": "test"},
        }

        # Act
        req = Request.from_protocol(wire_format)

        # Assert
        assert req.method == "test"

    def test_request_preserves_progress_token_roundtrip(self):
        # Arrange
        request = Request(
            method="test",
            progress_token="123",
        )

        # Act
        serialized = request.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, **serialized}
        reconstructed = Request.from_protocol(wire_format)

        # Assert
        assert reconstructed == request  # Roundtrip
        assert reconstructed.progress_token == "123"
        assert reconstructed.method == "test"

    def test_notification_rejects_missing_method(self):
        # Arrange and Act and Assert
        with pytest.raises(KeyError):
            Notification.from_protocol({"not_method": "test"})

    def test_notification_serialization_does_not_mutate_input(self):
        # Arrange
        payload = {
            "method": "notification/test",
        }
        wire_format = {
            "jsonrpc": "2.0",
            "id": 1,
            **payload,
        }
        original_data = copy.deepcopy(wire_format)

        # Act
        notif = Notification.from_protocol(wire_format)
        serialized = notif.to_protocol()

        # Assert
        assert serialized == payload
        assert wire_format == original_data

    def test_error_rejects_missing_code(self):
        # Arrange and Act and Assert
        with pytest.raises(KeyError):
            Error.from_protocol({"message": "test"})

    def test_error_rejects_non_integer_code(self):
        # Arrange and Act and Assert
        with pytest.raises(ValidationError):
            wire_format = {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": "not_an_int", "message": "test"},
            }
            Error.from_protocol(wire_format)

    def test_error_rejects_missing_message(self):
        # Arrange and Act and Assert
        with pytest.raises(KeyError):
            wire_format = {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -1, "data": "test"},
            }
            Error.from_protocol(wire_format)

    def test_error_rejects_int_data(self):
        # Arrange and Act and Assert
        with pytest.raises(ValidationError):
            wire_format = {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -1, "message": "test", "data": 1},
            }
            Error.from_protocol(wire_format)

    def test_error_preserves_nested_dict_data_roundtrip(self):
        # Arrange
        error_data = {"code": -1, "message": "test", "data": {"field": "email"}}
        wire_format = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": error_data,
        }

        # Act
        err = Error.from_protocol(wire_format)
        serialized = err.to_protocol()

        # Assert
        assert serialized == error_data

    def test_error_accepts_exceptions_in_constructor(self):
        # Arrange
        err = Error(code=-1, message="test", data=ValueError("test error"))

        # Act
        result = err.to_protocol()

        # Assert
        assert isinstance(result["data"], str)
        assert "ValueError" in result["data"]
        assert "test error" in result["data"]

    def test_error_accepts_exception_in_protocol_data(self):
        # Arrange
        wire_format = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": -1,
                "message": "test",
                "data": ValueError("test error"),
            },
        }

        # Act
        err = Error.from_protocol(wire_format)

        # Assert
        assert isinstance(err.data, str)
        assert "ValueError" in err.data
        assert "test error" in err.data

    def test_error_preserves_empty_string_data(self):
        # Arrange
        err = Error(code=-1, message="test", data="")

        # Act
        result = err.to_protocol()

        # Assert
        assert result["data"] == ""

    def test_error_preserves_empty_dict_data(self):
        # Arrange
        err = Error(code=-1, message="test", data={})

        # Act
        result = err.to_protocol()

        # Assert
        assert result["data"] == {}

    def test_error_captures_exception_chain(self):
        # Arrange and Act
        try:
            try:
                raise ValueError("inner")
            except ValueError as e:
                raise RuntimeError("outer") from e
        except RuntimeError as exc:
            err = Error(code=-1, message="test", data=exc)
            result = err.to_protocol()

            # Assert
            assert "direct cause" in result["data"] or "caused by" in result["data"]
            assert "ValueError" in result["data"]
            assert "inner" in result["data"]
            assert "RuntimeError" in result["data"]
            assert "outer" in result["data"]

    def test_error_omits_none_data_from_serialization(self):
        # Arrange
        err1 = Error(code=-1, message="test")

        # Act
        serialized1 = err1.to_protocol()

        # Assert
        assert serialized1 == {"code": -1, "message": "test"}
