from unittest.mock import AsyncMock

from conduit.client.session import ClientSession
from conduit.protocol.base import METHOD_NOT_FOUND, Error
from conduit.protocol.initialization import RootsCapability
from conduit.protocol.roots import ListRootsRequest, ListRootsResult
from tests.client.session.conftest import ClientSessionTest


class TestRootsRequestHandling(ClientSessionTest):
    """Test roots/list request handling."""

    roots_request = ListRootsRequest()

    async def test_delegates_to_roots_manager_when_capability_advertised(self):
        """Test that roots requests delegate to manager when capability exists."""
        # Arrange
        self.config.capabilities.roots = RootsCapability(list_changed=True)
        self.session = ClientSession(self.transport, self.config)

        # Mock the roots manager
        mock_result = ListRootsResult(roots=[])
        self.session.roots.handle_list_roots = AsyncMock(return_value=mock_result)

        # Act
        result = await self.session._handle_list_roots(self.roots_request)

        # Assert
        assert result == mock_result
        self.session.roots.handle_list_roots.assert_awaited_once()

    async def test_returns_error_when_roots_capability_not_advertised(self):
        """Test that roots requests return METHOD_NOT_FOUND when capability missing."""
        # Arrange
        self.config.capabilities.roots = None
        self.session = ClientSession(self.transport, self.config)

        # Act
        result = await self.session._handle_list_roots(self.roots_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert "does not support roots capability" in result.message
