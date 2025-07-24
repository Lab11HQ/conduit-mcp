import pytest

from conduit.transport.stdio.shared import parse_json_message, serialize_message


class TestParseJsonMessage:
    def test_parses_valid_json_dict(self):
        """Test that valid JSON dict is parsed correctly."""
        # Arrange
        line = '{"jsonrpc": "2.0", "method": "test", "id": 1}'

        # Act
        result = parse_json_message(line)

        # Assert
        assert result == {"jsonrpc": "2.0", "method": "test", "id": 1}

    def test_strips_whitespace_from_line(self):
        """Test that leading/trailing whitespace is stripped."""
        # Arrange
        line = '  {"jsonrpc": "2.0", "method": "test"}  \n\t'

        # Act
        result = parse_json_message(line)

        # Assert
        assert result == {"jsonrpc": "2.0", "method": "test"}

    def test_returns_none_for_empty_line(self):
        """Test that empty lines are ignored."""
        assert parse_json_message("") is None
        assert parse_json_message("   ") is None
        assert parse_json_message("\n\t  ") is None

    def test_returns_none_for_invalid_json(self):
        """Test that malformed JSON returns None."""
        invalid_json_lines = [
            "not json at all",
            '{"incomplete": json',
            '{"trailing": "comma",}',
            "null",  # Valid JSON but not a dict
            "42",  # Valid JSON but not a dict
            '"string"',  # Valid JSON but not a dict
        ]

        for line in invalid_json_lines:
            assert parse_json_message(line) is None

    def test_returns_none_for_non_dict_json(self):
        """Test that valid JSON that isn't a dict returns None."""
        non_dict_cases = ["null", "42", '"hello"', "[1, 2, 3]", "true", "false"]

        for line in non_dict_cases:
            assert parse_json_message(line) is None

    def test_handles_unicode_content(self):
        """Test parsing JSON with unicode characters."""
        unicode_json = '{"message": "Hello 世界", "emoji": "🚀"}'

        result = parse_json_message(unicode_json)

        assert result == {"message": "Hello 世界", "emoji": "🚀"}


class TestSerializeMessage:
    def test_uses_compact_format_with_unicode(self):
        """Test that serialization uses our standard format."""
        # Arrange
        message = {"greeting": "Hello 世界", "nested": {"key": "value"}}

        # Act
        result = serialize_message(message)

        # Assert
        assert result == '{"greeting":"Hello 世界","nested":{"key":"value"}}'

    def test_wraps_json_errors_as_value_error(self):
        """Test that JSON serialization errors get wrapped."""
        # Arrange
        message = {"method": lambda: None}  # Unserializable

        # Act/Assert
        with pytest.raises(ValueError):
            serialize_message(message)
