"""
Test resource-related types.
"""

import pytest
from pydantic import ValidationError

from conduit.protocol.resources import (
    Annotations,
    ListResourcesRequest,
    ListResourcesResult,
    ListResourceTemplatesRequest,
    ListResourceTemplatesResult,
    ReadResourceRequest,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    SubscribeRequest,
    TextResourceContents,
    UnsubscribeRequest,
)


class TestResources:
    def test_list_resource_request_roundtrip_with_cursor(self):
        protocol_data = {"method": "resources/list", "params": {"cursor": "xyz"}}
        req = ListResourcesRequest.from_protocol(protocol_data)
        assert req.cursor == "xyz"
        assert req.method == "resources/list"
        serialized = req.to_protocol()
        assert serialized == protocol_data

    def test_list_resource_request_roundtrip_with_cursor_and_metadata(self):
        protocol_data = {
            "method": "resources/list",
            "params": {"cursor": "xyz", "_meta": {"progressToken": "123"}},
        }
        req = ListResourcesRequest.from_protocol(protocol_data)
        assert req.cursor == "xyz"
        assert req.progress_token == "123"
        assert req.method == "resources/list"
        assert req.to_protocol() == protocol_data

    def test_list_resources_request_rejects_improper_method(self):
        protocol_data = {"method": "dont_list"}
        with pytest.raises(ValueError):
            ListResourcesRequest.from_protocol(protocol_data)

    def test_list_resources_result_roundtrips(self):
        resource = Resource(
            uri="https://example.com",
            name="Example",
            annotations=Annotations(audience="user", priority=0.5),
        )
        res = ListResourcesResult(
            resources=[resource],
            next_cursor="next",
        )
        protocol_data = res.to_protocol()
        from_protocol = ListResourcesResult.from_protocol(protocol_data)
        assert from_protocol == res

    def test_list_resources_uses_alias_for_mime_type(self):
        resource = Resource(
            uri="https://example.com",
            name="Example",
            mime_type="text/plain",
            size_in_bytes=1,
        )
        result = ListResourcesResult(resources=[resource])
        serialized = result.to_protocol()
        serialized_resource = serialized["resources"][0]
        print("protocol", serialized)
        assert "mime_type" not in serialized_resource
        assert serialized_resource["mimeType"] == "text/plain"
        assert serialized_resource["size"] == 1

    def test_list_resource_result_serialize_uri_to_string_not_anyurl(self):
        resource = Resource(
            uri="https://example.com",
            name="Example",
        )
        result = ListResourcesResult(
            resources=[resource],
        )
        assert result.to_protocol()["resources"][0]["uri"] == "https://example.com/"

    def test_annotations_serializes_to_empty_dict_with_no_data(self):
        annotations = Annotations()
        protocol_data = annotations.to_protocol()
        assert protocol_data == {}

    def test_annotation_rejects_priorities_out_of_range(self):
        with pytest.raises(ValidationError):
            Annotations(priority=100)

    def test_annotation_serialize_with_data(self):
        annotation = Annotations(audience="user", priority=0.5)
        protocol_data = annotation.to_protocol()
        expeceted = {"audience": ["user"], "priority": 0.5}
        assert protocol_data == expeceted

    def test_resource_result_serializes_with_annotation(self):
        resource = Resource(
            uri="https://example.com",
            name="Example",
            annotations=Annotations(audience="user", priority=0.5),
        )
        result = ListResourcesResult(resources=[resource])
        expected = {
            "resources": [
                {
                    "uri": "https://example.com/",
                    "name": "Example",
                    "annotations": {"audience": ["user"], "priority": 0.5},
                }
            ]
        }
        assert result.to_protocol() == expected

    def test_resource_rejects_invalid_uri(self):
        with pytest.raises(ValidationError):
            Resource(uri="not-a-uri", name="Test")

    def test_resource_normalizes_uri_schemes_as_expected(self):
        test_cases = [
            ("https://example.com", "https://example.com/"),  # Gets trailing slash
            ("http://example.com", "http://example.com/"),  # Gets trailing slash
            ("file:///path/to/file.txt", "file:///path/to/file.txt"),  # No change
            (
                "data:text/plain;base64,SGVsbG8=",
                "data:text/plain;base64,SGVsbG8=",
            ),  # No change
            ("custom-scheme:resource-id", "custom-scheme:resource-id"),  # No change
            ("urn:isbn:1234", "urn:isbn:1234"),  # No change
        ]

        for input_uri, expected_uri in test_cases:
            resource = Resource(uri=input_uri, name="Test")
            assert str(resource.uri) == expected_uri

    def test_resource_template_serializes_with_uri_template(self):
        resource_template = ResourceTemplate(
            name="Test",
            uri_template="https://example.com/{resource_id}",
        )
        assert resource_template.to_protocol() == {
            "name": "Test",
            "uriTemplate": "https://example.com/{resource_id}",
        }

    def test_list_resource_template_request_method_matches_spec(self):
        spec_method_name = "resources/templates/list"
        request = ListResourceTemplatesRequest()
        assert request.method == spec_method_name

    def test_list_resource_template_result_roundtrips(self):
        resource_template = ResourceTemplate(
            name="Test",
            uri_template="https://example.com/{resource_id}",
        )
        result = ListResourceTemplatesResult(
            resource_templates=[resource_template],
        )
        protocol_data = result.to_protocol()
        from_protocol = ListResourceTemplatesResult.from_protocol(protocol_data)
        assert from_protocol == result

    def test_read_resource_request_method_matches_spec(self):
        spec_method_name = "resources/read"
        request = ReadResourceRequest(uri="https://example.com/")
        assert request.method == spec_method_name

    def test_read_resource_result_roundtrips(self):
        result = ReadResourceResult(
            contents=[
                TextResourceContents(uri="https://example.com/", text="Hello, world!"),
            ],
        )
        protocol_data = result.to_protocol()
        from_protocol = ReadResourceResult.from_protocol(protocol_data)
        assert from_protocol == result

    def test_subscribe_request_method_roundtrips(self):
        request = SubscribeRequest(uri="https://example.com/")
        protocol_data = request.to_protocol()
        from_protocol = SubscribeRequest.from_protocol(protocol_data)
        assert from_protocol == request

    def test_unsubscribe_request_method_roundtrips(self):
        request = UnsubscribeRequest(uri="https://example.com/")
        protocol_data = request.to_protocol()
        from_protocol = UnsubscribeRequest.from_protocol(protocol_data)
        assert from_protocol == request
