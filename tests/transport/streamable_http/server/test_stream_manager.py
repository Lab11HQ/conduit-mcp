import json

import pytest

from conduit.transport.streamable_http.server.stream_manager import StreamManager


class TestStreamManager:
    async def test_create_stream_and_send_message_happy_path(self):
        """Test creating a stream and sending a message successfully."""
        # Arrange
        manager = StreamManager()
        client_id = "client-123"
        request_id = "req-456"
        test_message = {"id": "msg-1", "method": "test", "params": {"data": "hello"}}

        # Act
        stream = await manager.create_stream(client_id, request_id)
        success = await manager.send_to_existing_stream(
            client_id, test_message, originating_request_id=request_id
        )

        # Assert
        assert success is True
        assert stream is not None
        assert stream.client_id == client_id
        assert stream.request_id == request_id
        assert isinstance(stream.stream_id, str)

        # Verify the message was queued by getting it from the event generator
        event_gen = stream.event_generator()
        event = await event_gen.__anext__()

        assert event.startswith("data: ")
        assert event.endswith("\n\n")

        # Verify the JSON content
        event_data = event[6:-2]  # Strip "data: " and "\n\n"
        parsed_message = json.loads(event_data)
        assert parsed_message == test_message

    async def test_cleanup_client_streams(self):
        """Test cleaning up all streams for a client."""
        # Arrange
        manager = StreamManager()
        client_id = "client-123"
        other_client_id = "client-456"

        # Create multiple streams for the target client
        stream1 = await manager.create_stream(client_id, "req-1")
        stream2 = await manager.create_stream(client_id, "req-2")
        stream3 = await manager.create_stream(client_id)  # No request_id

        # Create a stream for another client (should not be affected)
        other_stream = await manager.create_stream(other_client_id, "req-3")

        # Act
        await manager.cleanup_client_streams(client_id)

        # Assert
        # Target client streams should be cleaned up
        assert manager.get_stream_by_id(stream1.stream_id) is None
        assert manager.get_stream_by_id(stream2.stream_id) is None
        assert manager.get_stream_by_id(stream3.stream_id) is None

        # Other client stream should remain
        assert manager.get_stream_by_id(other_stream.stream_id) is not None

        # Verify streams are actually closed by trying to get events
        # (should get StopAsyncIteration immediately due to close sentinel)
        with pytest.raises(StopAsyncIteration):
            event_gen = stream1.event_generator()
            await event_gen.__anext__()

    async def test_cleanup_nonexistent_client(self):
        """Test cleaning up streams for a client that doesn't exist."""
        # Arrange
        manager = StreamManager()
        fake_client_id = "nonexistent-client"

        # Act & Assert - should not raise any errors
        await manager.cleanup_client_streams(fake_client_id)

    async def test_close_all_streams(self):
        """Test closing all streams in the manager."""
        # Arrange
        manager = StreamManager()

        # Create streams for multiple clients
        stream1 = await manager.create_stream("client-1", "req-1")
        stream2 = await manager.create_stream("client-2", "req-2")
        stream3 = await manager.create_stream("client-1")  # Another for client-1

        # Act
        await manager.close_all_streams()

        # Assert
        # All streams should be cleaned up
        assert manager.get_stream_by_id(stream1.stream_id) is None
        assert manager.get_stream_by_id(stream2.stream_id) is None
        assert manager.get_stream_by_id(stream3.stream_id) is None

        # All streams should be closed
        for stream in [stream1, stream2, stream3]:
            with pytest.raises(StopAsyncIteration):
                event_gen = stream.event_generator()
                await event_gen.__anext__()

    async def test_send_to_nonexistent_stream(self):
        """Test sending to streams that don't exist."""
        # Arrange
        manager = StreamManager()
        client_id = "client-123"
        message = {"id": "msg-1", "method": "test"}

        # Act & Assert
        # No streams exist at all
        result = await manager.send_to_existing_stream(client_id, message, "req-1")
        assert result is False

        # Stream exists but wrong request_id
        await manager.create_stream(client_id, "req-2")
        result = await manager.send_to_existing_stream(client_id, message, "req-1")
        assert result is False

        # Client has no streams for fallback case
        result = await manager.send_to_existing_stream("nonexistent-client", message)
        assert result is False
