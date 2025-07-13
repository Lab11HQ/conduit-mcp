import asyncio
from unittest.mock import AsyncMock

import pytest

from conduit.protocol.common import EmptyResult
from conduit.protocol.content import TextResourceContents
from conduit.protocol.resources import (
    ListResourcesRequest,
    ListResourcesResult,
    ListResourceTemplatesRequest,
    ListResourceTemplatesResult,
    ReadResourceRequest,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    SubscribeRequest,
    UnsubscribeRequest,
)
from conduit.server.client_manager import ClientManager
from conduit.server.protocol.resources import ResourceManager


class TestResourceManager:
    def setup_method(self):
        # Arrange - Create client manager and register a test client
        self.client_manager = ClientManager()
        self.client_id = "test-client-123"
        self.client_context = self.client_manager.register_client(self.client_id)

    def test_register_resource_stores_resource_and_handler(self):
        # Arrange
        manager = ResourceManager(self.client_manager)
        resource = Resource(uri="file://test.txt", name="Test File")
        handler = AsyncMock()

        # Act
        manager.register(resource, handler)

        # Assert
        assert "file://test.txt" in manager.registered_resources
        assert manager.registered_resources["file://test.txt"] is resource
        assert "file://test.txt" in manager.handlers
        assert manager.handlers["file://test.txt"] is handler

    def test_register_template_stores_template_and_handler(self):
        # Arrange
        manager = ResourceManager(self.client_manager)
        template = ResourceTemplate(
            uri_template="file://logs/{date}.log", name="Log Files"
        )
        handler = AsyncMock()

        # Act
        manager.register(template, handler)

        # Assert
        assert "file://logs/{date}.log" in manager.registered_templates
        assert manager.registered_templates["file://logs/{date}.log"] is template
        assert "file://logs/{date}.log" in manager.template_handlers
        assert manager.template_handlers["file://logs/{date}.log"] is handler

    async def test_handle_list_resources_returns_registered_resources(self):
        # Arrange
        manager = ResourceManager(self.client_manager)
        resource = Resource(uri="file://test.txt", name="Test File")
        handler = AsyncMock()
        manager.register(resource, handler)
        request = ListResourcesRequest()

        # Act
        result = await manager.handle_list_resources(self.client_id, request)

        # Assert
        assert result == ListResourcesResult(resources=[resource])

    async def test_handle_list_templates_returns_registered_templates(self):
        # Arrange
        manager = ResourceManager(self.client_manager)
        template = ResourceTemplate(
            uri_template="file://logs/{date}.log", name="Log Files"
        )
        handler = AsyncMock()
        manager.register(template, handler)
        request = ListResourceTemplatesRequest()

        # Act
        result = await manager.handle_list_templates(self.client_id, request)

        # Assert
        assert result == ListResourceTemplatesResult(resource_templates=[template])

    async def test_handle_read_delegates_to_static_resource_handler(self):
        # Arrange
        manager = ResourceManager(self.client_manager)
        resource = Resource(uri="file://test.txt", name="Test File")
        expected_result = ReadResourceResult(
            contents=[TextResourceContents(uri="file://test.txt", text="file content")]
        )
        handler = AsyncMock(return_value=expected_result)
        manager.register(resource, handler)
        request = ReadResourceRequest(uri="file://test.txt")

        # Act
        result = await manager.handle_read(self.client_id, request)

        # Assert
        handler.assert_awaited_once_with(self.client_id, request)
        assert result is expected_result

    async def test_handle_read_raises_keyerror_for_unknown_resource(self):
        # Arrange - don't register any resources
        manager = ResourceManager(self.client_manager)
        request = ReadResourceRequest(uri="file://unknown.txt")

        # Act & Assert
        with pytest.raises(KeyError):
            await manager.handle_read(self.client_id, request)

    async def test_handle_subscribe_adds_to_subscriptions_for_known_resource(self):
        # Arrange
        manager = ResourceManager(self.client_manager)
        resource = Resource(uri="file://test.txt", name="Test File")
        handler = AsyncMock()
        manager.register(resource, handler)
        request = SubscribeRequest(uri="file://test.txt")

        # Act
        result = await manager.handle_subscribe(self.client_id, request)

        # Assert
        assert "file://test.txt" in self.client_context.subscriptions
        assert isinstance(result, EmptyResult)

    async def test_handle_subscribe_calls_callback_if_registered(self):
        # Arrange
        manager = ResourceManager(self.client_manager)
        resource = Resource(uri="file://test.txt", name="Test File")
        handler = AsyncMock()
        callback = AsyncMock()
        manager.register(resource, handler)
        manager.on_subscribe(callback)
        request = SubscribeRequest(uri="file://test.txt")

        # Act
        await manager.handle_subscribe(self.client_id, request)

        # Assert
        await asyncio.sleep(0)  # Yield to let the callback run
        callback.assert_awaited_once_with(self.client_id, "file://test.txt")

    async def test_handle_subscribe_raises_keyerror_for_unknown_resource(self):
        # Arrange
        manager = ResourceManager(self.client_manager)
        request = SubscribeRequest(uri="file://unknown.txt")

        # Act & Assert
        with pytest.raises(KeyError):
            await manager.handle_subscribe(self.client_id, request)

    async def test_handle_unsubscribe_removes_from_subscriptions(self):
        # Arrange
        manager = ResourceManager(self.client_manager)
        resource = Resource(uri="file://test.txt", name="Test File")
        handler = AsyncMock()
        manager.register(resource, handler)
        self.client_context.subscriptions.add("file://test.txt")
        assert "file://test.txt" in self.client_context.subscriptions
        request = UnsubscribeRequest(uri="file://test.txt")

        # Act
        result = await manager.handle_unsubscribe(self.client_id, request)

        # Assert
        assert "file://test.txt" not in self.client_context.subscriptions
        assert isinstance(result, EmptyResult)

    async def test_handle_unsubscribe_calls_callback_if_registered(self):
        # Arrange
        manager = ResourceManager(self.client_manager)
        callback = AsyncMock()
        self.client_context.subscriptions.add("file://test.txt")
        assert "file://test.txt" in self.client_context.subscriptions
        manager.on_unsubscribe(callback)
        request = UnsubscribeRequest(uri="file://test.txt")

        # Act
        await manager.handle_unsubscribe(self.client_id, request)

        # Assert
        await asyncio.sleep(0)  # Yield to let the callback run
        callback.assert_awaited_once_with(self.client_id, "file://test.txt")

    async def test_handle_unsubscribe_raises_keyerror_if_not_subscribed(self):
        # Arrange - don't subscribe to any resources
        manager = ResourceManager(self.client_manager)
        request = UnsubscribeRequest(uri="file://test.txt")

        # Act & Assert
        with pytest.raises(KeyError):
            await manager.handle_unsubscribe(self.client_id, request)

    async def test_handle_read_delegates_to_template_handler_when_uri_matches_pattern(
        self,
    ):
        # Arrange
        manager = ResourceManager(self.client_manager)
        template = ResourceTemplate(
            uri_template="file://logs/{date}.log", name="Log Files"
        )
        expected_result = ReadResourceResult(
            contents=[
                TextResourceContents(
                    uri="file://logs/2024-01-15.log", text="log content for 2024-01-15"
                )
            ]
        )
        handler = AsyncMock(return_value=expected_result)
        manager.register(template, handler)
        request = ReadResourceRequest(uri="file://logs/2024-01-15.log")

        # Act
        result = await manager.handle_read(self.client_id, request)

        # Assert
        handler.assert_awaited_once_with(self.client_id, request)
        assert result is expected_result

    async def test_handle_subscribe_allows_subscription_to_template_matching_uri(self):
        # Arrange
        manager = ResourceManager(self.client_manager)
        template = ResourceTemplate(
            uri_template="file://logs/{date}.log", name="Log Files"
        )
        handler = AsyncMock()
        callback = AsyncMock()
        manager.register(template, handler)
        manager.on_subscribe(callback)
        request = SubscribeRequest(uri="file://logs/2024-01-15.log")

        # Act
        result = await manager.handle_subscribe(self.client_id, request)

        # Assert
        assert "file://logs/2024-01-15.log" in self.client_context.subscriptions
        await asyncio.sleep(0)  # Yield to let the callback run
        callback.assert_awaited_once_with(self.client_id, "file://logs/2024-01-15.log")
        assert isinstance(result, EmptyResult)

    async def test_handle_subscribe_raises_keyerror_for_non_matching_template(self):
        # Arrange
        manager = ResourceManager(self.client_manager)
        template = ResourceTemplate(
            uri_template="file://logs/{date}.log", name="Log Files"
        )
        handler = AsyncMock()
        manager.register(template, handler)
        request = SubscribeRequest(uri="file://config/settings.json")

        # Act & Assert
        with pytest.raises(KeyError):
            await manager.handle_subscribe(self.client_id, request)
