from unittest.mock import AsyncMock

from conduit.client.session_v2 import ClientConfig, ClientSession
from conduit.protocol.base import METHOD_NOT_FOUND, Error
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    RootsCapability,
)
from conduit.protocol.roots import ListRootsRequest, ListRootsResult


class TestRootsRequestHandling:
    """Test roots/list request handling."""

    def setup_method(self):
        self.transport = AsyncMock()
        self.config_with_roots = ClientConfig(
            client_info=Implementation(name="test-client", version="1.0.0"),
            capabilities=ClientCapabilities(roots=RootsCapability()),
        )
        self.config_without_roots = ClientConfig(
            client_info=Implementation(name="test-client", version="1.0.0"),
            capabilities=ClientCapabilities(roots=None),
        )

    list_roots_request = ListRootsRequest()

    async def test_delegates_to_roots_manager_when_capability_advertised(self):
        """Test that roots requests delegate to manager when capability exists."""
        # Arrange
        self.session = ClientSession(self.transport, self.config_with_roots)

        # Mock the roots manager
        mock_result = ListRootsResult(roots=[])
        self.session.roots.handle_list_roots = AsyncMock(return_value=mock_result)

        # Act
        result = await self.session._handle_list_roots(
            "server_id", self.list_roots_request
        )

        # Assert
        assert result == mock_result
        self.session.roots.handle_list_roots.assert_awaited_once()

    async def test_returns_error_when_roots_capability_not_advertised(self):
        """Test that roots requests return METHOD_NOT_FOUND when capability missing."""
        # Arrange
        self.session = ClientSession(self.transport, self.config_without_roots)

        # Act
        result = await self.session._handle_list_roots(
            "server_id", self.list_roots_request
        )

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
