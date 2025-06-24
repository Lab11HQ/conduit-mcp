import pytest

from conduit.protocol.sampling import (
    CreateMessageRequest,
    CreateMessageResult,
    ModelHint,
    ModelPreferences,
    SamplingMessage,
    TextContent,
)


class TestCreateMessageRequest:
    def test_create_message_request_serialization_data_matches_protocol(self):
        # Arrange
        request = CreateMessageRequest(
            messages=[
                SamplingMessage(role="user", content=TextContent(text="Hello, world!"))
            ],
            preferences=ModelPreferences(
                cost_priority=0.5, speed_priority=0.5, intelligence_priority=0.5
            ),
            system_prompt="You are a helpful assistant.",
            include_context="none",
            temperature=0.5,
            max_tokens=100,
            stop_sequences=["\n"],
        )

        # Act
        serialized = request.to_protocol()

        # Assert
        assert serialized == {
            "method": "sampling/createMessage",
            "params": {
                "messages": [
                    {
                        "role": "user",
                        "content": {"type": "text", "text": "Hello, world!"},
                    }
                ],
                "systemPrompt": "You are a helpful assistant.",
                "includeContext": "none",
                "temperature": 0.5,
                "maxTokens": 100,
                "stopSequences": ["\n"],
                "modelPreferences": {
                    "costPriority": 0.5,
                    "speedPriority": 0.5,
                    "intelligencePriority": 0.5,
                },
            },
        }

    def test_create_message_request_roundtrip_with_both_kinds_of_metadata_and_hints(
        self,
    ):
        # Arrange
        original = CreateMessageRequest(
            messages=[SamplingMessage(role="user", content=TextContent(text="Hello"))],
            max_tokens=150,
            preferences=ModelPreferences(hints=[ModelHint(name="gpt")]),
            stop_sequences=["<END>", "\n\n"],
            llm_metadata={"provider_specific": "openai"},
            progress_token="req-123",
            metadata={"trace_id": "abc-def"},
        )

        # Act
        serialized = original.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, **serialized}
        reconstructed = CreateMessageRequest.from_protocol(wire_format)

        # Assert
        assert reconstructed == original

        # Assert
        assert wire_format["method"] == "sampling/createMessage"
        assert wire_format["params"]["modelPreferences"]["hints"] == [{"name": "gpt"}]
        assert wire_format["params"]["stopSequences"] == ["<END>", "\n\n"]
        assert wire_format["params"]["maxTokens"] == 150
        assert wire_format["params"]["_meta"]["progressToken"] == "req-123"
        assert wire_format["params"]["_meta"]["trace_id"] == "abc-def"
        assert wire_format["params"]["metadata"] == {
            "provider_specific": "openai",
        }

    def test_create_message_request_metadata_collision_is_handled(self):
        # Arrange
        original = CreateMessageRequest(
            messages=[SamplingMessage(role="user", content=TextContent(text="Test"))],
            max_tokens=100,
            llm_metadata={
                "temperature": 0.5,
                "model": "gpt-4",
            },  # Could conflict with our temperature field
            metadata={
                "temperature": "trace_temp",
                "model": "trace_model",
            },  # Same keys, different meaning
        )

        # Act
        serialized = original.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, **serialized}
        reconstructed = CreateMessageRequest.from_protocol(wire_format)

        # Assert
        assert reconstructed == original
        assert serialized["params"]["metadata"]["temperature"] == 0.5
        assert serialized["params"]["_meta"]["temperature"] == "trace_temp"

    def test_create_message_request_progress_token_set_in_mcp_meta_is_handled(self):
        # Arrange
        malformed_protocol = {
            "method": "sampling/createMessage",
            "params": {
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": "Test"}}
                ],
                "maxTokens": 100,
                "metadata": {"progressToken": "evil-token"},  # Wrong place!
                "_meta": {"progressToken": "good-token", "other": "data"},
            },
        }

        # Act
        reconstructed = CreateMessageRequest.from_protocol(malformed_protocol)

        # Assert
        assert reconstructed.progress_token == "good-token"
        assert reconstructed.llm_metadata == {"progressToken": "evil-token"}

    def test_empty_metadata_objects_are_converted_to_none(self):
        # Arrange
        original = CreateMessageRequest(
            messages=[SamplingMessage(role="user", content=TextContent(text="Test"))],
            max_tokens=100,
            llm_metadata={},  # Empty dict
            metadata={},  # Empty dict
        )

        # Act
        serialized = original.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, **serialized}
        reconstructed = CreateMessageRequest.from_protocol(wire_format)

        # Assert
        assert reconstructed.llm_metadata is None
        assert reconstructed.metadata is None

        # Assert
        assert "metadata" not in serialized["params"]
        assert "_meta" not in serialized["params"]

    def test_none_vs_missing_fields_are_handled(self):
        # Arrange
        original = CreateMessageRequest(
            messages=[SamplingMessage(role="user", content=TextContent(text="Test"))],
            max_tokens=100,
            temperature=None,  # Explicitly None
            llm_metadata=None,  # Explicitly None
        )

        # Act
        serialized = original.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, **serialized}
        reconstructed = CreateMessageRequest.from_protocol(wire_format)

        # Assert
        assert reconstructed == original
        # None fields should not appear in protocol
        assert "temperature" not in serialized["params"]
        assert "metadata" not in serialized["params"]

    def test_create_message_request_roundtrips(self):
        # Arrange
        request = CreateMessageRequest(
            messages=[
                SamplingMessage(role="user", content=TextContent(text="Hello, world!"))
            ],
            preferences=ModelPreferences(cost_priority=1),
            max_tokens=100,
        )

        # Act
        serialized = request.to_protocol()

        # Assert
        assert serialized == {
            "method": "sampling/createMessage",
            "params": {
                "messages": [
                    {
                        "role": "user",
                        "content": {"type": "text", "text": "Hello, world!"},
                    }
                ],
                "modelPreferences": {"costPriority": 1},
                "maxTokens": 100,
            },
        }

        # Act
        reconstructed = CreateMessageRequest.from_protocol(serialized)

        # Assert
        assert reconstructed == request

    def test_create_message_request_rejects_invalid_priority(self):
        # Arrange and Assert
        with pytest.raises(ValueError):
            CreateMessageRequest(
                messages=[
                    SamplingMessage(
                        role="user", content=TextContent(text="Hello, world!")
                    )
                ],
                preferences=ModelPreferences(cost_priority=1.1),  # BOOM!
                max_tokens=100,
            )


class TestCreateMessageResult:
    def test_create_message_result_minimal_roundtrip(self):
        # Arrange
        original = CreateMessageResult(
            role="user", content=TextContent(type="text", text="Hi"), model="claude-3"
        )

        # Act
        serialized = original.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, "result": serialized}
        reconstructed = CreateMessageResult.from_protocol(wire_format)

        # Assert
        assert reconstructed == original

    def test_create_message_result_roundtrip(self):
        # Arrange
        original = CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text="Hello world"),
            model="gpt-4",
            stop_reason="endTurn",
            metadata={"trace_id": "abc123"},
        )

        # Act
        serialized = original.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, "result": serialized}
        reconstructed = CreateMessageResult.from_protocol(wire_format)

        # Assert
        assert reconstructed == original
        assert serialized["stopReason"] == "endTurn"  # Verify alias works

    def test_create_message_result_custom_stop_reason(self):
        # Arrange
        original = CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text="Response"),
            model="custom-model",
            stop_reason="customReason",  # Not in the predefined literals
        )

        # Act
        serialized = original.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, "result": serialized}
        reconstructed = CreateMessageResult.from_protocol(wire_format)

        # Assert
        assert reconstructed == original
        assert reconstructed.stop_reason == "customReason"
        assert serialized["stopReason"] == "customReason"
