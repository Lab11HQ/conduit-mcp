from conduit.protocol.prompts import (
    PromptArgument,
    GetPromptRequest,
    GetPromptResult,
    ListPromptsResult,
    Prompt,
    PromptMessage,
    TextContent,
)


class TestPrompts:
    def test_list_prompts_result_roundtrips(self):
        # Arrange
        original = ListPromptsResult(
            prompts=[Prompt(name="test", description="Test prompt")],
        )

        # Act
        result_payload = original.to_protocol()
        jsonrpc_response = {"jsonrpc": "2.0", "id": 1, "result": result_payload}
        reconstructed = ListPromptsResult.from_protocol(jsonrpc_response)

        # Assert
        assert reconstructed == original
        assert reconstructed.to_protocol() == result_payload

    def test_prompt_list_result_roundtrips_with_metadata(self):
        # Arrange
        original = ListPromptsResult(
            prompts=[Prompt(name="Test")], metadata={"some_meta": "data"}
        )

        # Act
        result_payload = original.to_protocol()
        jsonrpc_response = {"jsonrpc": "2.0", "id": 1, "result": result_payload}
        reconstructed = ListPromptsResult.from_protocol(jsonrpc_response)

        # Assert
        assert reconstructed == original
        assert reconstructed.to_protocol() == result_payload

    def test_list_prompt_result_roundtrip_with_prompt_arguments(self):
        # Arrange
        original = ListPromptsResult(
            prompts=[
                Prompt(
                    name="Test",
                    arguments=[
                        PromptArgument(
                            name="arg1", description="Argument 1", required=True
                        )
                    ],
                )
            ]
        )
        expected_payload = {
            "prompts": [
                {
                    "name": "Test",
                    "arguments": [
                        {"name": "arg1", "description": "Argument 1", "required": True}
                    ],
                }
            ]
        }

        # Act
        result_payload = original.to_protocol()
        jsonrpc_response = {"jsonrpc": "2.0", "id": 1, "result": result_payload}
        reconstructed = ListPromptsResult.from_protocol(jsonrpc_response)

        # Assert
        assert reconstructed == original
        assert reconstructed.to_protocol() == expected_payload

    def test_get_prompt_request_roundtrips_with_args(self):
        # Arrange
        request = GetPromptRequest(name="Test", arguments={"arg1": "value1"})
        expected = {
            "method": "prompts/get",
            "params": {
                "name": "Test",
                "arguments": {"arg1": "value1"},
            },
        }

        # Act
        serialized = request.to_protocol()

        # Assert
        assert serialized == expected

    def test_get_prompt_request_roundtrips(self):
        # Arrange
        request = GetPromptRequest(name="Test", arguments={"arg1": "value1"})
        expected = {
            "method": "prompts/get",
            "params": {"name": "Test", "arguments": {"arg1": "value1"}},
        }

        # Act
        serialized = request.to_protocol()

        # Assert
        assert serialized == expected
        assert request == GetPromptRequest.from_protocol(serialized)

    def test_get_prompt_result_roundtrips_with_messages(self):
        # Arrange
        result = GetPromptResult(
            messages=[PromptMessage(role="user", content=TextContent(text="Hello"))]
        )

        # Act
        result_payload = result.to_protocol()
        jsonrpc_response = {"jsonrpc": "2.0", "id": 1, "result": result_payload}
        reconstructed = GetPromptResult.from_protocol(jsonrpc_response)

        # Assert
        assert reconstructed == result
        assert reconstructed.to_protocol() == result_payload
