from conduit.protocol.elicitation import (
    ElicitRequest,
    ElicitResult,
    NumberSchema,
    RequestedSchema,
    StringSchema,
)


class TestElicitation:
    def test_elicitation_request_roundtrip(self):
        # Arrange
        elicitation_request = ElicitRequest(
            message="Please enter your name",
            requested_schema=RequestedSchema(
                type="object",
                properties={
                    "string_schema": StringSchema(
                        title="Email",
                        description="Your email",
                        format="email",
                    ),
                    "number_schema": NumberSchema(
                        type="integer",
                        title="Age",
                        description="Your age",
                        minimum=0,
                        maximum=220,
                    ),
                },
                required=["string_schema"],
            ),
        )

        # Act
        serialized = elicitation_request.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, **serialized}
        reconstructed = ElicitRequest.from_protocol(wire_format)

        # Assert Round Trip
        assert reconstructed == elicitation_request

        # Assert Wire Format
        assert wire_format["params"]["message"] == "Please enter your name"
        assert wire_format["params"]["requestedSchema"] == {
            "type": "object",
            "properties": {
                "string_schema": {
                    "type": "string",
                    "title": "Email",
                    "description": "Your email",
                    "format": "email",
                },
                "number_schema": {
                    "type": "integer",
                    "title": "Age",
                    "description": "Your age",
                    "minimum": 0,
                    "maximum": 220,
                },
            },
            "required": ["string_schema"],
        }

        # Assert specific schema serialization
        string_schema_wire = wire_format["params"]["requestedSchema"]["properties"][
            "string_schema"
        ]
        assert string_schema_wire["format"] == "email"
        assert "minLength" not in string_schema_wire

    def test_elicitation_result_roundtrip(self):
        # Arrange
        elicitation_result = ElicitResult(
            action="accept",
            content={"user_email": "test@example.com"},
        )

        # Act
        serialized = elicitation_result.to_protocol()
        wire_format = {"jsonrpc": "2.0", "id": 1, "result": serialized}
        reconstructed = ElicitResult.from_protocol(wire_format)

        # Assert Round Trip
        assert reconstructed == elicitation_result

        # Assert Wire Format
        assert wire_format["result"]["action"] == "accept"
        assert wire_format["result"]["content"] == {
            "user_email": "test@example.com",
        }

    def test_elicitation_result_decline_no_content(self):
        # Test that decline/cancel don't include content
        result = ElicitResult(action="decline")

        serialized = result.to_protocol()

        assert serialized["action"] == "decline"
        assert "content" not in serialized  # Should be omitted when decline
