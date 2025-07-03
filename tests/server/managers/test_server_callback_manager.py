from unittest.mock import AsyncMock

import pytest

from conduit.protocol.common import CancelledNotification, ProgressNotification
from conduit.protocol.roots import Root
from conduit.server.managers.callbacks import CallbackManager


class TestServerCallbackManager:
    @pytest.mark.parametrize(
        "callback_type,register_method,notify_method,test_data",
        [
            (
                "progress",
                "on_progress",
                "call_progress",
                ProgressNotification(progress_token="123", progress=75),
            ),
            (
                "roots_changed",
                "on_roots_changed",
                "call_roots_changed",
                [Root(uri="file:///test")],
            ),
            (
                "initialized",
                "on_initialized",
                "call_initialized",
                None,
            ),  # No data passed
            (
                "cancelled",
                "on_cancelled",
                "call_cancelled",
                CancelledNotification(request_id="456", reason="timeout"),
            ),
        ],
    )
    async def test_notify_calls_callback_if_registered(
        self, callback_type, register_method, notify_method, test_data
    ):
        # Arrange
        manager = CallbackManager()
        callback = AsyncMock()
        getattr(manager, register_method)(callback)

        # Act
        if test_data is None:
            await getattr(manager, notify_method)()
        else:
            await getattr(manager, notify_method)(test_data)

        # Assert
        if test_data is None:
            callback.assert_awaited_once_with()
        else:
            callback.assert_awaited_once_with(test_data)

    @pytest.mark.parametrize(
        "callback_type,notify_method,test_data",
        [
            (
                "progress",
                "call_progress",
                ProgressNotification(progress_token="123", progress=75),
            ),
            ("roots_changed", "call_roots_changed", [Root(uri="file:///test")]),
            ("initialized", "call_initialized", None),
            (
                "cancelled",
                "call_cancelled",
                CancelledNotification(request_id="456", reason="timeout"),
            ),
        ],
    )
    async def test_notify_does_nothing_if_no_callback_registered(
        self, callback_type, notify_method, test_data
    ):
        # Arrange
        manager = CallbackManager()

        # Act & Assert - should complete without raising
        if test_data is None:
            await getattr(manager, notify_method)()
        else:
            await getattr(manager, notify_method)(test_data)
