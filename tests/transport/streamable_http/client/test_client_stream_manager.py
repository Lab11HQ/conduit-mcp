import asyncio
from unittest.mock import AsyncMock, MagicMock

from conduit.transport.streamable_http.client.stream_manager import StreamManager


class TestStreamManager:
    def setup_method(self):
        self.http_client = MagicMock()
        self.stream_manager = StreamManager(self.http_client)
        self.message_queue = asyncio.Queue()

    async def test_start_stream_listener_creates_and_tracks_task(self):
        # Arrange
        server_id = "test-server"
        mock_response = MagicMock()

        # Mock the private listen method to avoid SSE complexity
        self.stream_manager._listen_to_sse_stream = AsyncMock()

        # Act
        task = await self.stream_manager.start_stream_listener(
            server_id, mock_response, self.message_queue
        )

        # Assert - Task was created and tracked
        assert isinstance(task, asyncio.Task)
        assert server_id in self.stream_manager._server_listeners
        assert task in self.stream_manager._server_listeners[server_id]
        assert self.stream_manager.get_server_stream_count(server_id) == 1

        # Cleanup
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_multiple_listeners_per_server_tracked_separately(self):
        # Arrange
        server_id = "test-server"
        mock_response1 = MagicMock()
        mock_response2 = MagicMock()

        # Mock the listen method to complete immediately
        self.stream_manager._listen_to_sse_stream = AsyncMock()

        # Act - Start two listeners for same server
        task1 = await self.stream_manager.start_stream_listener(
            server_id, mock_response1, self.message_queue
        )
        task2 = await self.stream_manager.start_stream_listener(
            server_id, mock_response2, self.message_queue
        )

        # Assert - Both tasks tracked under same server
        assert self.stream_manager.get_server_stream_count(server_id) == 2
        server_tasks = self.stream_manager._server_listeners[server_id]
        assert task1 in server_tasks
        assert task2 in server_tasks

        # Cleanup
        for task in [task1, task2]:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def test_listeners_isolated_by_server(self):
        # Arrange
        server1_id = "server-1"
        server2_id = "server-2"
        mock_response = MagicMock()

        self.stream_manager._listen_to_sse_stream = AsyncMock()

        # Act
        task1 = await self.stream_manager.start_stream_listener(
            server1_id, mock_response, self.message_queue
        )
        task2 = await self.stream_manager.start_stream_listener(
            server2_id, mock_response, self.message_queue
        )

        # Assert - Each server has its own tracking
        assert self.stream_manager.get_server_stream_count(server1_id) == 1
        assert self.stream_manager.get_server_stream_count(server2_id) == 1
        assert task1 in self.stream_manager._server_listeners[server1_id]
        assert task2 in self.stream_manager._server_listeners[server2_id]

        # Cleanup
        for task in [task1, task2]:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def test_stop_server_listeners_cancels_all_server_tasks(self):
        # Arrange
        server_id = "test-server"
        mock_response = MagicMock()

        # Mock listen method to run indefinitely until cancelled
        async def mock_listen(*args):
            try:
                await asyncio.sleep(10)  # Long sleep, should be cancelled
            except asyncio.CancelledError:
                raise

        self.stream_manager._listen_to_sse_stream = mock_listen

        # Start multiple listeners
        task1 = await self.stream_manager.start_stream_listener(
            server_id, mock_response, self.message_queue
        )
        task2 = await self.stream_manager.start_stream_listener(
            server_id, mock_response, self.message_queue
        )

        # Verify they're running
        assert not task1.done()
        assert not task2.done()
        assert self.stream_manager.get_server_stream_count(server_id) == 2

        # Act - Stop all listeners for the server
        self.stream_manager.stop_server_listeners(server_id)

        for task in [task1, task2]:
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Assert - All tasks cancelled and tracking cleared
        assert self.stream_manager.get_server_stream_count(server_id) == 0

    async def test_task_cleanup_on_completion(self):
        # Arrange
        server_id = "test-server"
        mock_response = MagicMock()

        # Create a mock where we can control completion
        completion_event = asyncio.Event()

        async def controlled_mock(*args):
            await completion_event.wait()

        self.stream_manager._listen_to_sse_stream = controlled_mock

        # Act - Start listener
        task = await self.stream_manager.start_stream_listener(
            server_id, mock_response, self.message_queue
        )

        # Verify task is tracked and running
        assert self.stream_manager.get_server_stream_count(server_id) == 1
        assert not task.done()

        # Complete the task
        completion_event.set()
        await task
        await asyncio.sleep(0.01)  # Let done callback run

        # Assert cleanup happened
        assert self.stream_manager.get_server_stream_count(server_id) == 0

    async def test_process_sse_event_valid_json(self):
        """Test valid JSON SSE event gets parsed and queued."""
        # Mock SSE event
        mock_event = MagicMock()
        mock_event.data = '{"jsonrpc": "2.0", "method": "ping", "id": 1}'
        mock_event.id = "event-123"

        # Process it
        await self.stream_manager._process_sse_event(
            "test-server", mock_event, self.message_queue
        )

        # Verify message was queued
        message = await self.message_queue.get()
        assert message.server_id == "test-server"
        assert message.payload == {"jsonrpc": "2.0", "method": "ping", "id": 1}
        assert message.metadata == {"sse_event_id": "event-123"}

    async def test_process_sse_event_invalid_json_does_not_raise(self):
        mock_event = MagicMock()
        mock_event.data = "invalid json{"

        # Should not raise, should log warning
        await self.stream_manager._process_sse_event(
            "test-server", mock_event, self.message_queue
        )

        # Queue should be empty
        assert self.message_queue.empty()
