import pytest
from pydantic import ValidationError

from conduit.protocol.completions import (
    CompleteRequest,
    CompleteResult,
    Completion,
    CompletionArgument,
)
from conduit.protocol.prompts import PromptReference
from conduit.protocol.resources import ResourceReference


class TestCompletions:
    def test_complete_request_round_trip(self):
        """Test CompleteRequest to_protocol and from_protocol round trip."""
        # Test with PromptReference
        prompt_request = CompleteRequest(
            ref=PromptReference(name="test-prompt"),
            argument=CompletionArgument(name="arg1", value="partial_value"),
        )
        protocol_data = prompt_request.to_protocol()
        reconstructed = CompleteRequest.from_protocol(protocol_data)

        assert reconstructed.method == "completion/complete"
        assert reconstructed.ref.type == "ref/prompt"
        assert reconstructed.ref.name == "test-prompt"
        assert reconstructed.argument.name == "arg1"
        assert reconstructed.argument.value == "partial_value"

        # Test with ResourceReference
        resource_request = CompleteRequest(
            ref=ResourceReference(uri="file:///path/to/resource"),
            argument=CompletionArgument(name="param", value="test"),
        )

        protocol_data = resource_request.to_protocol()
        reconstructed = CompleteRequest.from_protocol(protocol_data)
        print("reconstructed", reconstructed)
        print("-" * 100)
        print("protocol_data", protocol_data)

        assert reconstructed.ref.type == "ref/resource"
        assert str(reconstructed.ref.uri) == "file:///path/to/resource"

    def test_complete_result_round_trip(self):
        """Test CompleteResult to_protocol and from_protocol round trip."""
        result = CompleteResult(
            completion=Completion(
                values=["option1", "option2", "option3"], total=10, has_more=True
            )
        )

        protocol_data = result.to_protocol()
        reconstructed = CompleteResult.from_protocol(protocol_data)

        assert reconstructed.completion.values == ["option1", "option2", "option3"]
        assert reconstructed.completion.total == 10
        assert reconstructed.completion.has_more is True

    def test_complete_result_uses_alias(self):
        """Test that CompleteResult generates correct protocol format."""
        result = CompleteResult(
            completion=Completion(values=["test1", "test2"], has_more=False)
        )

        protocol_data = result.to_protocol()

        # Should have hasMore in camelCase due to alias
        assert protocol_data["completion"]["hasMore"] is False
        assert protocol_data["completion"]["values"] == ["test1", "test2"]
        assert "total" not in protocol_data["completion"]  # Excluded when None

    def test_completion_respects_max_length_constraint_of_100_values(self):
        # This should work
        valid_completion = Completion(values=["value"] * 100)
        assert len(valid_completion.values) == 100

        # This should raise ValidationError
        with pytest.raises(ValidationError) as exc_info:
            Completion(values=["value"] * 101)

        # Check that the error mentions the constraint
        error_details = str(exc_info.value)
        assert "100" in error_details or "max_length" in error_details

    def test_completion_optional_fields_roundtrip(self):
        """Test Completion with minimal required fields."""
        completion = Completion(values=["single_option"])

        assert completion.values == ["single_option"]
        assert completion.total is None
        assert completion.has_more is None

        # Should still round-trip correctly
        result = CompleteResult(completion=completion)
        protocol_data = result.to_protocol()
        reconstructed = CompleteResult.from_protocol(protocol_data)

        assert reconstructed.completion.values == ["single_option"]
        assert reconstructed.completion.total is None
        assert reconstructed.completion.has_more is None
