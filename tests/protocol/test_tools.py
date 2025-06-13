"""
Test tool-related types.
"""

import pytest
from pydantic import ValidationError

from conduit.protocol.common import ProgressNotification
from conduit.protocol.tools import (
    InputSchema,
    ListToolsRequest,
    ListToolsResult,
    Tool,
    ToolAnnotations,
)


class TestTools:
    def test_call_tool_with_arguments(self):
        # Test the complex case with nested data
        pass

    def test_invalid_wire_data(self):
        # Missing fields, wrong types, etc.
        pass

    def test_list_tools_request_minimal(self):
        # Test with no optional fields
        request = ListToolsRequest()
        protocol_data = request.to_protocol()
        reconstructed = ListToolsRequest.from_protocol(protocol_data)
        assert reconstructed == request
        assert reconstructed.cursor is None
        assert reconstructed.progress_token is None
        assert reconstructed.method == "tools/list"

    def test_list_tools_from_protocol_with_no_data_roundtrips_to_method_only(self):
        protocol_data = {"method": "tools/list"}
        request = ListToolsRequest.from_protocol(protocol_data)
        assert request.method == "tools/list"
        assert request.cursor is None
        assert request.progress_token is None
        assert request.to_protocol() == protocol_data

    def test_list_tools_request_round_trip_with_cursor_and_progress_token(self):
        request = ListToolsRequest(
            cursor="123",
            progress_token="456",
        )
        protocol_data = request.to_protocol()
        reconstructed = ListToolsRequest.from_protocol(protocol_data)
        assert reconstructed == request
        assert reconstructed.cursor == "123"
        assert reconstructed.progress_token == "456"
        assert reconstructed.method == "tools/list"

    def test_list_tools_request_wire_format(self):
        # Verify JSON matches spec exactly
        pass

    def test_progress_notification_roundtrip_without_metadata(self):
        protocol_data = {
            "method": "notifications/progress",
            "params": {
                "progressToken": "progress_token",
                "progress": 0.5,
                "total": 100,
                "message": "test",
            },
        }
        notif = ProgressNotification.from_protocol(protocol_data)
        assert notif.method == "notifications/progress"
        assert notif.progress_token == "progress_token"
        assert notif.progress == 0.5
        assert notif.total == 100
        assert notif.message == "test"
        serialized = notif.to_protocol()
        assert serialized == protocol_data

    def test_progress_notification_roundtrip_with_metadata(self):
        """Test that metadata is preserved during roundtrip"""
        protocol_data = {
            "method": "notifications/progress",
            "params": {
                "progressToken": "progress_token",
                "progress": 0.5,
                "total": 100,
                "message": "test",
                "_meta": {
                    "requestId": "req-123",
                    "timestamp": "2025-06-04T10:00:00Z",
                    "customField": {"nested": "value"},
                },
            },
        }

        # Deserialize
        notif = ProgressNotification.from_protocol(protocol_data)
        assert notif.metadata == {
            "requestId": "req-123",
            "timestamp": "2025-06-04T10:00:00Z",
            "customField": {"nested": "value"},
        }

        # Serialize back
        serialized = notif.to_protocol()
        assert serialized == protocol_data

    def test_progress_notification_ignores_empty_metadata(self):
        """Test handling of empty _meta object"""
        protocol_data = {
            "method": "notifications/progress",
            "params": {
                "progressToken": "progress_token",
                "progress": 0.5,
                "total": 100,
                "_meta": {},
            },
        }

        notif = ProgressNotification.from_protocol(protocol_data)
        assert notif.metadata is None

        serialized = notif.to_protocol()
        assert "_meta" not in serialized["params"]

    def test_list_tools_request_roundtrip(self):
        """Test ListToolsRequest protocol conversion."""
        request = ListToolsRequest(cursor="page_2")

        protocol_data = request.to_protocol()
        reconstructed = ListToolsRequest.from_protocol(protocol_data)

        assert reconstructed == request
        assert reconstructed.method == "tools/list"
        assert reconstructed.cursor == "page_2"

    def test_list_tools_result_roundtrip(self):
        """Test ListToolsResult with tools survives protocol conversion."""
        schema = InputSchema(
            type="object",
            properties={
                "query": {"type": "string", "description": "Search term"},
                "limit": {"type": "integer", "minimum": 1, "default": 10},
            },
            required=["query"],
        )

        tool = Tool(
            name="search_files",
            description="Search for files",
            input_schema=schema,
        )

        result = ListToolsResult(tools=[tool], next_cursor="next_page_token")

        protocol_data = result.to_protocol()
        reconstructed = ListToolsResult.from_protocol(protocol_data)

        assert reconstructed == result
        assert len(reconstructed.tools) == 1
        assert reconstructed.tools[0].name == "search_files"
        assert (
            reconstructed.tools[0].input_schema.properties["query"]["type"] == "string"
        )
        assert reconstructed.next_cursor == "next_page_token"

    def test_input_schema_validation(self):
        """Test that InputSchema validates properly."""
        # Valid schema
        schema = InputSchema(
            type="object", properties={"name": {"type": "string"}}, required=["name"]
        )
        assert schema.type == "object"

        # Type is frozen, should be "object"
        with pytest.raises(ValidationError):
            InputSchema(type="array")  # Should fail if frozen=True works

    def test_list_tools_result_protocol_roundtrip_complex_nested_schema(self):
        schema = InputSchema(
            properties={
                "config": {
                    "type": "object",
                    "properties": {
                        "timeout": {"type": "integer"},
                        "retries": {"type": "integer"},
                    },
                },
                "files": {"type": "array", "items": {"type": "string"}},
            },
            required=["config"],
        )

        annotations = ToolAnnotations(
            title="Complex Tool", read_only_hint=True, destructive_hint=False
        )

        tool = Tool(
            name="complex_tool",
            description="A tool with complex schema",
            input_schema=schema,
            annotations=annotations,
        )
        metadata = {
            "some": "metadata",
            "other": "metadata",
        }

        original_result = ListToolsResult(
            tools=[tool], next_cursor="next_page", metadata=metadata
        )

        # This is the real test - full protocol conversion
        protocol_data = original_result.to_protocol()
        assert protocol_data["_meta"] == metadata
        reconstructed_result = ListToolsResult.from_protocol(protocol_data)

        # Verify the nested Tool survived the roundtrip intact
        assert len(reconstructed_result.tools) == 1
        reconstructed_tool = reconstructed_result.tools[0]

        # Test that complex nested schema properties survived
        assert reconstructed_tool.input_schema.properties["config"]["type"] == "object"
        assert (
            reconstructed_tool.input_schema.properties["config"]["properties"][
                "timeout"
            ]["type"]
            == "integer"
        )
        assert (
            reconstructed_tool.input_schema.properties["files"]["items"]["type"]
            == "string"
        )
        assert reconstructed_tool.input_schema.required == ["config"]

        # Test that annotations survived with proper alias conversion
        assert reconstructed_tool.annotations.title == "Complex Tool"
        assert reconstructed_tool.annotations.read_only_hint is True
        assert reconstructed_tool.annotations.destructive_hint is False

        # Test pagination survived
        assert reconstructed_result.next_cursor == "next_page"

        # Test metadata survived
        assert reconstructed_result.metadata == metadata
