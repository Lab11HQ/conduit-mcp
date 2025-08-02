from unittest.mock import AsyncMock, Mock

from conduit.protocol.base import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION,
    Error,
)
from conduit.protocol.common import EmptyResult
from conduit.protocol.initialization import (
    Implementation,
    ResourcesCapability,
    ServerCapabilities,
)
from conduit.protocol.resources import (
    ListResourcesRequest,
    ListResourcesResult,
    ListResourceTemplatesRequest,
    ListResourceTemplatesResult,
    ReadResourceRequest,
    ReadResourceResult,
    SubscribeRequest,
    UnsubscribeRequest,
)
from conduit.server.client_manager import ClientState
from conduit.server.message_context import MessageContext
from conduit.server.session import ServerConfig, ServerSession


class TestResourceHandling:
    """Base class for resource handling tests."""

    def setup_method(self):
        self.transport = Mock()
        self.config_with_resources = ServerConfig(
            capabilities=ServerCapabilities(
                resources=ResourcesCapability()  # Enable all features
            ),
            info=Implementation(name="test-server", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
        )
        self.config_without_resources = ServerConfig(
            capabilities=ServerCapabilities(),
            info=Implementation(name="test-server", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
        )
        self.config_with_subscription = ServerConfig(
            capabilities=ServerCapabilities(
                resources=ResourcesCapability(subscribe=True)
            ),
            info=Implementation(name="test-server", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
        )
        self.config_without_subscription = ServerConfig(
            capabilities=ServerCapabilities(
                resources=ResourcesCapability(subscribe=False)
            ),
            info=Implementation(name="test-server", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
        )
        self.context = MessageContext(
            client_id="test-client",
            client_state=ClientState(),
            client_manager=AsyncMock(),
            transport=self.transport,
        )


class TestListResources(TestResourceHandling):
    """Test server session resource listing."""

    async def test_list_resources_returns_result_when_capability_enabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_resources)

        # Mock the resources manager
        expected_result = ListResourcesResult(resources=[])
        session.resources.handle_list_resources = AsyncMock(
            return_value=expected_result
        )

        # Act
        result = await session._handle_list_resources(
            self.context, ListResourcesRequest()
        )

        # Assert
        assert result == expected_result
        session.resources.handle_list_resources.assert_awaited_once_with(
            self.context, ListResourcesRequest()
        )

    async def test_list_resources_returns_error_when_capability_disabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_without_resources)

        # Act
        result = await session._handle_list_resources(
            self.context, ListResourcesRequest()
        )

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

    async def test_list_resource_templates_returns_result_when_capability_enabled(
        self,
    ):
        # Arrange
        session = ServerSession(self.transport, self.config_with_resources)

        # Mock the resources manager
        expected_result = ListResourceTemplatesResult(resource_templates=[])
        session.resources.handle_list_templates = AsyncMock(
            return_value=expected_result
        )

        # Act
        result = await session._handle_list_resource_templates(
            self.context, ListResourceTemplatesRequest()
        )

        # Assert
        assert result == expected_result
        session.resources.handle_list_templates.assert_awaited_once_with(
            self.context, ListResourceTemplatesRequest()
        )

    async def test_list_resource_templates_returns_error_when_capability_disabled(
        self,
    ):
        # Arrange
        session = ServerSession(self.transport, self.config_without_resources)

        # Act
        result = await session._handle_list_resource_templates(
            self.context, ListResourceTemplatesRequest()
        )

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND


class TestReadResource(TestResourceHandling):
    """Test server session resource reading."""

    async def test_read_resource_returns_result_when_capability_enabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_resources)

        expected_result = ReadResourceResult(contents=[])
        session.resources.handle_read = AsyncMock(return_value=expected_result)

        # Act
        result = await session._handle_read_resource(
            self.context, ReadResourceRequest(uri="test-uri")
        )

        # Assert
        assert result == expected_result
        session.resources.handle_read.assert_awaited_once_with(
            self.context, ReadResourceRequest(uri="test-uri")
        )

    async def test_read_resource_returns_error_when_capability_disabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_without_resources)

        # Act
        result = await session._handle_read_resource(
            self.context, ReadResourceRequest(uri="test-uri")
        )

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

    async def test_read_resource_returns_error_when_resource_not_found(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_resources)

        # Mock the resources manager
        session.resources.handle_read = AsyncMock(side_effect=KeyError("test-uri"))

        # Act
        result = await session._handle_read_resource(
            self.context, ReadResourceRequest(uri="test-uri")
        )

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

        # Verify manager was called
        session.resources.handle_read.assert_awaited_once_with(
            self.context, ReadResourceRequest(uri="test-uri")
        )

    async def test_read_resource_returns_error_when_generic_exception_raised(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_resources)

        # Mock the resources manager
        session.resources.handle_read = AsyncMock(
            side_effect=RuntimeError("test-error")
        )

        # Act
        result = await session._handle_read_resource(
            self.context, ReadResourceRequest(uri="test-uri")
        )

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR

        # Verify manager was called
        session.resources.handle_read.assert_awaited_once_with(
            self.context, ReadResourceRequest(uri="test-uri")
        )


class TestSubscribeResource(TestResourceHandling):
    """Test server session resource subscription."""

    async def test_subscribe_returns_empty_result_when_capability_enabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_subscription)

        # Mock the resources manager
        session.resources.handle_subscribe = AsyncMock(return_value=EmptyResult())

        # Act
        result = await session._handle_subscribe(
            self.context, SubscribeRequest(uri="test-uri")
        )

        # Assert
        assert result == EmptyResult()
        session.resources.handle_subscribe.assert_awaited_once_with(
            self.context, SubscribeRequest(uri="test-uri")
        )

    async def test_subscribe_returns_error_when_capability_disabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_without_subscription)

        # Act
        result = await session._handle_subscribe(
            self.context, SubscribeRequest(uri="test-uri")
        )

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

    async def test_subscribe_returns_error_when_resource_not_found(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_subscription)

        # Mock the resources manager
        session.resources.handle_subscribe = AsyncMock(side_effect=KeyError("test-uri"))

        # Act
        result = await session._handle_subscribe(
            self.context, SubscribeRequest(uri="test-uri")
        )

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

    async def test_unsubscribe_returns_empty_result_when_capability_enabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_subscription)

        # Mock the resources manager
        session.resources.handle_unsubscribe = AsyncMock(return_value=EmptyResult())

        # Act
        result = await session._handle_unsubscribe(
            self.context, UnsubscribeRequest(uri="test-uri")
        )

        # Assert
        assert result == EmptyResult()
        session.resources.handle_unsubscribe.assert_awaited_once_with(
            self.context, UnsubscribeRequest(uri="test-uri")
        )

    async def test_unsubscribe_returns_error_when_capability_disabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_without_subscription)

        # Act
        result = await session._handle_unsubscribe(
            self.context, UnsubscribeRequest(uri="test-uri")
        )

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

    async def test_unsubscribe_returns_error_when_resource_not_found(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_subscription)

        # Mock the resources manager
        session.resources.handle_unsubscribe = AsyncMock(
            side_effect=KeyError("test-uri")
        )

        # Act
        result = await session._handle_unsubscribe(
            self.context, UnsubscribeRequest(uri="test-uri")
        )

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
