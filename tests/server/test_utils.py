from conduit.server import utils


class TestUtils:
    def test_matches_template(self):
        # Arrange
        uri = "file://logs/2024-01-15.log"
        template = "file://logs/{date}.log"

        # Act
        result = utils.matches_template(uri, template)

        # Assert
        assert result is True

    def test_does_not_match_template(self):
        # Arrange
        uri = "file://config.json"
        template = "file://logs/{date}.log"

        # Act
        result = utils.matches_template(uri, template)

        # Assert
        assert result is False

    def test_extract_template_variables(self):
        # Arrange
        uri = "db://users/123/posts/456"
        template = "db://users/{user_id}/posts/{post_id}"

        # Act
        result = utils.extract_template_variables(uri, template)

        # Assert
        assert result == {"user_id": "123", "post_id": "456"}
