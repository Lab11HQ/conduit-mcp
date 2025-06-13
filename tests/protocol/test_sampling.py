import pytest

from conduit.protocol.sampling import (
    CreateMessageRequest,
    CreateMessageResult,
    ModelPreferences,
    SamplingMessage,
    TextContent,
)


class TestCreateMessageRequest:
    def test_check_create_message_request_serialization_data_matches_protocol(self):
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
        serialized = request.to_protocol()
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

    def test_minimal_create_message_request_roundtrip(self):
        """Minimal request with only required fields"""
        original = CreateMessageRequest(
            messages=[SamplingMessage(role="user", content=TextContent(text="Hi"))],
            max_tokens=50,
        )

        protocol_dict = original.to_protocol()
        reconstructed = CreateMessageRequest.from_protocol(protocol_dict)

        assert reconstructed == original
        assert "metadata" not in protocol_dict["params"]
        assert "_meta" not in protocol_dict["params"]

    def test_full_create_message_request_roundtrip(self):
        """Happy path: full roundtrip with all fields populated"""
        original = CreateMessageRequest(
            messages=[SamplingMessage(role="user", content=TextContent(text="Hello"))],
            max_tokens=150,
            preferences=ModelPreferences(hints=["gpt-4"]),
            system_prompt="You are helpful",
            include_context="thisServer",
            temperature=0.7,
            stop_sequences=["<END>", "\n\n"],
            llm_metadata={"provider": "openai", "custom_field": 42},
            progress_token="req-123",
            metadata={"trace_id": "abc-def", "user_id": 456},
        )

        protocol_dict = original.to_protocol()
        reconstructed = CreateMessageRequest.from_protocol(protocol_dict)

        assert reconstructed == original

        # Verify the protocol structure is correct. Note the MCP metadata is in the
        # _meta field and the LLM metadata is in the metadata field.
        assert protocol_dict["method"] == "sampling/createMessage"
        assert protocol_dict["params"]["metadata"] == {
            "provider": "openai",
            "custom_field": 42,
        }
        assert protocol_dict["params"]["_meta"]["progressToken"] == "req-123"
        assert protocol_dict["params"]["_meta"]["trace_id"] == "abc-def"
        assert protocol_dict["params"]["_meta"]["user_id"] == 456

    def test_create_message_request_metadata_collision_is_handled(self):
        """The gnarly case: both metadata types present with overlapping keys"""
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

        protocol_dict = original.to_protocol()
        # Verify they end up in different places
        assert protocol_dict["params"]["metadata"]["temperature"] == 0.5
        assert protocol_dict["params"]["_meta"]["temperature"] == "trace_temp"

    def test_create_message_request_nested_metadata_roundtrip(self):
        """Complex nested objects in metadata"""
        complex_metadata = {
            "nested": {"deep": {"value": [1, 2, {"even": "deeper"}]}},
            "list": [{"item": 1}, {"item": 2}],
            "unicode": "café 🚀",
            "numbers": {"int": 42, "float": 3.14, "scientific": 1e-10},
        }

        original = CreateMessageRequest(
            messages=[SamplingMessage(role="user", content=TextContent(text="Test"))],
            max_tokens=100,
            llm_metadata=complex_metadata.copy(),
            metadata={"trace": complex_metadata.copy()},
        )

        protocol_dict = original.to_protocol()
        reconstructed = CreateMessageRequest.from_protocol(protocol_dict)

        assert reconstructed == original
        assert reconstructed.llm_metadata == complex_metadata
        assert reconstructed.metadata["trace"] == complex_metadata

    def test_create_message_request_progress_token_set_in_mcp_meta_is_handled(self):
        # Simulate malformed protocol data where progressToken appears in both _meta
        # and metadata
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

        reconstructed = CreateMessageRequest.from_protocol(malformed_protocol)

        # Should prefer the one from _meta
        assert reconstructed.progress_token == "good-token"
        # The evil one should end up in llm_metadata
        assert reconstructed.llm_metadata == {"progressToken": "evil-token"}

    def test_empty_metadata_objects_are_converted_to_none(self):
        """Edge case: empty but present metadata objects"""
        original = CreateMessageRequest(
            messages=[SamplingMessage(role="user", content=TextContent(text="Test"))],
            max_tokens=100,
            llm_metadata={},  # Empty dict
            metadata={},  # Empty dict
        )

        protocol_dict = original.to_protocol()
        reconstructed = CreateMessageRequest.from_protocol(protocol_dict)
        assert reconstructed.llm_metadata is None
        assert reconstructed.metadata is None

        # Neither should appear in protocol
        assert "metadata" not in protocol_dict["params"]
        assert "_meta" not in protocol_dict["params"]

    def test_none_vs_missing_fields_are_handled(self):
        """Subtle difference between None and missing fields"""
        original = CreateMessageRequest(
            messages=[SamplingMessage(role="user", content=TextContent(text="Test"))],
            max_tokens=100,
            temperature=None,  # Explicitly None
            llm_metadata=None,  # Explicitly None
        )

        protocol_dict = original.to_protocol()
        reconstructed = CreateMessageRequest.from_protocol(protocol_dict)

        assert reconstructed == original
        # None fields should not appear in protocol
        assert "temperature" not in protocol_dict["params"]
        assert "metadata" not in protocol_dict["params"]

    def test_create_message_request_roundtrips(self):
        request = CreateMessageRequest(
            messages=[
                SamplingMessage(role="user", content=TextContent(text="Hello, world!"))
            ],
            preferences=ModelPreferences(cost_priority=1),
            max_tokens=100,
        )
        serialized = request.to_protocol()
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
        deserialized = CreateMessageRequest.from_protocol(serialized)
        assert deserialized == request

    def test_create_message_request_rejects_invalid_priority(self):
        with pytest.raises(ValueError):
            CreateMessageRequest(
                messages=[
                    SamplingMessage(
                        role="user", content=TextContent(text="Hello, world!")
                    )
                ],
                # Priority must be between 0 and 1
                preferences=ModelPreferences(cost_priority=1.1),
                max_tokens=100,
            )


class TestCreateMessageResult:
    def test_create_message_result_minimal_roundtrip(self):
        """Test with only required fields"""
        original = CreateMessageResult(
            role="user", content=TextContent(type="text", text="Hi"), model="claude-3"
        )

        protocol_dict = original.to_protocol()
        reconstructed = CreateMessageResult.from_protocol(protocol_dict)

        assert reconstructed == original
        assert reconstructed.stop_reason is None
        assert "stopReason" not in protocol_dict  # None fields excluded

    def test_create_message_result_roundtrip(self):
        """Basic roundtrip test for CreateMessageResult"""
        original = CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text="Hello world"),
            model="gpt-4",
            stop_reason="endTurn",
            metadata={"trace_id": "abc123"},
        )

        protocol_dict = original.to_protocol()
        reconstructed = CreateMessageResult.from_protocol(protocol_dict)

        assert reconstructed == original
        assert protocol_dict["stopReason"] == "endTurn"  # Verify alias works

    def test_create_message_result_custom_stop_reason(self):
        """Test that custom stop reasons (not in the literal) work"""
        original = CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text="Response"),
            model="custom-model",
            stop_reason="customReason",  # Not in the predefined literals
        )

        protocol_dict = original.to_protocol()
        reconstructed = CreateMessageResult.from_protocol(protocol_dict)

        assert reconstructed == original
        assert reconstructed.stop_reason == "customReason"
