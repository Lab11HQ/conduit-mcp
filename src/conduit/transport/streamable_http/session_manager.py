"""Session management for streamable HTTP transport."""

import logging
import secrets
import uuid

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages client sessions and their lifecycle.

    Always assigns session IDs to simplify the protocol implementation.
    Maintains bidirectional mapping between sessions and clients.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, str] = {}  # session_id -> client_id
        self._client_sessions: dict[str, str] = {}  # client_id -> session_id

    def create_session(self) -> tuple[str, str]:
        """Create a new session and client ID pair.

        Returns:
            Tuple of (client_id, session_id)
        """
        client_id = str(uuid.uuid4())
        session_id = self._generate_session_id()

        self._sessions[session_id] = client_id
        self._client_sessions[client_id] = session_id

        logger.debug(f"Created session {session_id} for client {client_id}")
        return client_id, session_id

    def get_client_id(self, session_id: str) -> str | None:
        """Get client ID for a session.

        Returns None if session doesn't exist.
        """
        return self._sessions.get(session_id)

    def get_session_id(self, client_id: str) -> str | None:
        """Get session ID for a client.

        Returns None if client doesn't have a session.
        """
        return self._client_sessions.get(client_id)

    def session_exists(self, session_id: str) -> bool:
        """Check if session exists."""
        return session_id in self._sessions

    def terminate_session(self, session_id: str) -> str | None:
        """Terminate a session.

        Returns the client_id that was terminated, or None if session didn't exist.
        """
        if session_id not in self._sessions:
            return None

        client_id = self._sessions[session_id]
        del self._sessions[session_id]
        del self._client_sessions[client_id]

        logger.debug(f"Terminated session {session_id} for client {client_id}")
        return client_id

    def _generate_session_id(self) -> str:
        """Generate cryptographically secure session ID."""
        return secrets.token_urlsafe(32)

    def terminate_all_sessions(self) -> None:
        """Terminate all sessions."""
        for session_id in list(self._sessions):
            self.terminate_session(session_id)
