from conduit.protocol.roots import (
    ListRootsRequest,
    ListRootsResult,
    Root,
    RootsListChangedNotification,
)


class TestRoots:
    def test_list_roots_request_round_trip(self):
        # Arrange
        request = ListRootsRequest()

        # Act
        serialized = request.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, **serialized}
        reconstructed = ListRootsRequest.from_protocol(wire_format)

        # Assert
        assert reconstructed.method == "roots/list"
        assert reconstructed == request

    def test_list_roots_result_round_trip(self):
        # Arrange
        result = ListRootsResult(
            roots=[
                Root(uri="file:///home/user/project", name="Project Root"),
                Root(uri="file:///tmp/workspace"),  # No name
                Root(uri="file:///var/data", name="Data Directory"),
            ]
        )

        # Act
        serialized = result.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, "result": serialized}
        reconstructed = ListRootsResult.from_protocol(wire_format)

        # Assert
        assert len(reconstructed.roots) == 3
        assert str(reconstructed.roots[0].uri) == "file:///home/user/project"
        assert reconstructed.roots[0].name == "Project Root"
        assert str(reconstructed.roots[1].uri) == "file:///tmp/workspace"
        assert reconstructed.roots[1].name is None
        assert reconstructed.roots[2].name == "Data Directory"
        assert reconstructed == result

    # NOTE: We don't enforce file:// URIs anymore.
    # def test_root_uri_must_be_file_uri(self):
    #     # Arrange
    #     valid_root = Root(uri="file:///path/to/directory")

    #     # Act
    #     assert str(valid_root.uri) == "file:///path/to/directory"

    #     # Assert
    #     with pytest.raises(ValidationError) as exc_info:
    #         Root(uri="https://example.com/path")

    #     # Assert
    #     error_details = str(exc_info.value)
    #     assert "file://" in error_details

    #     # Act
    #     with pytest.raises(ValidationError) as exc_info:
    #         Root(uri="ftp://server/path")

    #     # Assert
    #     error_details = str(exc_info.value)
    #     assert "file://" in error_details

    def test_roots_list_changed_notification_round_trip(self):
        # Arrange
        notification = RootsListChangedNotification()

        # Act
        protocol_data = notification.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, **protocol_data}
        reconstructed = RootsListChangedNotification.from_protocol(wire_format)

        # Assert
        assert reconstructed.method == "notifications/roots/list_changed"
        assert reconstructed == notification
