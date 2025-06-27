"""
Test resource-related types.
"""

from conduit.protocol.resources import (
    Annotations,
    ListResourcesRequest,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    SubscribeRequest,
    TextResourceContents,
    UnsubscribeRequest,
)


class TestResources:
    def test_list_resource_request_roundtrip_with_cursor(self):
        # Arrange
        payload = {
            "method": "resources/list",
            "params": {"cursor": "abc"},
        }
        wire_format = {
            "jsonrpc": "2.0",
            "id": 1,
            **payload,
        }

        # Act
        req = ListResourcesRequest.from_protocol(wire_format)

        # Assert
        assert req.cursor == "abc"
        assert req.method == "resources/list"
        assert req.to_protocol() == payload

    def test_list_resource_request_roundtrip_with_cursor_and_metadata(self):
        # Arrange
        payload = {
            "method": "resources/list",
            "params": {"cursor": "abc", "_meta": {"progressToken": "123"}},
        }
        wire_format = {
            "jsonrpc": "2.0",
            "id": 1,
            **payload,
        }

        # Act
        req = ListResourcesRequest.from_protocol(wire_format)
        serialized = req.to_protocol()

        # Assert
        assert req.cursor == "abc"
        assert req.progress_token == "123"
        assert req.method == "resources/list"
        assert serialized == payload

    def test_list_resources_result_roundtrips(self):
        # Arrange
        resource = Resource(
            uri="https://example.com",
            name="Example",
            annotations=Annotations(audience="user", priority=0.5),
        )
        res = ListResourcesResult(
            resources=[resource],
            next_cursor="next",
        )
        # Act
        result_payload = res.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, "result": result_payload}

        # Assert
        from_protocol = ListResourcesResult.from_protocol(wire_format)
        assert from_protocol == res

    def test_list_resources_uses_alias_for_mime_type(self):
        # Arrange
        resource = Resource(
            uri="https://example.com",
            name="Example",
            mime_type="text/plain",
            size_in_bytes=1,
        )

        # Act
        result = ListResourcesResult(resources=[resource])
        serialized = result.to_protocol()

        # Assert
        serialized_resource = serialized["resources"][0]
        assert "mime_type" not in serialized_resource
        assert serialized_resource["mimeType"] == "text/plain"
        assert serialized_resource["size"] == 1

    def test_list_resources_serializes_with_resource_metadata_and_result_metadata(self):
        # Arrange
        resource = Resource(
            uri="https://example.com",
            name="Example",
            metadata={"ack": "barnacle"},
        )
        result = ListResourcesResult(resources=[resource], metadata={"crazy": "pants"})

        # Act
        serialized = result.to_protocol()

        # Assert
        assert serialized["_meta"] == {"crazy": "pants"}
        assert serialized["resources"][0]["_meta"] == {"ack": "barnacle"}

    def test_resource_result_serializes_with_annotation(self):
        # Arrange
        resource = Resource(
            uri="https://example.com",
            name="Example",
            annotations=Annotations(audience="user", priority=0.5),
        )
        result = ListResourcesResult(resources=[resource])
        expected = {
            "resources": [
                {
                    "uri": "https://example.com",
                    "name": "Example",
                    "annotations": {"audience": ["user"], "priority": 0.5},
                }
            ]
        }

        # Act
        serialized = result.to_protocol()

        # Assert
        assert serialized == expected

    def test_list_resource_template_result_serializes_with_uri_template(self):
        # Arrange
        resource_template = ResourceTemplate(
            name="Test",
            uri_template="https://example.com/{resource_id}",
        )
        result = ListResourceTemplatesResult(
            resource_templates=[resource_template],
        )

        # Act
        serialized = result.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, "result": serialized}

        # Assert
        assert wire_format["result"] == {
            "resourceTemplates": [
                {
                    "name": "Test",
                    "uriTemplate": "https://example.com/{resource_id}",
                }
            ]
        }

    def test_list_resource_template_result_roundtrips(self):
        # Arrange
        resource_template = ResourceTemplate(
            name="Test",
            uri_template="https://example.com/{resource_id}",
        )
        result = ListResourceTemplatesResult(
            resource_templates=[resource_template],
        )

        # Act
        result_payload = result.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, "result": result_payload}
        reconstructed = ListResourceTemplatesResult.from_protocol(wire_format)

        # Assert
        assert reconstructed == result

    def test_read_resource_result_roundtrips(self):
        # Arrange
        result = ReadResourceResult(
            contents=[
                TextResourceContents(uri="https://example.com/", text="Hello, world!"),
            ],
        )

        # Act
        result_payload = result.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, "result": result_payload}
        reconstructed = ReadResourceResult.from_protocol(wire_format)

        # Assert
        assert reconstructed == result

    def test_subscribe_request_method_roundtrips(self):
        # Arrange
        request = SubscribeRequest(uri="https://example.com/")

        # Act
        protocol_data = request.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, **protocol_data}
        reconstructed = SubscribeRequest.from_protocol(wire_format)

        # Assert
        assert reconstructed == request

    def test_unsubscribe_request_method_roundtrips(self):
        # Arrange
        request = UnsubscribeRequest(uri="https://example.com/")

        # Act
        protocol_data = request.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, **protocol_data}
        reconstructed = UnsubscribeRequest.from_protocol(wire_format)

        # Assert
        assert reconstructed == request
