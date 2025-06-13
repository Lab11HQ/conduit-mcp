"""
Tests for the base Request, Result, Error, and Notification classes.
"""

import copy

import pytest
from pydantic import ValidationError

from conduit.protocol.base import Error, Notification, Request, Result


class TestBaseClassSerialization:
    """
    Serialization is when we convert our types to dicts.
    Deserialization is when we convert dicts into our types.
    """

    def test_request_gets_progress_token_from_data(self):
        protocol_data = {"method": "test", "params": {"_meta": {"progressToken": 1}}}
        req = Request.from_protocol(protocol_data)
        assert req.method == "test"
        assert req.progress_token == 1

    def test_request_serialization_does_not_mutate_input(self):
        protocol_data = {
            "method": "test",
            "params": {"_meta": {"progressToken": "123"}},
        }
        original_data = copy.deepcopy(protocol_data)
        req = Request.from_protocol(protocol_data)
        serialized = req.to_protocol()
        assert req.method == "test"
        assert req.progress_token == "123"
        assert serialized == original_data
        assert protocol_data == original_data

    def test_request_accepts_progress_token_in_metadata(self):
        protocol_data = {
            "method": "test",
            "params": {"_meta": {"progressToken": "123"}},
        }
        req = Request.from_protocol(protocol_data)
        assert req.progress_token == "123"

    def test_request_rejects_bad_progress_token_in_metadata(self):
        protocol_data = {
            "method": "test",
            "params": {"_meta": {"progressToken": 1.9}},
        }
        with pytest.raises(ValidationError):
            Request.from_protocol(protocol_data)

    def test_request_gets_non_progress_token_metadata(self):
        protocol_data = {
            "method": "req",
            "params": {"testing": "hi", "_meta": {"not_a_progress_token": "not"}},
        }
        req = Request.from_protocol(protocol_data)
        assert req.metadata == {"not_a_progress_token": "not"}
        serialized = req.to_protocol()
        assert serialized["method"] == "req"
        assert serialized["params"]["_meta"]["not_a_progress_token"] == "not"

    def test_request_converts_snake_case_to_camelCase_output(self):
        req = Request(
            method="test",
            progress_token="123",
        )
        serialized = req.to_protocol()
        assert serialized["method"] == "test"
        assert serialized["params"]["_meta"]["progressToken"] == "123"

    def test_request_ignores_unknown_fields_without_error(self):
        protocol_data = {
            "method": "test",
            "params": {"unknown": "test"},
        }
        req = Request.from_protocol(protocol_data)
        assert req.method == "test"

    def test_request_preserves_progress_token_roundtrip(self):
        request = Request(
            method="test",
            progress_token="123",
        )
        protocol_data = request.to_protocol()
        assert protocol_data["params"]["_meta"]["progressToken"] == "123"
        reconstructed = Request.from_protocol(protocol_data)
        assert reconstructed.progress_token == "123"
        assert reconstructed.method == "test"

    def test_notification_rejects_missing_method(self):
        with pytest.raises(KeyError):
            Notification.from_protocol({"not_method": "test"})

    def test_notification_serialization_does_not_mutate_input(self):
        protocol_data = {
            "method": "notification/test",
        }
        original_data = copy.deepcopy(protocol_data)
        notif = Notification.from_protocol(protocol_data)
        serialized = notif.to_protocol()
        assert serialized == original_data
        assert protocol_data == original_data

    def test_can_initialize_empty_result(self):
        res = Result()
        assert res is not None

    def test_error_rejects_missing_code(self):
        with pytest.raises(KeyError):
            Error.from_protocol({"message": "test"})

    def test_error_rejects_non_integer_code(self):
        with pytest.raises(ValidationError):
            Error.from_protocol({"code": "not_an_int", "message": "test"})

    def test_error_rejects_missing_message(self):
        with pytest.raises(KeyError):
            Error.from_protocol({"code": -1, "data": "test"})

    def test_error_rejects_int_data(self):
        with pytest.raises(ValidationError):
            Error.from_protocol({"code": -1, "message": "test", "data": 1})

    def test_error_preserves_nested_dict_data_roundtrip(self):
        data = {"code": -1, "message": "test", "data": {"field": "email"}}
        err = Error.from_protocol(data)
        assert err.to_protocol() == data

    def test_error_accepts_exceptions_in_constructor(self):
        err = Error(code=-1, message="test", data=ValueError("test error"))
        result = err.to_protocol()
        assert isinstance(result["data"], str)
        print(result["data"])
        assert "ValueError" in result["data"]
        assert "test error" in result["data"]

    def test_error_accepts_exception_in_protocol_data(self):
        data = {"code": -1, "message": "test", "data": ValueError("test error")}
        err = Error.from_protocol(data)
        assert isinstance(err.data, str)
        assert "ValueError" in err.data
        assert "test error" in err.data

    def test_error_preserves_empty_string_data(self):
        err = Error(code=-1, message="test", data="")
        result = err.to_protocol()
        assert result["data"] == ""

    def test_error_preserves_empty_dict_data(self):
        err = Error(code=-1, message="test", data={})
        result = err.to_protocol()
        assert result["data"] == {}

    def test_error_captures_exception_chain(self):
        try:
            try:
                raise ValueError("inner")
            except ValueError as e:
                raise RuntimeError("outer") from e
        except RuntimeError as exc:
            err = Error(code=-1, message="test", data=exc)
            result = err.to_protocol()
            assert "direct cause" in result["data"] or "caused by" in result["data"]
            assert "ValueError" in result["data"]
            assert "inner" in result["data"]
            assert "RuntimeError" in result["data"]
            assert "outer" in result["data"]

    def test_error_omits_none_data_from_serialization(self):
        err1 = Error(code=-1, message="test")
        err2 = Error(code=-1, message="test", data=None)
        assert err1.to_protocol() == err2.to_protocol()
