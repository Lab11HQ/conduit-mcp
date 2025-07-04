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
    ResourcesCapability,
    RootsCapability,
    ServerCapabilities,
)


class TestInitialization:
    def test_initialize_request_roundtrip(self):
        request = InitializeRequest(
            client_info=Implementation(
                name="Test client name", title="Test client title", version="1"
            ),
            capabilities=ClientCapabilities(),
            protocol_version=PROTOCOL_VERSION,
        )
        protocol_data = request.to_protocol()
        reconstructed = InitializeRequest.from_protocol(protocol_data)
        assert reconstructed == request
        assert reconstructed.client_info.name == "Test client name"
        assert reconstructed.client_info.title == "Test client title"

    def test_initialize_request_serializes_bool_sampling_as_dict(self):
        # Arrange
        request = InitializeRequest(
            client_info=Implementation(name="Test client", version="1"),
            capabilities=ClientCapabilities(sampling=True),
            protocol_version=PROTOCOL_VERSION,
        )
        # Act
        serialized = request.to_protocol()
        # Assert
        assert serialized["params"]["capabilities"]["sampling"] == {}

    def test_initialize_from_protocol_deserializes_dict_sampling_as_bool(self):
        # Arrange
        protocol_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "clientInfo": {"name": "Test client", "version": "1"},
                "capabilities": {"sampling": {}},
            },
        }
        # Act
        request = InitializeRequest.from_protocol(protocol_data)
        # Assert
        assert request.capabilities.sampling

    def test_initialize_request_no_sampling_serializes_as_empty_dict(self):
        # Arrange
        request = InitializeRequest(
            client_info=Implementation(name="Test client", version="1"),
            capabilities=ClientCapabilities(roots=RootsCapability(list_changed=True)),
            protocol_version=PROTOCOL_VERSION,
        )
        # Act
        serialized = request.to_protocol()
        # Assert
        assert "sampling" not in serialized["params"]["capabilities"]

    def test_initialized_notification_roundtrip(self):
        # Arrange
        notif = InitializedNotification()
        # Act
        protocol_data = notif.to_protocol()
        # Assert
        reconstructed = InitializedNotification.from_protocol(protocol_data)
        assert reconstructed == notif

    def test_initialize_result_roundtrip(self):
        # Arrange
        original = InitializeResult(
            protocol_version="2025-03-26",
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="test_server", version="1.0"),
        )
        jsonrpc_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "serverInfo": {"name": "test_server", "version": "1.0"},
            },
        }

        # Act
        reconstructed = InitializeResult.from_protocol(jsonrpc_response)

        # Assert
        assert reconstructed == original
        assert reconstructed.to_protocol() == jsonrpc_response["result"]

    def test_initialize_result_with_metadata_roundtrips(self):
        # Arrange
        result_payload = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "serverInfo": {"name": "test_server", "version": "1.0"},
            "_meta": {"some": "metadata"},
        }
        jsonrpc_response = {"jsonrpc": "2.0", "id": 1, "result": result_payload}

        # Act
        result = InitializeResult.from_protocol(jsonrpc_response)

        # Assert
        assert result.metadata == {"some": "metadata"}
        assert result.to_protocol() == result_payload

    def test_initialize_result_ignores_empty_metadata_from_protocol(self):
        # Arrange
        result_payload_without_meta = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "serverInfo": {"name": "test_server", "version": "1.0"},
        }
        result_payload_with_meta = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "serverInfo": {"name": "test_server", "version": "1.0"},
            "_meta": {},
        }
        jsonrpc_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": result_payload_with_meta,
        }

        # Act
        result = InitializeResult.from_protocol(jsonrpc_response)

        # Assert
        assert result.metadata is None

        assert result.to_protocol() == result_payload_without_meta

    def test_initialize_result_does_not_serialize_metadata_if_empty(self):
        result = InitializeResult(
            protocol_version=PROTOCOL_VERSION,
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="test_server", version="1.0"),
        )
        serialized = result.to_protocol()
        assert "_meta" not in serialized

    def test_initialize_request_roundtrip_with_sampling(self):
        # Arrange
        request = InitializeRequest(
            client_info=Implementation(name="Test client", version="1"),
            capabilities=ClientCapabilities(sampling=True),
            protocol_version=PROTOCOL_VERSION,
        )
        # Act
        serialized = request.to_protocol()
        serialized["id"] = 1
        serialized["jsonrpc"] = "2.0"
        reconstructed = InitializeRequest.from_protocol(serialized)

        # Assert on serialization
        assert serialized == {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "clientInfo": {"name": "Test client", "version": "1"},
                "capabilities": {"sampling": {}},  # Note: Empty dict instead of bool
            },
        }

        # Assert on deserialization
        assert reconstructed.capabilities.sampling
        assert reconstructed.protocol_version == PROTOCOL_VERSION

    def test_initialize_request_roundtrip_with_no_sampling(self):
        # Arrange
        request = InitializeRequest(
            client_info=Implementation(name="Test client", version="1"),
            capabilities=ClientCapabilities(
                sampling=False, roots=RootsCapability(list_changed=True)
            ),
            protocol_version=PROTOCOL_VERSION,
        )
        # Act
        serialized = request.to_protocol()

        assert "sampling" not in serialized["params"]["capabilities"]
        assert serialized["params"]["capabilities"]["roots"]["listChanged"]

    def test_initialize_result_serializes_bool_capabilities_as_dict(self):
        # Arrange
        result = InitializeResult(
            protocol_version=PROTOCOL_VERSION,
            capabilities=ServerCapabilities(logging=True, completions=True),
            server_info=Implementation(name="test_server", version="1.0"),
        )
        # Act
        serialized = result.to_protocol()
        jsonrpc_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": serialized,
        }
        # Assert
        assert jsonrpc_response["result"]["capabilities"]["logging"] == {}
        assert jsonrpc_response["result"]["capabilities"]["completions"] == {}

    def test_initialize_result_deserializes_bool_capabilities_from_dict(self):
        # Arrange
        jsonrpc_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"logging": {}, "completions": {}, "resources": {}},
                "serverInfo": {"name": "test_server", "version": "1.0"},
            },
        }
        # Act
        result = InitializeResult.from_protocol(jsonrpc_response)
        # Assert
        assert result.capabilities.logging
        assert result.capabilities.completions
        assert isinstance(result.capabilities.resources, ResourcesCapability)
