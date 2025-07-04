"""
Test JSONRPC serialization.
"""

import pytest
from pydantic import ValidationError

from conduit.protocol.base import PROTOCOL_VERSION, Error
from conduit.protocol.common import PingRequest, ProgressNotification
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    InitializeRequest,
    InitializeResult,
    ServerCapabilities,
)
from conduit.protocol.jsonrpc import (
    JSONRPC_VERSION,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)
from conduit.protocol.resources import ListResourcesRequest


class TestJSONRPCSerializing:
    def test_serializes_request_with_params(self):
        req = InitializeRequest(
            client_info=Implementation(name="Test client", version="1"),
            capabilities=ClientCapabilities(),
        )
        jsonrpc_req = JSONRPCRequest.from_request(req, id=1)
        wire_data = jsonrpc_req.to_wire()
        expected_data = {
            "jsonrpc": JSONRPC_VERSION,
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "clientInfo": {"name": "Test client", "version": "1"},
                "capabilities": {},
            },
        }
        print("wire_data", wire_data)
        assert wire_data == expected_data

    def test_serializes_with_cursor_for_pagination(self):
        req = ListResourcesRequest(cursor="xyz")
        jsonrpc_req = JSONRPCRequest.from_request(req, id=1)
        wire_data = jsonrpc_req.to_wire()
        expected_data = {
            "jsonrpc": JSONRPC_VERSION,
            "id": 1,
            "method": "resources/list",
            "params": {"cursor": "xyz"},
        }
        assert wire_data == expected_data

    def test_serializes_notification_with_params(self):
        notif = ProgressNotification(
            progress_token="token", progress=1, total=2, message="Halfway home!"
        )
        jsonrpc_notif = JSONRPCNotification.from_notification(notif)
        wire_data = jsonrpc_notif.to_wire()
        expected_data = {
            "jsonrpc": JSONRPC_VERSION,
            "method": "notifications/progress",
            "params": {
                "progressToken": "token",
                "progress": 1,
                "total": 2,
                "message": "Halfway home!",
            },
        }
        assert wire_data == expected_data

    def test_serializes_response_with_params(self):
        result = InitializeResult(
            capabilities=ServerCapabilities(completions=True),
            server_info=Implementation(name="test server", version="1"),
            instructions="Use me well",
        )
        jsonrpc_response = JSONRPCResponse.from_result(result=result, id=1)
        wire_data = jsonrpc_response.to_wire()
        expected_data = {
            "jsonrpc": JSONRPC_VERSION,
            "id": 1,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"completions": {}},
                "serverInfo": {"name": "test server", "version": "1"},
                "instructions": "Use me well",
            },
        }
        assert wire_data == expected_data

    def test_serializes_error_with_error_data(self):
        err = Error(message="Bad. No good.", code=57, data="Specifics")
        jsonrpc_error = JSONRPCError.from_error(error=err, id=1)
        wire_data = jsonrpc_error.to_wire()
        expected_data = {
            "jsonrpc": JSONRPC_VERSION,
            "id": 1,
            "error": {"message": "Bad. No good.", "code": 57, "data": "Specifics"},
        }
        assert wire_data == expected_data

    def test_serializes_request_without_params(self):
        ping = PingRequest()
        jsonrpc_req = JSONRPCRequest.from_request(ping, id=2)
        wire_data = jsonrpc_req.to_wire()
        expected_data = {"jsonrpc": JSONRPC_VERSION, "id": 2, "method": "ping"}
        assert "params" not in wire_data
        assert wire_data["method"] == "ping"
        assert wire_data == expected_data

    def test_jsonrpc_request_is_outgoing_only(self):
        """JSONRPCRequest is designed for outgoing messages only.

        Incoming wire data should be parsed directly to typed requests,
        not through JSONRPCRequest objects.
        """
        wire_data = {
            "jsonrpc": JSONRPC_VERSION,
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "clientInfo": {"name": "Test client", "version": "1"},
                "capabilities": {},
            },
        }

        # This should fail - we don't support deserializing from wire format
        with pytest.raises((ValidationError, KeyError)):
            JSONRPCRequest.model_validate(wire_data)

        # Instead, parse directly to typed request
        request = InitializeRequest.from_protocol(wire_data)
        assert request.method == "initialize"
        assert request.client_info.name == "Test client"
