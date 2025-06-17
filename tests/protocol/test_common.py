"""
Test miscellaneous types like Pings, CancelledNotifications, etc.
"""

import pytest

from conduit.protocol.common import CancelledNotification, EmptyResult, PingRequest


class TestCommon:
    def test_ping_rejects_non_ping_request(self):
        with pytest.raises(ValueError):
            protocol_data = {"method": "not_ping"}
            _ = PingRequest.from_protocol(protocol_data)

    def test_ping_roundtrips(self):
        # Arrange
        protocol_data = {"jsonrpc": "2.0", "id": 1, "method": "ping"}

        # Act
        ping = PingRequest.from_protocol(protocol_data)
        serialized = ping.to_protocol()

        # Assert
        assert serialized == {"method": "ping"}

    def test_cancelled_notification_roundtrips_with_id_alias(self):
        # Arrange
        payload = {
            "method": "notifications/cancelled",
            "params": {"requestId": 1, "reason": "no need"},
        }
        protocol_data = {
            "jsonrpc": "2.0",
            "id": 1,
            **payload,
        }

        # Act
        notif = CancelledNotification.from_protocol(protocol_data)
        serialized = notif.to_protocol()

        # Assert
        assert notif.method == "notifications/cancelled"
        assert notif.request_id == 1
        assert notif.reason == "no need"

        assert serialized == payload

    def test_empty_result_no_metadata_roundtrip(self):
        # Arrange
        jsonrpc_response = {"jsonrpc": "2.0", "id": 1, "result": {}}

        # Act
        empty_result = EmptyResult.from_protocol(jsonrpc_response)

        # Assert
        assert empty_result.metadata is None
        assert empty_result.to_protocol() == jsonrpc_response["result"]

    def test_empty_result_roundtrip(self):
        # Arrange
        metadata = {"trace_id": "abc123", "duration_ms": 42}
        original = EmptyResult(metadata=metadata)
        jsonrpc_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"_meta": metadata},
        }

        # Act
        reconstructed = EmptyResult.from_protocol(jsonrpc_response)

        # Assert
        assert reconstructed == original
        assert reconstructed.to_protocol() == jsonrpc_response["result"]
