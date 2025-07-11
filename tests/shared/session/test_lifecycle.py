import asyncio

import pytest

from conduit.protocol.common import PingRequest

from .conftest import BaseSessionTest


class TestBaseSessionLifecycle(BaseSessionTest):
    _default_yield_time = 0.01

    async def test_start_creates_message_loop_task(self):
        # Arrange
        assert self.session._message_loop_task is None
        assert self.session.running is False

        # Act
        await self.session.start()

        # Assert
        assert self.session._message_loop_task is not None
        assert isinstance(self.session._message_loop_task, asyncio.Task)
        assert not self.session._message_loop_task.done()
        assert self.session.running is True

    async def test_start_is_idempotent(self):
        # Arrange
        await self.session.start()
        first_task = self.session._message_loop_task

        # Act
        await self.session.start()
        await self.session.start()

        # Assert
        assert self.session._message_loop_task is first_task
        assert self.session.running is True
        assert not first_task.done()

    async def test_start_raises_connection_error_if_transport_closed(self):
        # Arrange
        await self.transport.close()
        assert not self.transport.is_open

        # Act & Assert
        with pytest.raises(
            ConnectionError, match="Cannot start session: transport is closed"
        ):
            await self.session.start()

    async def test_stop_stops_message_loop(self):
        # Arrange
        await self.session.start()
        assert self.session.running is True
        assert self.session._message_loop_task is not None

        # Act
        await self.session.stop()

        # Assert
        assert self.session.running is False
        assert self.session._message_loop_task is None

    async def test_stop_triggerr_pending_request_cleanup(self):
        # Arrange
        await self.session.start()

        request_task = asyncio.create_task(
            self.session.send_request(PingRequest(), timeout=10.0)
        )

        # Wait for the ping request to be sent
        await self.wait_for_sent_message("ping")
        assert len(self.session._pending_requests) == 1

        # Act
        await self.session.stop()
        await self.yield_to_event_loop()

        # Assert
        assert len(self.session._pending_requests) == 0
        assert request_task.done()
        assert request_task.result() is not None

    async def test_stop_is_idempotent(self):
        # Arrange
        await self.session.start()

        # Act
        await self.session.stop()
        await self.session.stop()

        # Assert
        assert not self.session.running

    async def test_stop_cancels_in_flight_request_handlers(self):
        # Arrange
        await self.session.start()
        slow_task = asyncio.create_task(asyncio.sleep(10))
        self.session._in_flight_requests["test-request"] = slow_task

        # Act
        await self.session.stop()

        # Assert - wait for the task to be cancelled
        try:
            await asyncio.wait_for(slow_task, timeout=0.1)
        except asyncio.CancelledError:
            pass  # Expected!
        except asyncio.TimeoutError:
            pytest.fail("Task should have been cancelled")

        assert slow_task.cancelled()
        assert len(self.session._in_flight_requests) == 0

    async def test_session_can_be_restarted_after_stop(self):
        """Session can be stopped and restarted without recreating transport."""
        # Arrange & Act: Start, process a message, then stop
        handled_messages = []

        async def tracking_handler(payload):
            handled_messages.append(payload)

        self.session._handle_message = tracking_handler

        await self.session.start()

        self.transport.receive_message({"jsonrpc": "2.0", "method": "test/before-stop"})
        await self.yield_to_event_loop()

        await self.session.stop()
        assert not self.session.running

        # Act: Restart and process another message
        await self.session.start()
        assert self.session.running

        self.transport.receive_message(
            {"jsonrpc": "2.0", "method": "test/after-restart"}
        )
        await self.yield_to_event_loop()

        # Assert: Both phases worked
        assert len(handled_messages) == 2
        assert handled_messages[0]["method"] == "test/before-stop"
        assert handled_messages[1]["method"] == "test/after-restart"
