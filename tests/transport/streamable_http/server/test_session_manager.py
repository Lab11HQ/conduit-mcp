import uuid

from conduit.transport.streamable_http.server.session_manager import SessionManager


class TestSessionManager:
    def test_empty_manager_state(self):
        # Arrange
        manager = SessionManager()
        fake_id = str(uuid.uuid4())

        # Act & Assert
        assert manager.get_client_id(fake_id) is None
        assert manager.get_session_id(fake_id) is None
        assert manager.session_exists(fake_id) is False
        assert manager.terminate_session(fake_id) is False

        # Should not raise errors
        manager.terminate_all_sessions()

    def test_create_session_happy_path(self):
        # Arrange
        manager = SessionManager()

        # Act
        client_id, session_id = manager.create_session()

        # Assert
        assert client_id is not None
        assert session_id is not None
        assert isinstance(client_id, str)
        assert isinstance(session_id, str)

        # Verify both IDs are valid UUIDs
        uuid.UUID(client_id)  # Will raise ValueError if invalid
        uuid.UUID(session_id)  # Will raise ValueError if invalid

        # Verify bidirectional lookup works
        assert manager.get_client_id(session_id) == client_id
        assert manager.get_session_id(client_id) == session_id
        assert manager.session_exists(session_id) is True

    def test_create_multiple_sessions(self):
        # Arrange
        manager = SessionManager()

        # Act
        client_id1, session_id1 = manager.create_session()
        client_id2, session_id2 = manager.create_session()
        client_id3, session_id3 = manager.create_session()

        # Assert
        # All IDs should be unique
        assert client_id1 != client_id2 != client_id3
        assert session_id1 != session_id2 != session_id3

        # All sessions should exist and map correctly
        assert manager.get_client_id(session_id1) == client_id1
        assert manager.get_client_id(session_id2) == client_id2
        assert manager.get_client_id(session_id3) == client_id3

        assert manager.get_session_id(client_id1) == session_id1
        assert manager.get_session_id(client_id2) == session_id2
        assert manager.get_session_id(client_id3) == session_id3

    def test_get_session_id(self):
        # Arrange
        manager = SessionManager()
        client_id, session_id = manager.create_session()
        fake_client_id = str(uuid.uuid4())

        # Act
        real_session = manager.get_session_id(client_id)
        fake_session = manager.get_session_id(fake_client_id)

        # Assert
        assert real_session == session_id
        assert fake_session is None

    def test_session_exists(self):
        # Arrange
        manager = SessionManager()
        _, session_id = manager.create_session()

        # Act
        real_session = manager.session_exists(session_id)
        fake_session = manager.session_exists(str(uuid.uuid4()))

        # Assert
        assert real_session is True
        assert fake_session is False

    def test_terminate_session_existing(self):
        # Arrange
        manager = SessionManager()
        client_id, session_id = manager.create_session()

        # Act
        result = manager.terminate_session(session_id)

        # Assert
        assert result is True
        assert manager.session_exists(session_id) is False
        assert manager.get_client_id(session_id) is None
        assert manager.get_session_id(client_id) is None

    def test_terminate_session_nonexistent(self):
        # Arrange
        manager = SessionManager()
        fake_session_id = str(uuid.uuid4())

        # Act
        result = manager.terminate_session(fake_session_id)

        # Assert: should return False
        assert result is False

    def test_terminate_session_leaves_others_intact(self):
        # Arrange
        manager = SessionManager()
        client_id1, session_id1 = manager.create_session()
        client_id2, session_id2 = manager.create_session()
        client_id3, session_id3 = manager.create_session()

        # Act
        result = manager.terminate_session(session_id2)

        # Assert
        assert result is True

        # Session 2 should be gone
        assert manager.session_exists(session_id2) is False
        assert manager.get_client_id(session_id2) is None
        assert manager.get_session_id(client_id2) is None

        # Sessions 1 and 3 should remain
        assert manager.session_exists(session_id1) is True
        assert manager.session_exists(session_id3) is True
        assert manager.get_client_id(session_id1) == client_id1
        assert manager.get_client_id(session_id3) == client_id3
        assert manager.get_session_id(client_id1) == session_id1
        assert manager.get_session_id(client_id3) == session_id3

    def test_terminate_all_sessions_empty_manager(self):
        # Arrange
        manager = SessionManager()

        # Act
        manager.terminate_all_sessions()

        # Assert
        # Should not raise any errors
        assert True

    def test_terminate_all_sessions_with_sessions(self):
        # Arrange
        manager = SessionManager()
        client_id1, session_id1 = manager.create_session()
        client_id2, session_id2 = manager.create_session()
        client_id3, session_id3 = manager.create_session()

        # Act
        manager.terminate_all_sessions()

        # Assert
        assert manager.session_exists(session_id1) is False
        assert manager.session_exists(session_id2) is False
        assert manager.session_exists(session_id3) is False

        assert manager.get_client_id(session_id1) is None
        assert manager.get_client_id(session_id2) is None
        assert manager.get_client_id(session_id3) is None

        assert manager.get_session_id(client_id1) is None
        assert manager.get_session_id(client_id2) is None
        assert manager.get_session_id(client_id3) is None
