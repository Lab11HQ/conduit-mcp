from unittest.mock import AsyncMock, Mock

import pytest

from conduit.protocol.base import METHOD_NOT_FOUND, Error
from conduit.protocol.common import (
    CancelledNotification,
    ProgressNotification,
)
from conduit.protocol.logging import LoggingMessageNotification
from conduit.protocol.prompts import (
    ListPromptsRequest,
    ListPromptsResult,
    Prompt,
    PromptListChangedNotification,
)
from conduit.protocol.tools import (
    JSONSchema,
    ListToolsRequest,
    ListToolsResult,
    Tool,
    ToolListChangedNotification,
)
from conduit.shared.exceptions import UnknownNotificationError
from tests.client.session.conftest import ClientSessionTest


class TestNotificationRouting(ClientSessionTest):
    async def test_raises_error_for_unknown_notification_method(self):
        # Arrange
        unknown_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/unknown",
            "params": {},
        }

        # Act & Assert
        with pytest.raises(UnknownNotificationError, match="notifications/unknown"):
            await self.session._handle_session_notification(unknown_notification)


class TestCancellationNotificationHandling(ClientSessionTest):
    async def test_cancels_in_flight_request_and_notifies_callback(self):
        # Arrange
        request_id = "test-request-123"
        mock_task = Mock()
        self.session._in_flight_requests[request_id] = mock_task

        cancellation = CancelledNotification(
            request_id=request_id, reason="user cancelled"
        )

        # Mock the callback manager
        self.session.callbacks.call_cancelled = AsyncMock()

        # Act
        await self.session._handle_cancelled(cancellation)

        # Assert
        mock_task.cancel.assert_called_once()
        self.session.callbacks.call_cancelled.assert_awaited_once_with(cancellation)

    async def test_ignores_cancellation_when_request_id_not_found(self):
        # Arrange
        cancellation = CancelledNotification(
            request_id="unknown-request", reason="user cancelled"
        )

        # Mock the callback manager
        self.session.callbacks.call_cancelled = AsyncMock()

        # Act
        await self.session._handle_cancelled(cancellation)

        # Assert
        # No task should be cancelled and no callback should be called
        self.session.callbacks.call_cancelled.assert_not_called()


class TestProgressNotificationHandling(ClientSessionTest):
    async def test_delegates_progress_notification_to_callback_manager(self):
        # Arrange
        progress_notification = ProgressNotification(
            progress_token="test-123", progress=50.0, total=100.0
        )

        self.session.callbacks.call_progress = AsyncMock()

        # Act
        await self.session._handle_progress(progress_notification)

        # Assert
        self.session.callbacks.call_progress.assert_awaited_once_with(
            progress_notification
        )


class TestLoggingNotificationHandling(ClientSessionTest):
    async def test_delegates_logging_notification_to_callback_manager(self):
        # Arrange
        logging_notification = LoggingMessageNotification(
            level="info", data="Test log message"
        )

        # Mock the callback manager method
        self.session.callbacks.call_logging_message = AsyncMock()

        # Act
        await self.session._handle_logging_message(logging_notification)

        # Assert
        self.session.callbacks.call_logging_message.assert_awaited_once_with(
            logging_notification
        )


class TestPromptsListChangedHandling(ClientSessionTest):
    async def test_updates_state_and_calls_callback_on_successful_refresh(self):
        # Arrange
        notification = PromptListChangedNotification()
        prompts = [
            Prompt(name="test-prompt", description="A test prompt"),
            Prompt(name="another-prompt", description="Another test prompt"),
        ]
        result = ListPromptsResult(prompts=prompts)
        self.session.send_request = AsyncMock(return_value=result)
        self.session.callbacks.call_prompts_changed = AsyncMock()

        # Act
        await self.session._handle_prompts_list_changed(notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        sent_request = self.session.send_request.call_args[0][0]
        assert isinstance(sent_request, ListPromptsRequest)

        assert self.session.server_state.prompts == prompts

        self.session.callbacks.call_prompts_changed.assert_awaited_once_with(prompts)

    async def test_ignores_server_error_response_silently(self):
        # Arrange
        notification = PromptListChangedNotification()
        error_result = Error(code=METHOD_NOT_FOUND, message="Prompts not supported")
        self.session.send_request = AsyncMock(return_value=error_result)
        self.session.callbacks.call_prompts_changed = AsyncMock()
        initial_prompts = self.session.server_state.prompts

        # Act
        await self.session._handle_prompts_list_changed(notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        assert self.session.server_state.prompts == initial_prompts
        self.session.callbacks.call_prompts_changed.assert_not_called()

    async def test_ignores_request_failure_silently(self):
        # Arrange
        notification = PromptListChangedNotification()
        self.session.send_request = AsyncMock(
            side_effect=ConnectionError("Network failure")
        )
        self.session.callbacks.call_prompts_changed = AsyncMock()
        initial_prompts = self.session.server_state.prompts

        # Act
        await self.session._handle_prompts_list_changed(notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        assert self.session.server_state.prompts == initial_prompts
        self.session.callbacks.call_prompts_changed.assert_not_called()


class TestToolsListChangedHandling(ClientSessionTest):
    async def test_updates_state_and_calls_callback_on_successful_refresh(self):
        # Arrange
        notification = ToolListChangedNotification()

        tools = [
            Tool(
                name="test-tool", description="A test tool", input_schema=JSONSchema()
            ),
            Tool(
                name="another-tool",
                description="Another test tool",
                input_schema=JSONSchema(),
            ),
        ]
        result = ListToolsResult(tools=tools)

        self.session.send_request = AsyncMock(return_value=result)
        self.session.callbacks.call_tools_changed = AsyncMock()

        # Act
        await self.session._handle_tools_list_changed(notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        sent_request = self.session.send_request.call_args[0][0]
        assert isinstance(sent_request, ListToolsRequest)

        assert self.session.server_state.tools == tools
        self.session.callbacks.call_tools_changed.assert_awaited_once_with(tools)

    async def test_ignores_server_error_response_silently(self):
        # Arrange
        notification = ToolListChangedNotification()
        error_result = Error(code=METHOD_NOT_FOUND, message="Tools not supported")

        self.session.send_request = AsyncMock(return_value=error_result)
        self.session.callbacks.call_tools_changed = AsyncMock()
        initial_tools = self.session.server_state.tools

        # Act
        await self.session._handle_tools_list_changed(notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        assert self.session.server_state.tools == initial_tools
        self.session.callbacks.call_tools_changed.assert_not_called()

    async def test_ignores_request_failure_silently(self):
        # Arrange
        notification = ToolListChangedNotification()

        self.session.send_request = AsyncMock(
            side_effect=ConnectionError("Network failure")
        )
        self.session.callbacks.call_tools_changed = AsyncMock()
        initial_tools = self.session.server_state.tools

        # Act
        await self.session._handle_tools_list_changed(notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        assert self.session.server_state.tools == initial_tools
        self.session.callbacks.call_tools_changed.assert_not_called()
