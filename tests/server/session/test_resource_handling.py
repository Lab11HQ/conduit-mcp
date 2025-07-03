from unittest.mock import AsyncMock

from conduit.protocol.base import INTERNAL_ERROR, METHOD_NOT_FOUND, Error
from conduit.protocol.common import EmptyResult
from conduit.protocol.content import TextResourceContents
from conduit.protocol.initialization import ResourcesCapability
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

from .conftest import ServerSessionTest


class TestListResources(ServerSessionTest):
    async def test_returns_resources_from_manager_when_capability_enabled(self):
        """Test listing static resources."""
        # Arrange
        self.config.capabilities.resources = ResourcesCapability()

        # Create expected resources
        resource1 = Resource(
            name="test_resource_1",
            uri="file:///test1.txt",
            description="A test resource",
            mime_type="text/plain",
        )
        resource2 = Resource(
            name="test_resource_2",
            uri="file:///test2.txt",
            description="Another test resource",
            mime_type="text/plain",
        )

        # Mock the manager to return our resources
        self.session.resources.handle_list_resources = AsyncMock(
            return_value=ListResourcesResult(resources=[resource1, resource2])
        )

        request = ListResourcesRequest()

        # Act
        result = await self.session._handle_list_resources(request)

        # Assert
        assert isinstance(result, ListResourcesResult)
        assert len(result.resources) == 2
        assert result.resources[0].name == "test_resource_1"
        assert result.resources[1].name == "test_resource_2"

        # Verify manager was called
        self.session.resources.handle_list_resources.assert_awaited_once_with(request)

    async def test_rejects_list_resources_when_capability_not_set(self):
        """Test error when resources capability is not configured."""
        # Arrange
        self.config.capabilities.resources = None  # No resources capability
        request = ListResourcesRequest()

        # Act
        result = await self.session._handle_list_resources(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "Server does not support resources capability"


class TestListResourceTemplates(ServerSessionTest):
    async def test_returns_templates_from_manager_when_capability_enabled(self):
        """Test listing resource templates."""
        # Arrange
        self.config.capabilities.resources = ResourcesCapability()

        # Create expected templates
        template1 = ResourceTemplate(
            name="log_template",
            uri_template="file:///logs/{date}.log",
            description="Daily log files",
            mime_type="text/plain",
        )
        template2 = ResourceTemplate(
            name="user_template",
            uri_template="db://users/{user_id}",
            description="User profile data",
            mime_type="application/json",
        )

        # Mock the manager to return our templates
        self.session.resources.handle_list_templates = AsyncMock(
            return_value=ListResourceTemplatesResult(
                resource_templates=[template1, template2]
            )
        )

        request = ListResourceTemplatesRequest()

        # Act
        result = await self.session._handle_list_resource_templates(request)

        # Assert
        assert isinstance(result, ListResourceTemplatesResult)
        assert len(result.resource_templates) == 2
        assert result.resource_templates[0].name == "log_template"
        assert result.resource_templates[0].uri_template == "file:///logs/{date}.log"
        assert result.resource_templates[1].name == "user_template"
        assert result.resource_templates[1].uri_template == "db://users/{user_id}"

        # Verify manager was called
        self.session.resources.handle_list_templates.assert_awaited_once_with(request)

    async def test_rejects_list_templates_when_capability_not_set(self):
        """Test error when resources capability is not configured."""
        # Arrange
        self.config.capabilities.resources = None  # No resources capability
        request = ListResourceTemplatesRequest()

        # Act
        result = await self.session._handle_list_resource_templates(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "Server does not support resources capability"


class TestReadResource(ServerSessionTest):
    async def test_returns_static_resource_when_capability_enabled(self):
        """Test reading a static resource."""
        # Arrange
        self.config.capabilities.resources = ResourcesCapability()

        expected_result = ReadResourceResult(
            contents=[
                TextResourceContents(
                    uri="file:///test.txt",
                    text="Hello, world!",
                    mime_type="text/plain",
                )
            ]
        )

        # Mock the manager to return success
        self.session.resources.handle_read = AsyncMock(return_value=expected_result)

        request = ReadResourceRequest(uri="file:///test.txt")

        # Act
        result = await self.session._handle_read_resource(request)

        # Assert
        assert isinstance(result, ReadResourceResult)
        assert len(result.contents) == 1
        assert result.contents[0].uri == "file:///test.txt"
        assert result.contents[0].text == "Hello, world!"

        # Verify manager was called
        self.session.resources.handle_read.assert_awaited_once_with(request)

    async def test_rejects_read_resource_when_capability_not_set(self):
        """Test error when resources capability is not configured."""
        # Arrange
        self.config.capabilities.resources = None  # No resources capability
        request = ReadResourceRequest(uri="file:///test.txt")

        # Act
        result = await self.session._handle_read_resource(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "Server does not support resources capability"

    async def test_returns_method_not_found_when_resource_unknown(self):
        """Test error when manager raises KeyError for unknown resource."""
        # Arrange
        self.config.capabilities.resources = ResourcesCapability()

        # Mock the manager to raise KeyError (unknown resource)
        self.session.resources.handle_read = AsyncMock(
            side_effect=KeyError("Unknown resource: file:///nonexistent.txt")
        )

        request = ReadResourceRequest(uri="file:///nonexistent.txt")

        # Act
        result = await self.session._handle_read_resource(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert "unknown resource" in result.message.lower()

        # Verify manager was called
        self.session.resources.handle_read.assert_awaited_once_with(request)

    async def test_returns_internal_error_when_manager_raises_exception(self):
        """Test error when manager raises unexpected exception."""
        # Arrange
        self.config.capabilities.resources = ResourcesCapability()

        # Mock the manager to raise generic exception
        self.session.resources.handle_read = AsyncMock(
            side_effect=ValueError("File system error")
        )

        request = ReadResourceRequest(uri="file:///test.txt")

        # Act
        result = await self.session._handle_read_resource(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR
        assert result.message == "Error reading resource"

        # Verify manager was called
        self.session.resources.handle_read.assert_awaited_once_with(request)


class TestResourceSubscription(ServerSessionTest):
    async def test_subscribes_to_static_resource_when_capability_enabled(self):
        """Test subscribing to a static resource."""
        # Arrange
        self.config.capabilities.resources = ResourcesCapability(subscribe=True)

        # Mock the manager to return success
        self.session.resources.handle_subscribe = AsyncMock(return_value=EmptyResult())

        request = SubscribeRequest(uri="file:///test.txt")

        # Act
        result = await self.session._handle_subscribe(request)

        # Assert
        assert isinstance(result, EmptyResult)

        # Verify manager was called
        self.session.resources.handle_subscribe.assert_awaited_once_with(request)

    async def test_rejects_subscribe_when_resources_capability_not_set(self):
        """Test error when resources capability is not configured."""
        # Arrange
        self.config.capabilities.resources = None  # No resources capability
        request = SubscribeRequest(uri="file:///test.txt")

        # Act
        result = await self.session._handle_subscribe(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "Server does not support resource subscription"

    async def test_rejects_subscribe_when_subscribe_capability_not_set(self):
        """Test error when resources capability exists but subscribe is not enabled."""
        # Arrange
        self.config.capabilities.resources = ResourcesCapability(subscribe=False)
        request = SubscribeRequest(uri="file:///test.txt")

        # Act
        result = await self.session._handle_subscribe(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "Server does not support resource subscription"

    async def test_returns_method_not_found_when_resource_unknown(self):
        """Test error when manager raises KeyError for unknown resource."""
        # Arrange
        self.config.capabilities.resources = ResourcesCapability(subscribe=True)

        # Mock the manager to raise KeyError (unknown resource)
        self.session.resources.handle_subscribe = AsyncMock(
            side_effect=KeyError(
                "Cannot subscribe to unknown resource: file:///nonexistent.txt"
            )
        )

        request = SubscribeRequest(uri="file:///nonexistent.txt")

        # Act
        result = await self.session._handle_subscribe(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert "unknown resource" in result.message.lower()

        # Verify manager was called
        self.session.resources.handle_subscribe.assert_awaited_once_with(request)

    async def test_unsubscribes_from_resource_when_capability_enabled(self):
        """Test successful unsubscription from resource when capability is enabled."""
        # Arrange
        self.config.capabilities.resources = ResourcesCapability(subscribe=True)

        # Mock the manager to return success
        self.session.resources.handle_unsubscribe = AsyncMock(
            return_value=EmptyResult()
        )

        request = UnsubscribeRequest(uri="file:///test.txt")

        # Act
        result = await self.session._handle_unsubscribe(request)

        # Assert
        assert isinstance(result, EmptyResult)

        # Verify manager was called
        self.session.resources.handle_unsubscribe.assert_awaited_once_with(request)

    async def test_rejects_unsubscribe_when_resources_capability_not_set(self):
        """Test error when resources capability is not configured."""
        # Arrange
        self.config.capabilities.resources = None  # No resources capability
        request = UnsubscribeRequest(uri="file:///test.txt")

        # Act
        result = await self.session._handle_unsubscribe(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "Server does not support resource subscription"

    async def test_rejects_unsubscribe_when_subscribe_capability_not_set(self):
        """Test error when resources capability exists but subscribe is not enabled."""
        # Arrange
        self.config.capabilities.resources = ResourcesCapability(subscribe=False)
        request = UnsubscribeRequest(uri="file:///test.txt")

        # Act
        result = await self.session._handle_unsubscribe(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "Server does not support resource subscription"

    async def test_returns_method_not_found_when_not_subscribed(self):
        """Test error when manager raises KeyError for unsubscribed resource."""
        # Arrange
        self.config.capabilities.resources = ResourcesCapability(subscribe=True)

        # Mock the manager to raise KeyError (not subscribed)
        self.session.resources.handle_unsubscribe = AsyncMock(
            side_effect=KeyError("Not subscribed to resource: file:///test.txt")
        )

        request = UnsubscribeRequest(uri="file:///test.txt")

        # Act
        result = await self.session._handle_unsubscribe(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert "not subscribed" in result.message.lower()

        # Verify manager was called
        self.session.resources.handle_unsubscribe.assert_awaited_once_with(request)
