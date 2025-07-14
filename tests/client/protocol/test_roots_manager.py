from conduit.client.protocol.roots import RootsManager
from conduit.protocol.roots import ListRootsRequest, ListRootsResult, Root


class TestRootsManager:
    def test_add_root_appends_to_roots(self):
        # Arrange
        manager = RootsManager()
        root = Root(uri="file:///test")

        # Act
        manager.add_root(root)

        # Assert
        assert manager.roots == [root]

    def test_remove_root_removes_from_roots(self):
        # Arrange
        manager = RootsManager()
        root = Root(uri="file:///test")
        manager.add_root(root)

        # Act
        result = manager.remove_root("file:///test")

        # Assert
        assert result == True
        assert manager.roots == []

    def test_remove_root_returns_false_if_root_not_found(self):
        # Arrange
        manager = RootsManager()

        # Act
        result = manager.remove_root("file://not-found")

        # Assert
        assert result == False
        assert manager.roots == []

    def test_clear_roots_removes_all_roots(self):
        # Arrange
        manager = RootsManager()
        root = Root(uri="file:///test")
        manager.add_root(root)

        # Act
        manager.clear_roots()

        # Assert
        assert manager.roots == []

    def test_clear_roots_does_not_raise_if_no_roots(self):
        # Arrange
        manager = RootsManager()

        # Act
        manager.clear_roots()

        # Assert
        assert manager.roots == []

    async def test_handle_list_roots_returns_empty_list_if_no_roots(self):
        # Arrange
        manager = RootsManager()

        # Act
        result = await manager.handle_list_roots(ListRootsRequest())

        # Assert
        assert result == ListRootsResult(roots=[])

    async def test_handle_list_roots_returns_roots(self):
        # Arrange
        manager = RootsManager()
        root = Root(uri="file:///test")
        manager.add_root(root)

        # Act
        result = await manager.handle_list_roots(ListRootsRequest())

        # Assert
        assert result == ListRootsResult(roots=[root])
