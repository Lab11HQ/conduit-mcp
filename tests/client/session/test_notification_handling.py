from unittest.mock import AsyncMock, Mock

from conduit.client.session import ClientConfig, ClientSession
from conduit.protocol.base import METHOD_NOT_FOUND, Error, Request
from conduit.protocol.common import (
    CancelledNotification,
    ProgressNotification,
)
from conduit.protocol.content import TextResourceContents
from conduit.protocol.initialization import ClientCapabilities, Implementation
from conduit.protocol.logging import LoggingMessageNotification
from conduit.protocol.prompts import (
    ListPromptsRequest,
    ListPromptsResult,
    Prompt,
    PromptListChangedNotification,
)
from conduit.protocol.resources import (
    ListResourcesRequest,
    ListResourcesResult,
    ListResourceTemplatesRequest,
    ListResourceTemplatesResult,
    ReadResourceRequest,
    ReadResourceResult,
    Resource,
    ResourceListChangedNotification,
    ResourceTemplate,
    ResourceUpdatedNotification,
)
from conduit.protocol.tools import (
    JSONSchema,
    ListToolsRequest,
    ListToolsResult,
    Tool,
    ToolListChangedNotification,
)


class TestNotificationHandling:
    def setup_method(self):
        self.transport = AsyncMock()
        self.config = ClientConfig(
            client_info=Implementation(name="test-client", version="1.0.0"),
            capabilities=ClientCapabilities(),
        )
        self.session = ClientSession(self.transport, self.config)
        self.session.server_manager.register_server("server_id")


class TestCancellationNotificationHandling(TestNotificationHandling):
    async def test_cancels_in_flight_request_and_calls_callback(self):
        # Arrange
        request_id = "test-request-123"
        mock_task = Mock()
        mock_task.cancel = Mock(return_value=True)

        mock_request = Mock()
        self.session.server_manager.track_request_from_server(
            "server_id", request_id, mock_request, mock_task
        )

        cancellation = CancelledNotification(
            request_id=request_id, reason="Taking too long"
        )

        # Mock the callback manager
        self.session.callbacks.call_cancelled = AsyncMock()

        # Act
        await self.session._handle_cancelled("server_id", cancellation)

        # Assert
        mock_task.cancel.assert_called_once()
        self.session.callbacks.call_cancelled.assert_awaited_once_with(
            "server_id", cancellation
        )

    async def test_does_not_call_callback_when_request_id_not_found(self):
        # Arrange
        cancellation = CancelledNotification(
            request_id="unknown-request", reason="Taking too long"
        )

        # Mock the callback manager
        self.session.callbacks.call_cancelled = AsyncMock()

        # Act
        await self.session._handle_cancelled("server_id", cancellation)

        # Assert
        # No callback should be called since no request was actually cancelled
        self.session.callbacks.call_cancelled.assert_not_awaited()


class TestProgressNotificationHandling(TestNotificationHandling):
    async def test_delegates_progress_notification_to_callback_manager(self):
        # Arrange
        progress_notification = ProgressNotification(
            progress_token="test-123", progress=50.0, total=100.0
        )

        self.session.callbacks.call_progress = AsyncMock()

        # Act
        await self.session._handle_progress("server_id", progress_notification)

        # Assert
        self.session.callbacks.call_progress.assert_awaited_once_with(
            "server_id", progress_notification
        )


class TestLoggingNotificationHandling(TestNotificationHandling):
    async def test_delegates_logging_notification_to_callback_manager(self):
        # Arrange
        logging_notification = LoggingMessageNotification(
            level="info", data="Test log message"
        )

        # Mock the callback manager method
        self.session.callbacks.call_logging_message = AsyncMock()

        # Act
        await self.session._handle_logging_message("server_id", logging_notification)

        # Assert
        self.session.callbacks.call_logging_message.assert_awaited_once_with(
            "server_id", logging_notification
        )


class TestPromptsListChangedHandling(TestNotificationHandling):
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
        await self.session._handle_prompts_list_changed("server_id", notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        sent_request = self.session.send_request.call_args[0][1]
        assert isinstance(sent_request, ListPromptsRequest)

        assert self.session.server_manager.get_server("server_id").prompts == prompts

        self.session.callbacks.call_prompts_changed.assert_awaited_once_with(
            "server_id", prompts
        )

    async def test_ignores_server_error_response_silently(self):
        # Arrange
        notification = PromptListChangedNotification()
        error_result = Error(code=METHOD_NOT_FOUND, message="Prompts not supported")
        self.session.send_request = AsyncMock(return_value=error_result)
        self.session.callbacks.call_prompts_changed = AsyncMock()
        initial_prompts = self.session.server_manager.get_server("server_id").prompts

        # Act
        await self.session._handle_prompts_list_changed("server_id", notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        assert (
            self.session.server_manager.get_server("server_id").prompts
            == initial_prompts
        )
        self.session.callbacks.call_prompts_changed.assert_not_awaited()

    async def test_ignores_request_failure_silently(self):
        # Arrange
        notification = PromptListChangedNotification()
        self.session.send_request = AsyncMock(
            side_effect=ConnectionError("Network failure")
        )
        self.session.callbacks.call_prompts_changed = AsyncMock()
        initial_prompts = self.session.server_manager.get_server("server_id").prompts

        # Act
        await self.session._handle_prompts_list_changed("server_id", notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        assert (
            self.session.server_manager.get_server("server_id").prompts
            == initial_prompts
        )
        self.session.callbacks.call_prompts_changed.assert_not_awaited()


class TestToolsListChangedHandling(TestNotificationHandling):
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
        await self.session._handle_tools_list_changed("server_id", notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        sent_request = self.session.send_request.call_args[0][1]
        assert isinstance(sent_request, ListToolsRequest)

        assert self.session.server_manager.get_server("server_id").tools == tools
        self.session.callbacks.call_tools_changed.assert_awaited_once_with(
            "server_id", tools
        )

    async def test_ignores_server_error_response_silently(self):
        # Arrange
        notification = ToolListChangedNotification()
        error_result = Error(code=METHOD_NOT_FOUND, message="Tools not supported")

        self.session.send_request = AsyncMock(return_value=error_result)
        self.session.callbacks.call_tools_changed = AsyncMock()
        initial_tools = self.session.server_manager.get_server("server_id").tools

        # Act
        await self.session._handle_tools_list_changed("server_id", notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        assert (
            self.session.server_manager.get_server("server_id").tools == initial_tools
        )
        self.session.callbacks.call_tools_changed.assert_not_awaited()

    async def test_ignores_request_failure_silently(self):
        # Arrange
        notification = ToolListChangedNotification()

        self.session.send_request = AsyncMock(
            side_effect=ConnectionError("Network failure")
        )
        self.session.callbacks.call_tools_changed = AsyncMock()
        initial_tools = self.session.server_manager.get_server("server_id").tools

        # Act
        await self.session._handle_tools_list_changed("server_id", notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        assert (
            self.session.server_manager.get_server("server_id").tools == initial_tools
        )
        self.session.callbacks.call_tools_changed.assert_not_awaited()


class TestResourcesUpdatedHandling(TestNotificationHandling):
    async def test_reads_specific_resource_and_calls_callback_on_successful_read(self):
        # Arrange
        resource_uri = "file:///test/resource.txt"
        notification = ResourceUpdatedNotification(uri=resource_uri)

        read_result = ReadResourceResult(
            contents=[TextResourceContents(uri=resource_uri, text="Updated content")]
        )

        self.session.send_request = AsyncMock(return_value=read_result)
        self.session.callbacks.call_resource_updated = AsyncMock()

        # Act
        await self.session._handle_resources_updated("server_id", notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        sent_request = self.session.send_request.call_args[0][1]
        assert isinstance(sent_request, ReadResourceRequest)
        assert sent_request.uri == resource_uri

        self.session.callbacks.call_resource_updated.assert_awaited_once_with(
            "server_id", resource_uri, read_result
        )

    async def test_ignores_server_error_response_silently(self):
        # Arrange
        resource_uri = "file:///test/resource.txt"
        notification = ResourceUpdatedNotification(uri=resource_uri)
        error_result = Error(code=METHOD_NOT_FOUND, message="Resource not found")

        self.session.send_request = AsyncMock(return_value=error_result)
        self.session.callbacks.call_resource_updated = AsyncMock()

        # Act
        await self.session._handle_resources_updated("server_id", notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        self.session.callbacks.call_resource_updated.assert_not_called()

    async def test_ignores_request_failure_silently(self):
        # Arrange
        resource_uri = "file:///test/resource.txt"
        notification = ResourceUpdatedNotification(uri=resource_uri)

        self.session.send_request = AsyncMock(
            side_effect=ConnectionError("Network failure")
        )
        self.session.callbacks.call_resource_updated = AsyncMock()

        # Act
        await self.session._handle_resources_updated("server_id", notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        self.session.callbacks.call_resource_updated.assert_not_called()


class TestResourcesListChangedHandling(TestNotificationHandling):
    async def test_updates_state_and_calls_callbacks_on_successful_refresh(self):
        # Arrange
        notification = ResourceListChangedNotification()

        resources = [
            Resource(uri="file:///test1.txt", name="Test Resource 1"),
            Resource(uri="file:///test2.txt", name="Test Resource 2"),
        ]
        templates = [
            ResourceTemplate(uri_template="file:///{name}.txt", name="File Template")
        ]

        resources_result = ListResourcesResult(resources=resources)
        templates_result = ListResourceTemplatesResult(resource_templates=templates)

        def mock_send_request(server_id: str, request: Request):
            if isinstance(request, ListResourcesRequest):
                return resources_result
            elif isinstance(request, ListResourceTemplatesRequest):
                return templates_result

        self.session.send_request = AsyncMock(side_effect=mock_send_request)
        self.session.callbacks.call_resources_changed = AsyncMock()

        # Act
        await self.session._handle_resources_list_changed("server_id", notification)

        # Assert
        assert self.session.send_request.await_count == 2

        assert (
            self.session.server_manager.get_server("server_id").resources == resources
        )
        assert (
            self.session.server_manager.get_server("server_id").resource_templates
            == templates
        )

        self.session.callbacks.call_resources_changed.assert_awaited_once_with(
            "server_id", resources, templates
        )

    async def test_handles_partial_failure_gracefully(self):
        # Arrange
        notification = ResourceListChangedNotification()

        resources = [Resource(uri="file:///test.txt", name="Test Resource")]
        resources_result = ListResourcesResult(resources=resources)
        templates_error = Error(code=METHOD_NOT_FOUND, message="No templates here!")

        def mock_send_request(server_id: str, request: Request):
            if isinstance(request, ListResourcesRequest):
                return resources_result
            elif isinstance(request, ListResourceTemplatesRequest):
                return templates_error

        self.session.send_request = AsyncMock(side_effect=mock_send_request)
        self.session.callbacks.call_resources_changed = AsyncMock()

        # Act
        await self.session._handle_resources_list_changed("server_id", notification)

        # Assert
        assert self.session.send_request.await_count == 2

        # Resources should be updated, templates should remain unchanged
        assert (
            self.session.server_manager.get_server("server_id").resources == resources
        )
        assert (
            self.session.server_manager.get_server("server_id").resource_templates
            is None
        )  # No update on failure

        # Callback should be called with resources and empty templates list
        self.session.callbacks.call_resources_changed.assert_awaited_once_with(
            "server_id", resources, []
        )
