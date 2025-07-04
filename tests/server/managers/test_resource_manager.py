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
from conduit.server.managers.resources import ResourceManager


class TestResourceManager:
    def test_register_resource_stores_resource_and_handler(self):
        # Arrange
        manager = ResourceManager()
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
        manager = ResourceManager()
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
        manager = ResourceManager()
        resource = Resource(uri="file://test.txt", name="Test File")
        handler = AsyncMock()
        manager.register(resource, handler)
        request = ListResourcesRequest()

        # Act
        result = await manager.handle_list_resources(request)

        # Assert
        assert result == ListResourcesResult(resources=[resource])

    async def test_handle_list_templates_returns_registered_templates(self):
        # Arrange
        manager = ResourceManager()
        template = ResourceTemplate(
            uri_template="file://logs/{date}.log", name="Log Files"
        )
        handler = AsyncMock()
        manager.register(template, handler)
        request = ListResourceTemplatesRequest()

        # Act
        result = await manager.handle_list_templates(request)

        # Assert
        assert result == ListResourceTemplatesResult(resource_templates=[template])

    async def test_handle_read_delegates_to_static_resource_handler(self):
        # Arrange
        manager = ResourceManager()
        resource = Resource(uri="file://test.txt", name="Test File")
        expected_result = ReadResourceResult(
            contents=[TextResourceContents(uri="file://test.txt", text="file content")]
        )
        handler = AsyncMock(return_value=expected_result)
        manager.register(resource, handler)
        request = ReadResourceRequest(uri="file://test.txt")

        # Act
        result = await manager.handle_read(request)

        # Assert
        handler.assert_awaited_once_with(request)
        assert result is expected_result

    async def test_handle_read_raises_keyerror_for_unknown_resource(self):
        # Arrange
        manager = ResourceManager()
        request = ReadResourceRequest(uri="file://unknown.txt")

        # Act & Assert
        with pytest.raises(KeyError, match="Unknown resource: file://unknown.txt"):
            await manager.handle_read(request)

    async def test_handle_subscribe_adds_to_subscriptions_for_known_resource(self):
        # Arrange
        manager = ResourceManager()
        resource = Resource(uri="file://test.txt", name="Test File")
        handler = AsyncMock()
        manager.register(resource, handler)
        request = SubscribeRequest(uri="file://test.txt")

        # Act
        result = await manager.handle_subscribe(request)

        # Assert
        assert "file://test.txt" in manager.subscriptions
        assert isinstance(result, EmptyResult)

    async def test_handle_subscribe_calls_callback_if_registered(self):
        # Arrange
        manager = ResourceManager()
        resource = Resource(uri="file://test.txt", name="Test File")
        handler = AsyncMock()
        callback = AsyncMock()
        manager.register(resource, handler)
        manager._on_subscribe = callback
        request = SubscribeRequest(uri="file://test.txt")

        # Act
        await manager.handle_subscribe(request)

        # Assert
        callback.assert_awaited_once_with("file://test.txt")

    async def test_handle_subscribe_raises_keyerror_for_unknown_resource(self):
        # Arrange
        manager = ResourceManager()
        request = SubscribeRequest(uri="file://unknown.txt")

        # Act & Assert
        with pytest.raises(
            KeyError, match="Cannot subscribe to unknown resource: file://unknown.txt"
        ):
            await manager.handle_subscribe(request)

    async def test_handle_unsubscribe_removes_from_subscriptions(self):
        # Arrange
        manager = ResourceManager()
        resource = Resource(uri="file://test.txt", name="Test File")
        handler = AsyncMock()
        manager.register(resource, handler)
        manager.subscriptions.add("file://test.txt")
        request = UnsubscribeRequest(uri="file://test.txt")

        # Act
        result = await manager.handle_unsubscribe(request)

        # Assert
        assert "file://test.txt" not in manager.subscriptions
        assert isinstance(result, EmptyResult)

    async def test_handle_unsubscribe_calls_callback_if_registered(self):
        # Arrange
        manager = ResourceManager()
        callback = AsyncMock()
        manager.subscriptions.add("file://test.txt")
        manager._on_unsubscribe = callback
        request = UnsubscribeRequest(uri="file://test.txt")

        # Act
        await manager.handle_unsubscribe(request)

        # Assert
        callback.assert_awaited_once_with("file://test.txt")

    async def test_handle_unsubscribe_raises_keyerror_if_not_subscribed(self):
        # Arrange
        manager = ResourceManager()
        request = UnsubscribeRequest(uri="file://test.txt")

        # Act & Assert
        with pytest.raises(
            KeyError, match="Not subscribed to resource: file://test.txt"
        ):
            await manager.handle_unsubscribe(request)

    async def test_handle_read_delegates_to_template_handler_when_uri_matches_pattern(
        self,
    ):
        # Arrange
        manager = ResourceManager()
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
        result = await manager.handle_read(request)

        # Assert
        handler.assert_awaited_once_with(request)
        assert result is expected_result

    async def test_handle_subscribe_allows_subscription_to_template_matching_uri(self):
        # Arrange
        manager = ResourceManager()
        template = ResourceTemplate(
            uri_template="file://logs/{date}.log", name="Log Files"
        )
        handler = AsyncMock()
        callback = AsyncMock()
        manager.register(template, handler)
        manager._on_subscribe = callback
        request = SubscribeRequest(uri="file://logs/2024-01-15.log")

        # Act
        result = await manager.handle_subscribe(request)

        # Assert
        assert "file://logs/2024-01-15.log" in manager.subscriptions
        callback.assert_awaited_once_with("file://logs/2024-01-15.log")
        assert isinstance(result, EmptyResult)

    def test_matches_template(self):
        # Arrange
        uri = "file://logs/2024-01-15.log"
        template = "file://logs/{date}.log"
        manager = ResourceManager()

        # Act
        result = manager._matches_template(uri=uri, template=template)

        # Assert
        assert result is True

    def test_does_not_match_template(self):
        # Arrange
        uri = "file://config.json"
        template = "file://logs/{date}.log"
        manager = ResourceManager()

        # Act
        result = manager._matches_template(uri=uri, template=template)

        # Assert
        assert result is False

    # def test_extract_template_variables(self):
    #     # Arrange
    #     uri = "db://users/123/posts/456"
    #     template = "db://users/{user_id}/posts/{post_id}"
    #     manager = ResourceManager()

    #     # Act
    #     result = manager._extract_template_variables(uri, template)

    #     # Assert
    #     assert result == {"user_id": "123", "post_id": "456"}
