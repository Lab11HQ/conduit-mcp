"""
Test miscellaneous types like Pings, CancelledNotifications, etc.
"""

import pytest

from conduit.protocol.common import CancelledNotification, EmptyResult, PingRequest


class TestMisc:
    def test_ping_rejects_non_ping_request(self):
        with pytest.raises(ValueError):
            protocol_data = {"method": "not_ping"}
            _ = PingRequest.from_protocol(protocol_data)

    def test_ping_roundtrips(self):
        protocol_data = {"method": "ping"}
        ping = PingRequest.from_protocol(protocol_data)
        serialized = ping.to_protocol()
        assert serialized == protocol_data

    def test_cancelled_notification_roundtrips_with_id_alias(self):
        protocol_data = {
            "method": "notifications/cancelled",
            "params": {"requestId": 1, "reason": "no need"},
        }
        notif = CancelledNotification.from_protocol(protocol_data)
        assert notif.method == "notifications/cancelled"
        assert notif.request_id == 1
        assert notif.reason == "no need"
        serialized = notif.to_protocol()
        assert serialized == protocol_data

    def test_empty_result_with_metadata_round_trip(self):
        """Test EmptyResult serializes metadata correctly."""
        # Test with metadata
        result_with_meta = EmptyResult(metadata={"operation": "delete", "count": 5})

        protocol_data = result_with_meta.to_protocol()
        reconstructed = EmptyResult.from_protocol(protocol_data)

        assert reconstructed.metadata == {"operation": "delete", "count": 5}
        assert protocol_data == {"_meta": {"operation": "delete", "count": 5}}

        # Test without metadata (should be clean)
        empty_result = EmptyResult()

        protocol_data = empty_result.to_protocol()
        reconstructed = EmptyResult.from_protocol(protocol_data)

        assert reconstructed.metadata is None
        assert protocol_data == {}  # Should be completely empty
