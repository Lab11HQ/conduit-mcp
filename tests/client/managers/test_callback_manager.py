from unittest.mock import AsyncMock

import pytest

from conduit.client.managers.callbacks import CallbackManager
from conduit.protocol.common import CancelledNotification, ProgressNotification
from conduit.protocol.logging import LoggingMessageNotification
from conduit.protocol.prompts import Prompt
from conduit.protocol.resources import Resource, ResourceTemplate
from conduit.protocol.tools import JSONSchema, Tool


class TestCallbackManager:
    @pytest.mark.parametrize(
        "callback_type,register_method,notify_method,test_data",
        [
            (
                "progress",
                "on_progress",
                "notify_progress",
                ProgressNotification(progress_token="123", progress=50),
            ),
            (
                "tools_changed",
                "on_tools_changed",
                "notify_tools_changed",
                [Tool(name="test", input_schema=JSONSchema())],
            ),
            (
                "resources_changed",
                "on_resources_changed",
                "notify_resources_changed",
                [Resource(name="test", uri="test://hi.txt")],
            ),
            (
                "resource_templates_changed",
                "on_resource_templates_changed",
                "notify_resource_templates_changed",
                [ResourceTemplate(name="test", uri_template="test://{id}")],
            ),
            (
                "prompts_changed",
                "on_prompts_changed",
                "notify_prompts_changed",
                [Prompt(name="test")],
            ),
            (
                "logging_message",
                "on_logging_message",
                "notify_logging_message",
                LoggingMessageNotification(level="info", data="test"),
            ),
            (
                "cancelled",
                "on_cancelled",
                "notify_cancelled",
                CancelledNotification(request_id="123", reason="test"),
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
        await getattr(manager, notify_method)(test_data)

        # Assert
        callback.assert_awaited_once_with(test_data)

    @pytest.mark.parametrize(
        "callback_type,notify_method,test_data",
        [
            (
                "progress",
                "notify_progress",
                ProgressNotification(progress_token="123", progress=50),
            ),
            (
                "tools_changed",
                "notify_tools_changed",
                [Tool(name="test", input_schema=JSONSchema())],
            ),
            (
                "resources_changed",
                "notify_resources_changed",
                [Resource(name="test", uri="test://hi.txt")],
            ),
            (
                "resource_templates_changed",
                "notify_resource_templates_changed",
                [ResourceTemplate(name="test", uri_template="test://{id}")],
            ),
            ("prompts_changed", "notify_prompts_changed", [Prompt(name="test")]),
            (
                "logging_message",
                "notify_logging_message",
                LoggingMessageNotification(level="info", data="test"),
            ),
            (
                "cancelled",
                "notify_cancelled",
                CancelledNotification(request_id="123", reason="test"),
            ),
        ],
    )
    async def test_notify_does_nothing_if_no_callback_registered(
        self, callback_type, notify_method, test_data
    ):
        # Arrange
        manager = CallbackManager()

        # Act & Assert (should not raise)
        await getattr(manager, notify_method)(test_data)
