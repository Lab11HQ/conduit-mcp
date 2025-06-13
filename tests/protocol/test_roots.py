import pytest
from pydantic import ValidationError

from conduit.protocol.roots import (
    ListRootsRequest,
    ListRootsResult,
    Root,
    RootsListChangedNotification,
)


class TestRoots:
    def test_list_roots_request_round_trip(self):
        """Test ListRootsRequest to_protocol and from_protocol round trip."""
        request = ListRootsRequest()

        protocol_data = request.to_protocol()
        reconstructed = ListRootsRequest.from_protocol(protocol_data)

        assert reconstructed.method == "roots/list"
        assert protocol_data == {"method": "roots/list"}

    def test_list_roots_result_round_trip(self):
        """Test ListRootsResult with multiple roots."""
        result = ListRootsResult(
            roots=[
                Root(uri="file:///home/user/project", name="Project Root"),
                Root(uri="file:///tmp/workspace"),  # No name
                Root(uri="file:///var/data", name="Data Directory"),
            ]
        )

        protocol_data = result.to_protocol()
        reconstructed = ListRootsResult.from_protocol(protocol_data)

        assert len(reconstructed.roots) == 3
        assert str(reconstructed.roots[0].uri) == "file:///home/user/project"
        assert reconstructed.roots[0].name == "Project Root"
        assert str(reconstructed.roots[1].uri) == "file:///tmp/workspace"
        assert reconstructed.roots[1].name is None
        assert reconstructed.roots[2].name == "Data Directory"
        assert reconstructed == result

    def test_root_uri_validation(self):
        """Test that Root enforces file:// URI requirement."""
        # Valid file URIs should work
        valid_root = Root(uri="file:///path/to/directory")
        assert str(valid_root.uri) == "file:///path/to/directory"

        # Invalid schemes should raise ValidationError
        with pytest.raises(ValidationError) as exc_info:
            Root(uri="https://example.com/path")

        error_details = str(exc_info.value)
        assert "file://" in error_details

        with pytest.raises(ValidationError) as exc_info:
            Root(uri="ftp://server/path")

        error_details = str(exc_info.value)
        assert "file://" in error_details

    def test_roots_list_changed_notification_round_trip(self):
        """Test RootsListChangedNotification round trip."""
        notification = RootsListChangedNotification()

        protocol_data = notification.to_protocol()
        reconstructed = RootsListChangedNotification.from_protocol(protocol_data)

        assert reconstructed.method == "notifications/roots/list_changed"
        assert protocol_data == {"method": "notifications/roots/list_changed"}
