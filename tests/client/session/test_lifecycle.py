import asyncio
from unittest.mock import AsyncMock

from .conftest import BaseSessionTest


class TestClientSessionLifecycle(BaseSessionTest):
    async def test_start_creates_message_loop_task(self):
        # Arrange: verify initial state
        assert self.session._task is None
        assert self.session._running is False

        # Act
        await self.session._start()

        # Assert: task created and running
        assert self.session._task is not None
        assert isinstance(self.session._task, asyncio.Task)
        assert not self.session._task.done()
        assert self.session._running is True

        # Cleanup
        await self.session.stop()

    async def test_start_is_idempotent_does_not_create_multiple_tasks(self):
        # Act: start multiple times
        await self.session._start()
        first_task = self.session._task

        await self.session._start()
        await self.session._start()

        # Assert: same task instance, still running
        assert self.session._task is first_task
        assert self.session._running is True
        assert not first_task.done()

        # Cleanup
        await self.session.stop()

    async def test_stop_resets_session_to_clean_uninitialized_state(self):
        # Arrange: start session and initialize it
        await self.session._start()
        self.session._initialized = True

        # Verify we have initialized state
        assert self.session._running is True
        assert self.session._task is not None

        # Act
        await self.session.stop()

        # Assert: complete state reset
        assert self.session._running is False
        assert self.session._task is None
        assert self.session._initialized is False

    async def test_stop_is_idempotent_multiple_calls_are_safe(self):
        # Arrange: start the session
        await self.session._start()
        self.session._initialized = True
        assert self.session._running is True
        assert self.session._task is not None

        # Act: stop multiple times
        await self.session.stop()
        await self.session.stop()
        await self.session.stop()

        # Assert: clean state after all calls
        assert self.session._running is False
        assert self.session._task is None
        assert self.session._initialized is False
        assert self.session._initializing is None

    async def test_stop_calls_transport_close(self):
        # Arrange: start the session
        await self.session._start()

        self.transport.close = AsyncMock()
        assert not self.transport.closed

        # Act
        await self.session.stop()

        # Assert: transport was closed
        self.transport.close.assert_awaited_once()

    async def test_stop_cancels_and_awaits_background_task(self):
        # Arrange: start the session and capture the task
        await self.session._start()
        background_task = self.session._task
        assert background_task is not None
        assert not background_task.done()

        # Act
        await self.session.stop()

        # Assert: task was cancelled and cleaned up
        assert background_task.done()
        assert background_task.cancelled()
        assert self.session._task is None
