import asyncio

import pytest

from conduit.protocol.base import Error
from conduit.protocol.common import PingRequest


class TestClientMessageCoordinatorLifecycle:
    async def test_start_is_idempotent(self, coordinator):
        # Arrange
        assert not coordinator.running

        # Act - start multiple times
        await coordinator.start()
        assert coordinator.running

        await coordinator.start()  # Should be safe to call again

        # Assert - still running after multiple starts
        assert coordinator.running

        # Cleanup
        await coordinator.stop()
        assert not coordinator.running

    async def test_start_requires_open_transport(self, coordinator, mock_transport):
        # Arrange
        await mock_transport.close()
        assert not mock_transport.is_open

        # Act & Assert
        with pytest.raises(ConnectionError, match="transport is closed"):
            await coordinator.start()

    async def test_stop_is_idempotent(self, coordinator):
        # Arrange
        await coordinator.start()
        assert coordinator.running

        # Act - stop multiple times
        await coordinator.stop()
        assert not coordinator.running

        await coordinator.stop()  # Should be safe to call again
        assert not coordinator.running

    async def test_stop_without_start_is_safe(self, coordinator):
        # Arrange
        assert not coordinator.running

        # Act & Assert - should not raise
        await coordinator.stop()
        assert not coordinator.running

    async def test_running_property_reflects_state(self, coordinator):
        # Arrange
        assert not coordinator.running

        # Act & Assert
        await coordinator.start()
        assert coordinator.running

        await coordinator.stop()
        assert not coordinator.running

    async def test_multiple_start_stop_cycles(self, coordinator):
        # Arrange & Act - multiple cycles
        for _ in range(3):
            assert not coordinator.running
            await coordinator.start()
            assert coordinator.running
            await coordinator.stop()
            assert not coordinator.running

    async def test_coordinator_can_be_restarted_after_stop(
        self, coordinator, mock_transport, yield_loop
    ):
        """Coordinator can be stopped and restarted and still process messages."""
        # Arrange
        handled_messages = []

        async def tracking_handler(payload):
            handled_messages.append(payload)

        coordinator._handle_server_message = tracking_handler

        # Act - Start, process message, stop
        await coordinator.start()
        mock_transport.add_server_message(
            {"jsonrpc": "2.0", "method": "test/before-stop"}
        )
        await yield_loop()
        await coordinator.stop()

        # Act - Restart and process another message
        await coordinator.start()
        mock_transport.add_server_message(
            {"jsonrpc": "2.0", "method": "test/after-restart"}
        )
        await yield_loop()

        # Assert - Both phases worked
        assert len(handled_messages) == 2
        assert handled_messages[0]["method"] == "test/before-stop"
        assert handled_messages[1]["method"] == "test/after-restart"

        # Cleanup
        await coordinator.stop()

    async def test_stop_cancels_all_server_requests(
        self, coordinator, server_manager, yield_loop
    ):
        # Arrange
        await coordinator.start()

        # Create mock in-flight tasks for requests FROM server
        task1 = asyncio.create_task(asyncio.sleep(10))
        task2 = asyncio.create_task(asyncio.sleep(10))

        # Create mock pending request futures for requests TO server
        future1 = asyncio.Future()
        future2 = asyncio.Future()

        # Add requests to server context
        context = server_manager.get_server_context()
        context.requests_from_server["req1"] = task1
        context.requests_from_server["req2"] = task2

        ping_request = PingRequest()
        context.requests_to_server["ping1"] = (ping_request, future1)
        context.requests_to_server["ping2"] = (ping_request, future2)

        # Act
        await coordinator.stop()
        await yield_loop()

        # Assert - both types of requests are cancelled/resolved
        for task in [task1, task2]:
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert task1.cancelled()
        assert task2.cancelled()
        assert future1.done()
        assert future2.done()

        # Verify futures were resolved with errors
        result1 = future1.result()
        result2 = future2.result()
        assert isinstance(result1, Error)
        assert isinstance(result2, Error)
