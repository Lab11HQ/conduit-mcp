"""
Test initialization-related types.
"""

from conduit.protocol.base import PROTOCOL_VERSION
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    InitializedNotification,
    InitializeRequest,
    InitializeResult,
    RootsCapability,
    ServerCapabilities,
)


class TestInitialization:
    def test_initialize_request_roundtrip(self):
        request = InitializeRequest(
            client_info=Implementation(name="Test client", version="1"),
            capabilities=ClientCapabilities(),
            protocol_version=PROTOCOL_VERSION,
        )
        protocol_data = request.to_protocol()
        reconstructed = InitializeRequest.from_protocol(protocol_data)
        assert reconstructed == request
        assert reconstructed.client_info.name == "Test client"

    def test_initialize_request_serializes_bool_sampling_as_dict(self):
        request = InitializeRequest(
            client_info=Implementation(name="Test client", version="1"),
            capabilities=ClientCapabilities(sampling=True),
            protocol_version=PROTOCOL_VERSION,
        )
        serialized = request.to_protocol()
        assert serialized["params"]["capabilities"]["sampling"] == {}

    def test_initialize_from_protocol_deserializes_dict_sampling_as_bool(self):
        protocol_data = {
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "clientInfo": {"name": "Test client", "version": "1"},
                "capabilities": {"sampling": {}},
            },
        }
        request = InitializeRequest.from_protocol(protocol_data)
        assert request.capabilities.sampling

    def test_initialize_request_no_sampling_serializes_as_empty_dict(self):
        request = InitializeRequest(
            client_info=Implementation(name="Test client", version="1"),
            capabilities=ClientCapabilities(roots=RootsCapability(list_changed=True)),
            protocol_version=PROTOCOL_VERSION,
        )
        serialized = request.to_protocol()
        assert "sampling" not in serialized["params"]["capabilities"]

    def test_initialized_notification_roundtrip(self):
        notif = InitializedNotification()
        protocol_data = notif.to_protocol()
        reconstructed = InitializedNotification.from_protocol(protocol_data)
        assert reconstructed == notif

    def test_initialize_result_roundtrip(self):
        result = InitializeResult(
            protocol_version="2025-03-26",
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="test_server", version="1.0"),
        )
        protocol_data = result.to_protocol()
        print("protocol_data", protocol_data)
        print("result", result)
        reconstructed = InitializeResult.from_protocol(protocol_data)
        print("-" * 100)
        print("reconstructed", reconstructed)
        assert reconstructed == result

    def test_initialize_result_with_metadata_roundtrips(self):
        protocol_data = {
            "protocolVersion": "not_a_version",
            "capabilities": {},
            "serverInfo": {"name": "test_server", "version": "1.0"},
            "_meta": {"some": "metadata"},
        }
        result = InitializeResult.from_protocol(protocol_data)
        assert result.metadata == {"some": "metadata"}
        serialized = result.to_protocol()
        assert serialized == protocol_data

    def test_initialize_result_ignores_empty_metadata_from_protocol(self):
        protocol_data = {
            "protocolVersion": "not_a_version",
            "capabilities": {},
            "serverInfo": {"name": "test_server", "version": "1.0"},
            "_meta": {},
        }
        result = InitializeResult.from_protocol(protocol_data)
        assert result.metadata is None
        serialized = result.to_protocol()
        assert "_meta" not in serialized

    def test_initialize_result_does_not_serialize_metadata_if_empty(self):
        result = InitializeResult(
            protocol_version="not_a_version",
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="test_server", version="1.0"),
        )
        serialized = result.to_protocol()
        assert "_meta" not in serialized
