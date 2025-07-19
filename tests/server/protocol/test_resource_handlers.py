from unittest.mock import AsyncMock

import pytest

from conduit.protocol.resources import (
    EmptyResult,
    ListResourcesRequest,
    ListResourcesResult,
    ListResourceTemplatesRequest,
    ListResourceTemplatesResult,
    ReadResourceRequest,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    SubscribeRequest,
    TextResourceContents,
    UnsubscribeRequest,
)
from conduit.server.protocol.resources import ResourceManager


class TestHandleList:
    def setup_method(self):
        # Arrange - consistent setup for all tests
        self.manager = ResourceManager()
        self.client_id = "test-client-123"
        self.global_resource = Resource(uri="file:///global.txt", name="Global File")
        self.client_resource = Resource(uri="file:///client.txt", name="Client File")
        self.global_template = ResourceTemplate(
            uri_template="file:///logs/{date}.log", name="Log Template"
        )
        self.client_template = ResourceTemplate(
            uri_template="file:///data/{id}.json", name="Data Template"
        )
        self.mock_handler = AsyncMock()

    async def test_handle_list_resources_returns_all_client_resources(self):
        # Arrange
        self.manager.add_resource(self.global_resource, self.mock_handler)
        self.manager.add_client_resource(
            self.client_id, self.client_resource, self.mock_handler
        )
        request = ListResourcesRequest()

        # Act
        result = await self.manager.handle_list_resources(self.client_id, request)

        # Assert
        assert isinstance(result, ListResourcesResult)
        assert len(result.resources) == 2
        resource_uris = {resource.uri for resource in result.resources}
        assert "file:///global.txt" in resource_uris
        assert "file:///client.txt" in resource_uris

    async def test_handle_list_templates_returns_all_client_templates(self):
        # Arrange
        self.manager.add_template(self.global_template, self.mock_handler)
        self.manager.add_client_template(
            self.client_id, self.client_template, self.mock_handler
        )
        request = ListResourceTemplatesRequest()

        # Act
        result = await self.manager.handle_list_templates(self.client_id, request)

        # Assert
        assert isinstance(result, ListResourceTemplatesResult)
        assert len(result.resource_templates) == 2
        template_patterns = {
            template.uri_template for template in result.resource_templates
        }
        assert "file:///logs/{date}.log" in template_patterns
        assert "file:///data/{id}.json" in template_patterns

    async def test_handle_list_resources_returns_empty_when_no_resources(self):
        # Arrange - no resources registered
        request = ListResourcesRequest()

        # Act
        result = await self.manager.handle_list_resources(self.client_id, request)

        # Assert
        assert isinstance(result, ListResourcesResult)
        assert len(result.resources) == 0

    async def test_handle_list_resources_returns_only_global_when_no_client_specific(
        self,
    ):
        # Arrange - only global resource
        self.manager.add_resource(self.global_resource, self.mock_handler)
        request = ListResourcesRequest()

        # Act
        result = await self.manager.handle_list_resources(self.client_id, request)

        # Assert
        assert isinstance(result, ListResourcesResult)
        assert len(result.resources) == 1
        assert result.resources[0].uri == "file:///global.txt"

    async def test_handle_list_templates_returns_empty_when_no_templates(self):
        # Arrange - no templates registered
        request = ListResourceTemplatesRequest()

        # Act
        result = await self.manager.handle_list_templates(self.client_id, request)

        # Assert
        assert isinstance(result, ListResourceTemplatesResult)
        assert len(result.resource_templates) == 0

    async def test_handle_list_templates_returns_only_global_when_no_client_specific(
        self,
    ):
        # Arrange - only global template
        self.manager.add_template(self.global_template, self.mock_handler)
        request = ListResourceTemplatesRequest()

        # Act
        result = await self.manager.handle_list_templates(self.client_id, request)

        # Assert
        assert isinstance(result, ListResourceTemplatesResult)
        assert len(result.resource_templates) == 1
        assert result.resource_templates[0].uri_template == "file:///logs/{date}.log"

    async def test_handle_list_resources_client_specific_overrides_global(self):
        # Arrange - same URI for both global and client-specific resources
        global_resource = Resource(uri="file:///config.json", name="Global Config")
        client_resource = Resource(
            uri="file:///config.json", name="Client Config Override"
        )

        self.manager.add_resource(global_resource, self.mock_handler)
        self.manager.add_client_resource(
            self.client_id, client_resource, self.mock_handler
        )
        request = ListResourcesRequest()

        # Act
        result = await self.manager.handle_list_resources(self.client_id, request)

        # Assert
        assert isinstance(result, ListResourcesResult)
        assert len(result.resources) == 1  # Only one resource despite same URI

        # Verify client-specific resource is returned, not global
        returned_resource = result.resources[0]
        assert returned_resource.uri == "file:///config.json"
        assert returned_resource.name == "Client Config Override"  # Client wins

    async def test_handle_list_templates_client_specific_overrides_global(self):
        # Arrange - same URI pattern for both global and client-specific templates
        global_template = ResourceTemplate(
            uri_template="file:///logs/{date}.log", name="Global Log Template"
        )
        client_template = ResourceTemplate(
            uri_template="file:///logs/{date}.log", name="Client Log Template Override"
        )

        self.manager.add_template(global_template, self.mock_handler)
        self.manager.add_client_template(
            self.client_id, client_template, self.mock_handler
        )
        request = ListResourceTemplatesRequest()

        # Act
        result = await self.manager.handle_list_templates(self.client_id, request)

        # Assert
        assert isinstance(result, ListResourceTemplatesResult)
        assert (
            len(result.resource_templates) == 1
        )  # Only one template despite same pattern

        # Verify client-specific template is returned, not global
        returned_template = result.resource_templates[0]
        assert returned_template.uri_template == "file:///logs/{date}.log"
        assert returned_template.name == "Client Log Template Override"  # Client wins


class TestHandleRead:
    def setup_method(self):
        # Arrange - consistent setup for all tests
        self.manager = ResourceManager()
        self.client_id = "test-client-123"
        self.test_resource = Resource(uri="file:///test.txt", name="Test File")
        self.expected_result = ReadResourceResult(
            contents=[
                TextResourceContents(uri="file:///test.txt", text="Hello, World!")
            ]
        )
        self.mock_handler = AsyncMock(return_value=self.expected_result)

    async def test_handle_read_calls_handler_and_returns_result(self):
        # Arrange
        self.manager.add_resource(self.test_resource, self.mock_handler)
        request = ReadResourceRequest(uri="file:///test.txt")

        # Act
        result = await self.manager.handle_read(self.client_id, request)

        # Assert
        # Verify handler was called with correct parameters
        self.mock_handler.assert_awaited_once_with(self.client_id, request)

        # Verify result matches expectations
        assert result == self.expected_result

    async def test_handle_read_calls_template_handler_and_returns_result(self):
        # Arrange
        log_template = ResourceTemplate(
            uri_template="file:///logs/{date}.log", name="Daily Logs"
        )
        expected_result = ReadResourceResult(
            contents=[
                TextResourceContents(
                    uri="file:///logs/2024-01-15.log",
                    text="2024-01-15: System started",
                )
            ]
        )
        template_handler = AsyncMock(return_value=expected_result)

        self.manager.add_template(log_template, template_handler)
        request = ReadResourceRequest(uri="file:///logs/2024-01-15.log")

        # Act
        result = await self.manager.handle_read(self.client_id, request)

        # Assert
        # Verify template handler was called with correct parameters
        template_handler.assert_awaited_once_with(self.client_id, request)

        # Verify result matches expectations
        assert result == expected_result

    async def test_handle_read_raises_keyerror_for_unknown_resource(self):
        # Arrange - no resources or templates registered
        request = ReadResourceRequest(uri="file:///nonexistent.txt")

        # Act & Assert
        with pytest.raises(KeyError):
            await self.manager.handle_read(self.client_id, request)

    async def test_handle_read_propagates_handler_exception(self):
        # Arrange
        failing_handler = AsyncMock(side_effect=RuntimeError("Handler failed"))
        self.manager.add_resource(self.test_resource, failing_handler)
        request = ReadResourceRequest(uri="file:///test.txt")

        # Act & Assert
        with pytest.raises(RuntimeError):
            await self.manager.handle_read(self.client_id, request)

        # Verify handler was called before it failed
        failing_handler.assert_awaited_once_with(self.client_id, request)


class TestHandleSubscription:
    def setup_method(self):
        # Arrange - consistent setup for all tests
        self.manager = ResourceManager()
        self.client_id = "test-client-123"
        self.test_resource = Resource(uri="file:///test.txt", name="Test File")
        self.mock_handler = AsyncMock()

    async def test_handle_subscribe_records_subscription_and_returns_empty_result(self):
        # Arrange
        self.manager.add_resource(self.test_resource, self.mock_handler)
        subscribe_callback = AsyncMock()
        self.manager.subscribe_handler = subscribe_callback
        request = SubscribeRequest(uri="file:///test.txt")

        # Act
        result = await self.manager.handle_subscribe(self.client_id, request)

        # Assert
        # Verify subscription was recorded
        assert self.client_id in self.manager._client_subscriptions
        assert "file:///test.txt" in self.manager._client_subscriptions[self.client_id]

        # Verify callback was called
        subscribe_callback.assert_awaited_once_with(self.client_id, "file:///test.txt")

        # Verify empty result returned
        assert isinstance(result, EmptyResult)

    async def test_handle_unsubscribe_removes_subscription_and_returns_empty_result(
        self,
    ):
        # Arrange - first subscribe to have something to unsubscribe from
        self.manager.add_resource(self.test_resource, self.mock_handler)
        self.manager._client_subscriptions[self.client_id] = {"file:///test.txt"}

        unsubscribe_callback = AsyncMock()
        self.manager.unsubscribe_handler = unsubscribe_callback
        request = UnsubscribeRequest(uri="file:///test.txt")

        # Act
        result = await self.manager.handle_unsubscribe(self.client_id, request)

        # Assert
        # Verify subscription was removed
        assert (
            "file:///test.txt" not in self.manager._client_subscriptions[self.client_id]
        )

        # Verify callback was called
        unsubscribe_callback.assert_awaited_once_with(
            self.client_id, "file:///test.txt"
        )

        # Verify empty result returned
        assert isinstance(result, EmptyResult)

    async def test_handle_subscribe_raises_keyerror_for_unknown_resource(self):
        # Arrange - no resources or templates registered
        request = SubscribeRequest(uri="file:///nonexistent.txt")

        # Act & Assert
        with pytest.raises(KeyError):
            await self.manager.handle_subscribe(self.client_id, request)

        # Verify no subscription was recorded
        assert self.client_id not in self.manager._client_subscriptions

    async def test_handle_unsubscribe_raises_keyerror_for_no_subscription(self):
        # Arrange - resource exists but client is not subscribed to it
        self.manager.add_resource(self.test_resource, self.mock_handler)
        request = UnsubscribeRequest(uri="file:///test.txt")
        assert self.client_id not in self.manager._client_subscriptions

        # Act & Assert
        with pytest.raises(KeyError):
            await self.manager.handle_unsubscribe(self.client_id, request)

    async def test_handle_subscribe_continues_when_callback_raises(self):
        # Arrange
        self.manager.add_resource(self.test_resource, self.mock_handler)
        failing_callback = AsyncMock(side_effect=RuntimeError("Callback failed"))
        self.manager.subscribe_handler = failing_callback
        request = SubscribeRequest(uri="file:///test.txt")

        # Act - should not raise the callback exception
        result = await self.manager.handle_subscribe(self.client_id, request)

        # Assert
        # Verify subscription was still recorded despite callback failure
        assert self.client_id in self.manager._client_subscriptions
        assert "file:///test.txt" in self.manager._client_subscriptions[self.client_id]

        # Verify callback was called
        failing_callback.assert_awaited_once_with(self.client_id, "file:///test.txt")

        # Verify empty result returned
        assert isinstance(result, EmptyResult)

    async def test_handle_unsubscribe_continues_when_callback_raises(self):
        # Arrange - first subscribe to have something to unsubscribe from
        self.manager.add_resource(self.test_resource, self.mock_handler)
        self.manager._client_subscriptions[self.client_id] = {"file:///test.txt"}

        failing_callback = AsyncMock(side_effect=RuntimeError("Callback failed"))
        self.manager.unsubscribe_handler = failing_callback
        request = UnsubscribeRequest(uri="file:///test.txt")

        # Act - should not raise the callback exception
        result = await self.manager.handle_unsubscribe(self.client_id, request)

        # Assert
        # Verify subscription was still removed despite callback failure
        assert (
            "file:///test.txt" not in self.manager._client_subscriptions[self.client_id]
        )

        # Verify callback was called
        failing_callback.assert_awaited_once_with(self.client_id, "file:///test.txt")

        # Verify empty result returned
        assert isinstance(result, EmptyResult)
