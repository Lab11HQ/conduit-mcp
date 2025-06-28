import asyncio

import pytest

from .conftest import BaseSessionTest


class TestBaseSessionLifecycle(BaseSessionTest):
    async def test_start_creates_message_loop_task(self):
        # Arrange
        assert self.session._message_loop_task is None
        assert self.session._running is False

        # Act
        await self.session.start()

        # Assert
        assert self.session._message_loop_task is not None
        assert isinstance(self.session._message_loop_task, asyncio.Task)
        assert not self.session._message_loop_task.done()
        assert self.session._running is True

    async def test_start_is_idempotent(self):
        # Arrange
        await self.session.start()
        first_task = self.session._message_loop_task

        # Act
        await self.session.start()
        await self.session.start()

        # Assert
        assert self.session._message_loop_task is first_task
        assert self.session._running is True
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
        assert self.session._running is True
        assert self.session._message_loop_task is not None

        # Act
        await self.session.stop()

        # Assert
        assert self.session._running is False
        assert self.session._message_loop_task is None

    async def test_stop_resolves_pending_requests(self):
        # Arrange
        await self.session.start()

        # Start a request that won't get a response
        from conduit.protocol.common import PingRequest

        request_task = asyncio.create_task(
            self.session.send_request(PingRequest(), timeout=10.0)
        )

        # Wait for the ping request to be sent
        await self.wait_for_sent_message("ping")
        assert len(self.session._pending_requests) == 1

        # Act
        await self.session.stop()

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
        assert self.session._running is False
        assert self.session._message_loop_task is None

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
