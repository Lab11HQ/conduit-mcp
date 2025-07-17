from unittest.mock import AsyncMock

from conduit.protocol.common import CancelledNotification, ProgressNotification
from conduit.protocol.initialization import InitializedNotification
from conduit.protocol.roots import Root
from conduit.server.callbacks import CallbackManager


class TestInitializationCallback:
    def setup_method(self):
        # Arrange - consistent client ID for all tests
        self.client_id = "test-client-123"

    async def test_initialized_callback_receives_client_id_and_initialization_details(
        self,
    ):
        # Arrange - user registers an initialization callback
        manager = CallbackManager()
        callback = AsyncMock()
        manager.on_initialized(callback)

        initialized_notification = InitializedNotification()

        # Act - server receives initialization completion from a specific client
        await manager.call_initialized(self.client_id, initialized_notification)

        # Assert - callback receives both client ID and initialization details
        callback.assert_awaited_once_with(self.client_id, initialized_notification)

    async def test_initialized_callback_does_nothing_when_no_callback_registered(self):
        # Arrange - manager with no callbacks registered
        manager = CallbackManager()
        initialized_notification = InitializedNotification()

        # Act - server receives initialization but no callback is registered
        await manager.call_initialized(self.client_id, initialized_notification)

        # Assert - completes without raising (no exception bubbles up)
        # Test passes if we reach this point without exception

    async def test_initialized_callback_does_not_raise_user_callback_exceptions(self):
        # Arrange - user registers a buggy callback that throws
        manager = CallbackManager()
        callback = AsyncMock(side_effect=RuntimeError("User callback failed"))
        manager.on_initialized(callback)

        initialized_notification = InitializedNotification()

        # Act - server receives initialization, user callback throws
        await manager.call_initialized(self.client_id, initialized_notification)

        # Assert - callback was called but exception didn't bubble up
        callback.assert_awaited_once_with(self.client_id, initialized_notification)
        # Test passes if we reach this point without the RuntimeError bubbling up


class TestProgressCallback:
    def setup_method(self):
        # Arrange - consistent client ID for all tests
        self.client_id = "test-client-123"

    async def test_progress_callback_receives_client_id_and_progress_details(self):
        # Arrange - user registers a progress callback
        manager = CallbackManager()
        callback = AsyncMock()
        manager.on_progress(callback)

        progress_notification = ProgressNotification(
            progress_token="file-upload-456",
            progress=75,
            total=100,
            message="Uploading file...",
        )

        # Act - server receives progress from a specific client
        await manager.call_progress(self.client_id, progress_notification)

        # Assert - callback receives both client ID and progress details
        callback.assert_awaited_once_with(self.client_id, progress_notification)

    async def test_progress_callback_does_nothing_when_no_callback_registered(self):
        # Arrange - manager with no callbacks registered
        manager = CallbackManager()
        progress_notification = ProgressNotification(
            progress_token="file-upload-456", progress=75
        )

        # Act - server receives progress but no callback is registered
        await manager.call_progress(self.client_id, progress_notification)

        # Assert - completes without raising (no exception bubbles up)
        # Test passes if we reach this point without exception

    async def test_progress_callback_does_not_raise_user_callback_exceptions(self):
        # Arrange - user registers a buggy callback that throws
        manager = CallbackManager()
        callback = AsyncMock(side_effect=RuntimeError("User callback failed"))
        manager.on_progress(callback)

        progress_notification = ProgressNotification(
            progress_token="file-upload-456", progress=75
        )

        # Act - server receives progress, user callback throws
        await manager.call_progress(self.client_id, progress_notification)

        # Assert - callback was called but exception didn't bubble up
        callback.assert_awaited_once_with(self.client_id, progress_notification)
        # Test passes if we reach this point without the RuntimeError bubbling up


class TestCancellationCallback:
    def setup_method(self):
        # Arrange - consistent client ID for all tests
        self.client_id = "test-client-123"

    async def test_cancelled_callback_receives_client_id_and_cancellation_details(self):
        # Arrange - user registers a cancellation callback
        manager = CallbackManager()
        callback = AsyncMock()
        manager.on_cancelled(callback)

        cancelled_notification = CancelledNotification(
            request_id="req-456", reason="timeout"
        )

        # Act - server receives cancellation from a specific client
        await manager.call_cancelled(self.client_id, cancelled_notification)

        # Assert - callback receives both client ID and cancellation details
        callback.assert_awaited_once_with(self.client_id, cancelled_notification)

    async def test_cancelled_callback_does_nothing_when_no_callback_registered(self):
        # Arrange - manager with no callbacks registered
        manager = CallbackManager()
        cancelled_notification = CancelledNotification(
            request_id="req-456", reason="timeout"
        )

        # Act - server receives cancellation but no callback is registered
        await manager.call_cancelled(self.client_id, cancelled_notification)

        # Assert - completes without raising (no exception bubbles up)
        # Test passes if we reach this point without exception

    async def test_cancelled_callback_does_not_raise_user_callback_exceptions(self):
        # Arrange - user registers a buggy callback that throws
        manager = CallbackManager()
        callback = AsyncMock(side_effect=RuntimeError("User callback failed"))
        manager.on_cancelled(callback)

        cancelled_notification = CancelledNotification(
            request_id="req-456", reason="timeout"
        )

        # Act - server receives cancellation, user callback throws
        await manager.call_cancelled(self.client_id, cancelled_notification)

        # Assert - callback was called but exception didn't bubble up
        callback.assert_awaited_once_with(self.client_id, cancelled_notification)
        # Test passes if we reach this point without the RuntimeError bubbling up


class TestRootsChangedCallback:
    def setup_method(self):
        # Arrange - consistent client ID for all tests
        self.client_id = "test-client-123"

    async def test_roots_changed_callback_receives_client_id_and_roots_list(self):
        # Arrange - user registers a roots changed callback
        manager = CallbackManager()
        callback = AsyncMock()
        manager.on_roots_changed(callback)

        roots = [Root(uri="file:///project/src"), Root(uri="file:///project/docs")]

        # Act - server receives roots change from a specific client
        await manager.call_roots_changed(self.client_id, roots)

        # Assert - callback receives both client ID and roots list
        callback.assert_awaited_once_with(self.client_id, roots)

    async def test_roots_changed_callback_does_nothing_when_no_callback_registered(
        self,
    ):
        # Arrange - manager with no callbacks registered
        manager = CallbackManager()
        roots = [Root(uri="file:///project/src")]

        # Act - server receives roots change but no callback is registered
        await manager.call_roots_changed(self.client_id, roots)

        # Assert - completes without raising (no exception bubbles up)
        # Test passes if we reach this point without exception

    async def test_roots_changed_callback_does_not_raise_user_callback_exceptions(self):
        # Arrange - user registers a buggy callback that throws
        manager = CallbackManager()
        callback = AsyncMock(side_effect=RuntimeError("User callback failed"))
        manager.on_roots_changed(callback)

        roots = [Root(uri="file:///project/src")]

        # Act - server receives roots change, user callback throws
        await manager.call_roots_changed(self.client_id, roots)

        # Assert - callback was called but exception didn't bubble up
        callback.assert_awaited_once_with(self.client_id, roots)
        # Test passes if we reach this point without the RuntimeError bubbling up
