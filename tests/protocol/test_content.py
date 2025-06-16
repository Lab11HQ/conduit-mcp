import pytest
from pydantic import ValidationError

from conduit.protocol.content import Annotations


class TestContent:
    def test_annotation_rejects_priorities_out_of_range(self):
        # Arrange
        with pytest.raises(ValidationError):
            Annotations(priority=100)

    def test_annotation_serialize_with_data(self):
        annotation = Annotations(audience="user", priority=0.5)
        protocol_data = annotation.to_protocol()
        expeceted = {"audience": ["user"], "priority": 0.5}
        assert protocol_data == expeceted
