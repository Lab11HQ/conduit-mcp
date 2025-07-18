from conduit.client.protocol.roots import RootsManager
from conduit.protocol.roots import ListRootsRequest, ListRootsResult, Root


class TestRootsManager:
    def test_add_root_appends_to_global_roots(self):
        # Arrange
        manager = RootsManager()
        root = Root(uri="file:///test")

        # Act
        manager.add_root(root)

        # Assert
        assert manager.get_global_roots() == [root]

    def test_remove_root_removes_from_global_roots(self):
        # Arrange
        manager = RootsManager()
        root = Root(uri="file:///test")
        manager.add_root(root)

        # Act
        result = manager.remove_root("file:///test")

        # Assert
        assert result == True
        assert manager.get_global_roots() == []

    def test_remove_root_returns_false_if_root_not_found(self):
        # Arrange
        manager = RootsManager()

        # Act
        result = manager.remove_root("file://not-found")

        # Assert
        assert result == False
        assert manager.get_global_roots() == []

    def test_clear_roots_removes_all_roots(self):
        # Arrange
        manager = RootsManager()
        root = Root(uri="file:///test")
        manager.add_root(root)

        # Act
        manager.clear_roots()

        # Assert
        assert manager.get_global_roots() == []

    def test_clear_roots_does_not_raise_if_no_roots(self):
        # Arrange
        manager = RootsManager()

        # Act
        manager.clear_roots()

        # Assert
        assert manager.get_global_roots() == []

    async def test_handle_list_roots_returns_empty_list_if_no_roots(self):
        # Arrange
        manager = RootsManager()

        # Act
        result = await manager.handle_list_roots("server_id", ListRootsRequest())

        # Assert
        assert result == ListRootsResult(roots=[])

    def test_add_root_to_server_appends_to_server_roots(self):
        # Arrange
        manager = RootsManager()
        root = Root(uri="file:///test")

        # Act
        manager.add_root_to_server("server_id", root)

        # Assert
        assert manager.get_roots_for_server("server_id") == [root]

    def test_get_roots_for_server_returns_server_specific_and_global_roots(self):
        # Arrange
        manager = RootsManager()
        server_specific_root = Root(uri="file:///server_specific")
        global_root = Root(uri="file:///global")
        manager.add_root_to_server("server_id", server_specific_root)
        manager.add_root(global_root)

        # Act
        result = manager.get_roots_for_server("server_id")

        # Assert
        assert len(result) == 2
        assert server_specific_root in result
        assert global_root in result

    def test_get_server_specific_roots_returns_only_server_specific_roots(self):
        # Arrange
        manager = RootsManager()
        server_specific_root = Root(uri="file:///server_specific")
        global_root = Root(uri="file:///global")
        manager.add_root(global_root)
        manager.add_root_to_server("server_id", server_specific_root)

        # Act
        result = manager.get_server_specific_roots("server_id")

        # Assert
        assert result == [server_specific_root]

    def test_cleanup_server_removes_server_specific_roots(self):
        # Arrange
        manager = RootsManager()
        server_specific_root = Root(uri="file:///server_specific")
        manager.add_root_to_server("server_id", server_specific_root)

        # Act
        manager.cleanup_server("server_id")

        # Assert
        assert manager.get_roots_for_server("server_id") == []
        assert manager.get_server_specific_roots("server_id") == []

    def test_cleanup_server_does_not_remove_global_roots(self):
        # Arrange
        manager = RootsManager()
        server_specific_root = Root(uri="file:///server_specific")
        manager.add_root_to_server("server_id", server_specific_root)
        global_root = Root(uri="file:///global")
        manager.add_root(global_root)

        # Act
        manager.cleanup_server("server_id")

        # Assert
        assert manager.get_global_roots() == [global_root]
        assert manager.get_roots_for_server("server_id") == [global_root]
        assert manager.get_server_specific_roots("server_id") == []
