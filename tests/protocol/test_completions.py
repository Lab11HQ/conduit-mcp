import pytest
from pydantic import ValidationError

from conduit.protocol.completions import (
    CompleteRequest,
    CompleteResult,
    Completion,
    CompletionArgument,
)
from conduit.protocol.prompts import PromptReference


class TestCompletions:
    def test_complete_request_round_trip(self):
        # Arrange
        request = CompleteRequest(
            ref=PromptReference(name="test-prompt"),
            argument=CompletionArgument(name="arg1", value="partial_value"),
        )

        # Act
        serialized = request.to_protocol()
        serialized["id"] = 1
        serialized["jsonrpc"] = "2.0"
        reconstructed = CompleteRequest.from_protocol(serialized)

        # Assert
        assert serialized == {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "completion/complete",
            "params": {
                "ref": {"type": "ref/prompt", "name": "test-prompt"},
                "argument": {"name": "arg1", "value": "partial_value"},
            },
        }

        assert reconstructed == request

    def test_complete_result_round_trip(self):
        # Arrange
        result = CompleteResult(
            completion=Completion(
                values=["option1", "option2", "option3"], total=10, has_more=True
            )
        )

        # Act
        serialized = result.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, "result": serialized}
        reconstructed = CompleteResult.from_protocol(wire_format)

        # Assert
        assert reconstructed == result

    def test_complete_result_uses_alias_for_has_more(self):
        # Arrange
        result = CompleteResult(
            completion=Completion(values=["test1", "test2"], has_more=False)
        )

        # Act
        serialized = result.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, "result": serialized}
        reconstructed = CompleteResult.from_protocol(wire_format)

        # Assert
        assert serialized["completion"]["hasMore"] is False
        assert reconstructed == result

    def test_completion_respects_max_length_constraint_of_100_values(self):
        # Arrange
        valid_completion = Completion(values=["value"] * 100)
        assert len(valid_completion.values) == 100

        # Assert
        with pytest.raises(ValidationError) as exc_info:
            Completion(values=["value"] * 101)

        # Assert
        error_details = str(exc_info.value)
        assert "100" in error_details or "max_length" in error_details

    def test_completion_optional_fields_roundtrip(self):
        # Arrange
        completion = Completion(values=["single_option"])

        # Assert
        assert completion.values == ["single_option"]
        assert completion.total is None
        assert completion.has_more is None

        # Act
        result = CompleteResult(completion=completion)
        serialized = result.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, "result": serialized}
        reconstructed = CompleteResult.from_protocol(wire_format)

        # Assert
        assert reconstructed.completion.values == ["single_option"]
        assert reconstructed.completion.total is None
        assert reconstructed.completion.has_more is None
