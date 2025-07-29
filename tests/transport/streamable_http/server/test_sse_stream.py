import json

import pytest

from conduit.transport.streamable_http.server.sse_stream import SSEStream


class TestSSEStream:
    async def test_send_message_yields_event(self):
        # Arrange
        stream = SSEStream("test-stream", "client-123", "request-456")
        test_message = {"id": "req-1", "method": "test", "params": {}}

        # Act
        await stream.send_message(test_message)
        event_gen = stream.event_generator()

        # Get the first event
        event = await event_gen.__anext__()

        # Assert
        assert event is not None
        assert isinstance(event, str)
        assert event.startswith("data: ")
        assert event.endswith("\n\n")

        # Verify the JSON content
        event_data = event[6:-2]  # Strip "data: " and "\n\n"
        parsed_message = json.loads(event_data)
        assert parsed_message == test_message

        # Verify stream properties
        assert stream.stream_id == "test-stream"
        assert stream.client_id == "client-123"
        assert stream.request_id == "request-456"

    async def test_explicit_close_stops_event_generator(self):
        """Test that explicitly closing the stream stops the event generator."""
        # Arrange
        stream = SSEStream("test-stream", "client-123", "request-456")
        test_message = {"id": "req-1", "method": "test", "params": {}}

        # Act
        await stream.send_message(test_message)
        await stream.close()  # Explicit close

        event_gen = stream.event_generator()

        # Get the first event (our test message)
        event = await event_gen.__anext__()

        # Assert first event is our message
        event_data = event[6:-2]  # Strip "data: " and "\n\n"
        parsed_message = json.loads(event_data)
        assert parsed_message == test_message

        # Generator should stop after close sentinel
        with pytest.raises(StopAsyncIteration):
            await event_gen.__anext__()

    async def test_response_message_auto_closes_event_generator(self):
        """Test that sending a response message auto-closes the generator."""
        # Arrange
        stream = SSEStream("test-stream", "client-123", "request-456")
        response_message = {"id": "req-1", "result": {"success": True}}

        # Act
        await stream.send_message(response_message)
        event_gen = stream.event_generator()

        # Get the response event
        event = await event_gen.__anext__()

        # Assert response was sent
        event_data = event[6:-2]
        parsed_message = json.loads(event_data)
        assert parsed_message == response_message

        # Generator should auto-close after response
        with pytest.raises(StopAsyncIteration):
            await event_gen.__anext__()

    async def test_is_response_detection(self):
        """Test response detection logic."""
        # Arrange
        stream = SSEStream("test-stream", "client-123", "request-456")

        # Act & Assert
        # Valid responses
        assert stream.is_response({"id": "req-1", "result": {"data": "test"}}) is True
        assert (
            stream.is_response(
                {"id": "req-1", "error": {"code": -1, "message": "fail"}}
            )
            is True
        )

        # Invalid responses (not responses)
        assert stream.is_response({"method": "test", "params": {}}) is False
        assert stream.is_response({"id": "req-1"}) is False  # Missing result/error
        assert (
            stream.is_response({"id": "req-1", "result": {}, "error": {}}) is False
        )  # Both result and error
        assert stream.is_response({"result": {"data": "test"}}) is False  # Missing id
        assert stream.is_response({"id": True, "result": {}}) is False  # Boolean id
