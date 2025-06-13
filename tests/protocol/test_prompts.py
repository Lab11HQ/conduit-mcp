from conduit.protocol.prompts import (
    GetPromptRequest,
    GetPromptResult,
    ListPromptsRequest,
    ListPromptsResult,
    Prompt,
    PromptMessage,
    TextContent,
)


class TestPrompts:
    def test_list_prompts_request_method_matches_spec(self):
        request = ListPromptsRequest()
        assert request.method == "prompts/list"

    def test_list_prompts_result_roundtrips(self):
        result = ListPromptsResult(
            prompts=[Prompt(name="test", description="Test prompt")],
        )
        protocol_data = result.to_protocol()
        from_protocol = ListPromptsResult.from_protocol(protocol_data)
        assert from_protocol == result

    def test_prompt_list_result_serializes_with_metadata(self):
        result = ListPromptsResult(
            prompts=[Prompt(name="Test")], metadata={"some_meta": "data"}
        )
        expected = {"prompts": [{"name": "Test"}], "_meta": {"some_meta": "data"}}
        serialized = result.to_protocol()
        print("serialized", serialized)
        print("expected", expected)
        assert serialized == expected

    def test_get_prompt_request_serializes_with_args(self):
        request = GetPromptRequest(name="Test", arguments={"arg1": "value1"})
        expected = {
            "method": "prompts/get",
            "params": {
                "name": "Test",
                "arguments": {"arg1": "value1"},
            },
        }
        serialized = request.to_protocol()
        assert serialized == expected

    def test_get_prompt_request_roundtrips(self):
        request = GetPromptRequest(name="Test", arguments={"arg1": "value1"})
        protocol_data = request.to_protocol()
        assert request == GetPromptRequest.from_protocol(protocol_data)

    def test_get_prompt_result_serializes_with_messages(self):
        result = GetPromptResult(
            messages=[PromptMessage(role="user", content=TextContent(text="Hello"))]
        )
        expected = {
            "messages": [{"role": "user", "content": {"type": "text", "text": "Hello"}}]
        }
        serialized = result.to_protocol()
        assert serialized == expected
