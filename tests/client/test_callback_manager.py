from unittest.mock import AsyncMock

from conduit.client.callbacks import CallbackManager
from conduit.protocol.common import CancelledNotification, ProgressNotification
from conduit.protocol.content import TextResourceContents
from conduit.protocol.logging import LoggingMessageNotification
from conduit.protocol.prompts import Prompt
from conduit.protocol.resources import ReadResourceResult, Resource, ResourceTemplate
from conduit.protocol.tools import JSONSchema, Tool


class TestProgressCallback:
    async def test_progress_does_not_raise_user_callback_exceptions(self):
        # Arrange
        manager = CallbackManager()
        progress_notification = ProgressNotification(progress_token="123", progress=50)
        callback = AsyncMock(side_effect=RuntimeError("User callback failed"))
        manager.on_progress(callback)

        # Act
        await manager.call_progress("server_id", progress_notification)

        # Assert
        callback.assert_awaited_once_with(progress_notification)

    async def test_progress_does_nothing_when_no_callback_registered(self):
        # Arrange
        manager = CallbackManager()
        progress_notification = ProgressNotification(progress_token="123", progress=50)

        # Act
        await manager.call_progress("server_id", progress_notification)

        # Assert - Test passes if we reach this point without exception
        assert True


class TestToolsChangedCallback:
    async def test_tools_changed_does_not_raise_user_callback_exceptions(self):
        # Arrange
        manager = CallbackManager()
        tools = [Tool(name="test", input_schema=JSONSchema())]
        callback = AsyncMock(side_effect=RuntimeError("User callback failed"))
        manager.on_tools_changed(callback)
        await manager.call_tools_changed("server_id", tools)

        # Assert
        callback.assert_awaited_once_with(tools)

    async def test_tools_changed_does_nothing_when_no_callback_registered(self):
        # Arrange
        manager = CallbackManager()
        tools = [Tool(name="test", input_schema=JSONSchema())]

        # Act
        await manager.call_tools_changed("server_id", tools)

        # Assert - Test passes if we reach this point without exception
        assert True


class TestResourcesChangedCallback:
    async def test_resources_changed_does_not_raise_user_callback_exceptions(self):
        # Arrange
        manager = CallbackManager()
        resources = [Resource(name="test", uri="test://test")]
        templates = [ResourceTemplate(name="test", uri_template="test://test")]
        callback = AsyncMock(side_effect=RuntimeError("User callback failed"))
        manager.on_resources_changed(callback)

        # Act
        await manager.call_resources_changed("server_id", resources, templates)

        # Assert
        callback.assert_awaited_once_with(resources, templates)

    async def test_resources_changed_does_nothing_when_no_callback_registered(self):
        # Arrange
        manager = CallbackManager()
        resources = [Resource(name="test", uri="test://test")]
        templates = [ResourceTemplate(name="test", uri_template="test://test")]

        # Act
        await manager.call_resources_changed("server_id", resources, templates)

        # Assert - Test passes if we reach this point without exception
        assert True


class TestResourceUpdatedCallback:
    async def test_resource_updated_does_not_raise_user_callback_exceptions(self):
        # Arrange
        manager = CallbackManager()
        resource = Resource(name="test", uri="test://test")
        result = ReadResourceResult(
            contents=[TextResourceContents(uri=resource.uri, text="test")]
        )
        callback = AsyncMock(side_effect=RuntimeError("User callback failed"))
        manager.on_resource_updated(callback)

        # Act
        await manager.call_resource_updated("server_id", resource.uri, result)

        # Assert
        callback.assert_awaited_once_with(resource.uri, result)

    async def test_resource_updated_does_nothing_when_no_callback_registered(self):
        # Arrange
        manager = CallbackManager()
        resource = Resource(name="test", uri="test://test")
        result = ReadResourceResult(
            contents=[TextResourceContents(uri=resource.uri, text="test")]
        )

        # Act
        await manager.call_resource_updated("server_id", resource.uri, result)

        # Assert - Test passes if we reach this point without exception
        assert True


class TestPromptsChangedCallback:
    async def test_prompts_changed_does_not_raise_user_callback_exceptions(self):
        # Arrange
        manager = CallbackManager()
        prompts = [Prompt(name="test", description="test")]
        callback = AsyncMock(side_effect=RuntimeError("User callback failed"))
        manager.on_prompts_changed(callback)

        # Act
        await manager.call_prompts_changed("server_id", prompts)

        # Assert
        callback.assert_awaited_once_with(prompts)

    async def test_prompts_changed_does_nothing_when_no_callback_registered(self):
        # Arrange
        manager = CallbackManager()
        prompts = [Prompt(name="test", description="test")]

        # Act
        await manager.call_prompts_changed("server_id", prompts)

        # Assert - Test passes if we reach this point without exception
        assert True


class TestLoggingMessageCallback:
    async def test_logging_message_does_not_raise_user_callback_exceptions(self):
        # Arrange
        manager = CallbackManager()
        logging_message = LoggingMessageNotification(level="info", data="test")
        callback = AsyncMock(side_effect=RuntimeError("User callback failed"))
        manager.on_logging_message(callback)

        # Act
        await manager.call_logging_message(logging_message)

        # Assert
        callback.assert_awaited_once_with(logging_message)

    async def test_logging_message_does_nothing_when_no_callback_registered(self):
        # Arrange
        manager = CallbackManager()
        logging_message = LoggingMessageNotification(level="info", data="test")

        # Act
        await manager.call_logging_message(logging_message)

        # Assert - Test passes if we reach this point without exception
        assert True


class TestCancelledCallback:
    async def test_cancelled_does_not_raise_user_callback_exceptions(self):
        # Arrange
        manager = CallbackManager()
        cancelled_notification = CancelledNotification(request_id="123", reason="test")
        callback = AsyncMock(side_effect=RuntimeError("User callback failed"))
        manager.on_cancelled(callback)

        # Act
        await manager.call_cancelled("server_id", cancelled_notification)

        # Assert
        callback.assert_awaited_once_with(cancelled_notification)

    async def test_cancelled_does_nothing_when_no_callback_registered(self):
        # Arrange
        manager = CallbackManager()
        cancelled_notification = CancelledNotification(request_id="123", reason="test")

        # Act
        await manager.call_cancelled("server_id", cancelled_notification)

        # Assert - Test passes if we reach this point without exception
        assert True
