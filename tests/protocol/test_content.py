import pytest
from pydantic import ValidationError

from conduit.protocol.content import Annotations


class TestContent:
    def test_annotation_rejects_priorities_out_of_range(self):
        # Arrange & Act & Assert
        with pytest.raises(ValidationError):
            Annotations(priority=100)

    def test_annotation_accepts_last_modified_iso_8601(self):
        # Arrange
        annotation = Annotations(last_modified="2021-01-01")

        # Assert
        assert annotation.last_modified == "2021-01-01"

    def test_annotation_rejects_last_modified_not_iso_8601(self):
        # Arrange & Act & Assert
        with pytest.raises(ValidationError):
            Annotations(last_modified="Jan 1, 2021")
