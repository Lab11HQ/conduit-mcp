import asyncio

from conduit.protocol.base import INTERNAL_ERROR, Error, Result
from conduit.protocol.common import EmptyResult, PingRequest
from conduit.shared.request_tracker import RequestTracker


class TestRequestTracker:
    def setup_method(self):
        self.tracker = RequestTracker()

    async def test_track_outbound_request(self):
        # Arrange
        peer_id = "test-peer-123"
        request_id = "req-456"
        request = PingRequest()
        future = asyncio.Future[Result | Error]()

        # Act
        self.tracker.track_outbound_request(peer_id, request_id, request, future)

        # Assert
        result = self.tracker.get_outbound_request(peer_id, request_id)
        assert result is not None

        tracked_req, tracked_future = result
        assert tracked_req is request
        assert tracked_future is future
        assert not future.done()  # Future should not be resolved yet

        # Verify peer is tracked
        assert peer_id in self.tracker.get_peer_ids()
        assert request_id in self.tracker.get_peer_outbound_request_ids(peer_id)

    async def test_track_inbound_request(self):
        # Arrange
        peer_id = "test-peer-789"
        request_id = "req-101"
        request = PingRequest()

        # Create a simple async task for testing
        async def dummy_handler():
            await asyncio.sleep(0.01)  # Brief delay to simulate work

        task = asyncio.create_task(dummy_handler())

        # Act
        self.tracker.track_inbound_request(peer_id, request_id, request, task)

        # Assert
        result = self.tracker.get_inbound_request(peer_id, request_id)
        assert result is not None

        tracked_req, tracked_task = result
        assert tracked_req is request
        assert tracked_task is task

        # Verify peer is tracked
        assert peer_id in self.tracker.get_peer_ids()
        assert request_id in self.tracker.get_peer_inbound_request_ids(peer_id)

        # Clean up the task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_resolve_outbound_request(self):
        # Arrange
        peer_id = "test-peer-123"
        request_id = "req-456"
        request = PingRequest()
        future = asyncio.Future[Result | Error]()

        # Track the request first
        self.tracker.track_outbound_request(peer_id, request_id, request, future)

        # Create a result to resolve with
        result = EmptyResult()

        # Act
        self.tracker.resolve_outbound_request(peer_id, request_id, result)

        # Assert
        assert future.done()
        assert future.result() is result

        # Verify request is removed from tracking
        assert self.tracker.get_outbound_request(peer_id, request_id) is None
        assert request_id not in self.tracker.get_peer_outbound_request_ids(peer_id)

    async def test_resolve_outbound_request_peer_not_found(self):
        # Arrange
        nonexistent_peer = "ghost-peer"
        request_id = "req-123"

        result = EmptyResult()

        # Act & Assert - should not raise an exception
        self.tracker.resolve_outbound_request(nonexistent_peer, request_id, result)

        # Verify no side effects
        assert nonexistent_peer not in self.tracker.get_peer_ids()

    async def test_resolve_outbound_request_request_not_found(self):
        # Arrange
        peer_id = "test-peer-123"
        nonexistent_request = "ghost-request"

        # Track a different request to ensure peer exists
        real_request = PingRequest()
        real_future = asyncio.Future[Result | Error]()
        self.tracker.track_outbound_request(
            peer_id, "real-req", real_request, real_future
        )

        result = EmptyResult()

        # Act & Assert - should not raise an exception
        self.tracker.resolve_outbound_request(peer_id, nonexistent_request, result)

        # Verify no side effects on existing requests
        assert self.tracker.get_outbound_request(peer_id, "real-req") is not None
        assert not real_future.done()

    async def test_resolve_outbound_request_with_error(self):
        # Arrange
        peer_id = "test-peer-456"
        request_id = "req-789"
        request = PingRequest()
        future = asyncio.Future[Result | Error]()

        self.tracker.track_outbound_request(peer_id, request_id, request, future)

        # Create an error to resolve with
        error = Error(code=INTERNAL_ERROR, message="Something went wrong")

        # Act
        self.tracker.resolve_outbound_request(peer_id, request_id, error)

        # Assert
        assert future.done()
        assert future.result() is error

        # Verify request is removed from tracking
        assert self.tracker.get_outbound_request(peer_id, request_id) is None

    async def test_resolve_outbound_request_already_resolved_future(self):
        # Arrange
        peer_id = "test-peer-789"
        request_id = "req-101"
        request = PingRequest()
        future = asyncio.Future[Result | Error]()

        # Pre-resolve the future
        first_result = EmptyResult()
        future.set_result(first_result)

        self.tracker.track_outbound_request(peer_id, request_id, request, future)

        # Try to resolve again with different result
        second_result = EmptyResult()

        # Act & Assert - should not raise an InvalidStateError since we check if the
        # future is done before setting the result.
        self.tracker.resolve_outbound_request(peer_id, request_id, second_result)

        # Assert original result is preserved
        assert future.result() is first_result

        # Verify request is still removed from tracking
        assert self.tracker.get_outbound_request(peer_id, request_id) is None

    async def test_cancel_inbound_request(self):
        # Arrange
        peer_id = "test-peer-123"
        request_id = "req-456"
        request = PingRequest()

        # Create a task that will run for a bit
        async def long_running_handler():
            await asyncio.sleep(1.0)  # Long enough to cancel before completion

        task = asyncio.create_task(long_running_handler())

        self.tracker.track_inbound_request(peer_id, request_id, request, task)

        # Verify task is running
        assert not task.done()

        # Act
        self.tracker.cancel_inbound_request(peer_id, request_id)

        # Wait for the task to be cancelled
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Verify request is removed from tracking
        assert self.tracker.get_inbound_request(peer_id, request_id) is None
        assert request_id not in self.tracker.get_peer_inbound_request_ids(peer_id)

    async def test_cancel_inbound_request_peer_not_found(self):
        # Arrange
        nonexistent_peer = "ghost-peer"
        request_id = "req-123"

        # Act & Assert - should not raise an exception
        self.tracker.cancel_inbound_request(nonexistent_peer, request_id)

        # Verify no side effects
        assert nonexistent_peer not in self.tracker.get_peer_ids()

    async def test_cancel_inbound_request_request_not_found(self):
        # Arrange
        peer_id = "test-peer-456"
        nonexistent_request = "ghost-request"

        # Track a different request to ensure peer exists
        real_request = PingRequest()

        async def dummy_handler():
            await asyncio.sleep(1)

        real_task = asyncio.create_task(dummy_handler())

        self.tracker.track_inbound_request(peer_id, "real-req", real_request, real_task)

        # Act & Assert - should not raise an exception
        self.tracker.cancel_inbound_request(peer_id, nonexistent_request)

        # Verify no side effects on existing requests
        assert self.tracker.get_inbound_request(peer_id, "real-req") is not None
        assert not real_task.done()

        # Cleanup
        real_task.cancel()

    async def test_cancel_inbound_request_already_done_task(self):
        # Arrange
        peer_id = "test-peer-789"
        request_id = "req-101"
        request = PingRequest()

        # Create a task that completes immediately
        async def quick_handler():
            return  # Completes immediately

        task = asyncio.create_task(quick_handler())
        await task  # Wait for it to complete

        self.tracker.track_inbound_request(peer_id, request_id, request, task)
        assert task.done()

        # Act & Assert - should not raise an exception
        self.tracker.cancel_inbound_request(peer_id, request_id)

        # Verify request is still removed from tracking
        assert self.tracker.get_inbound_request(peer_id, request_id) is None

    async def test_cleanup_peer_requests_orchestration(self):
        # Arrange - set up multiple requests for one peer
        peer_id = "test-peer-123"

        # Track outbound requests
        outbound_req1 = PingRequest()
        outbound_future1 = asyncio.Future[Result | Error]()
        self.tracker.track_outbound_request(
            peer_id, "out-1", outbound_req1, outbound_future1
        )

        outbound_req2 = PingRequest()
        outbound_future2 = asyncio.Future[Result | Error]()
        self.tracker.track_outbound_request(
            peer_id, "out-2", outbound_req2, outbound_future2
        )

        # Track inbound requests
        async def dummy_handler():
            await asyncio.sleep(1.0)

        inbound_task1 = asyncio.create_task(dummy_handler())
        inbound_task2 = asyncio.create_task(dummy_handler())

        self.tracker.track_inbound_request(
            peer_id, "in-1", PingRequest(), inbound_task1
        )
        self.tracker.track_inbound_request(
            peer_id, "in-2", PingRequest(), inbound_task2
        )

        # Verify everything is tracked
        assert len(self.tracker.get_peer_outbound_request_ids(peer_id)) == 2
        assert len(self.tracker.get_peer_inbound_request_ids(peer_id)) == 2

        # Act
        self.tracker.cleanup_peer(peer_id)

        # Assert - all outbound futures resolved with errors
        assert outbound_future1.done()
        assert outbound_future2.done()
        assert isinstance(outbound_future1.result(), Error)
        assert isinstance(outbound_future2.result(), Error)
        assert (
            "Resolved internally by request tracker"
            in outbound_future1.result().message
        )

        # Assert - all inbound tasks cancelled
        for task in [inbound_task1, inbound_task2]:
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Assert - peer has no tracked requests
        assert len(self.tracker.get_peer_outbound_request_ids(peer_id)) == 0
        assert len(self.tracker.get_peer_inbound_request_ids(peer_id)) == 0

        # Assert - peer is no longer tracked
        assert peer_id not in self.tracker.get_peer_ids()

    async def test_cleanup_all_requests_orchestration(self):
        # Arrange - set up requests for multiple peers
        peer1_id = "peer-1"
        peer2_id = "peer-2"

        # Peer 1 requests
        future1 = asyncio.Future[Result | Error]()
        self.tracker.track_outbound_request(peer1_id, "req-1", PingRequest(), future1)

        async def handler1():
            await asyncio.sleep(1.0)

        task1 = asyncio.create_task(handler1())
        self.tracker.track_inbound_request(peer1_id, "req-2", PingRequest(), task1)

        # Peer 2 requests
        future2 = asyncio.Future[Result | Error]()
        self.tracker.track_outbound_request(peer2_id, "req-3", PingRequest(), future2)

        async def handler2():
            await asyncio.sleep(1.0)

        task2 = asyncio.create_task(handler2())
        self.tracker.track_inbound_request(peer2_id, "req-4", PingRequest(), task2)

        # Verify initial state
        assert len(self.tracker.get_peer_ids()) == 2

        # Act
        self.tracker.cleanup_all_peers()

        # Assert - all futures resolved with errors
        assert future1.done() and isinstance(future1.result(), Error)
        assert future2.done() and isinstance(future2.result(), Error)

        # Assert - all tasks cancelled
        for task in [task1, task2]:
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Assert - no peers tracked anymore
        assert len(self.tracker.get_peer_ids()) == 0

    def test_cleanup_peer_requests_nonexistent_peer(self):
        # Arrange
        nonexistent_peer = "ghost-peer"

        # Act & Assert - should not raise an exception
        self.tracker.cleanup_peer(nonexistent_peer)

        # Verify no side effects
        assert len(self.tracker.get_peer_ids()) == 0

    def test_cleanup_all_requests_empty_tracker(self):
        # Arrange - tracker is already empty
        assert len(self.tracker.get_peer_ids()) == 0

        # Act & Assert - should not raise an exception
        self.tracker.cleanup_all_peers()

        # Verify still empty
        assert len(self.tracker.get_peer_ids()) == 0
