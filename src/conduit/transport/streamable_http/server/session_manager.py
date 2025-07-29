"""Session management for streamable HTTP transport."""

import logging
import uuid

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages client sessions and their lifecycle.

    Maintains a simple mapping from session IDs to client IDs.
    Session IDs are UUIDs that comply with the MCP streamable HTTP spec.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, str] = {}  # session_id -> client_id

    # ================================
    # Creation
    # ================================

    def create_session(self) -> tuple[str, str]:
        """Create a new session and client ID pair.

        Returns:
            Tuple of (client_id, session_id)
        """
        client_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        self._sessions[session_id] = client_id

        logger.debug(f"Created session {session_id} for client {client_id}")
        return client_id, session_id

    # ================================
    # Access
    # ================================

    def get_client_id(self, session_id: str) -> str | None:
        """Get client ID for a session.

        Returns None if session doesn't exist.
        """
        return self._sessions.get(session_id)

    def get_session_id(self, client_id: str) -> str | None:
        """Get session ID for a client.

        Returns None if client doesn't have a session.
        """
        for session_id, stored_client_id in self._sessions.items():
            if stored_client_id == client_id:
                return session_id
        return None

    # ================================
    # Existence
    # ================================

    def session_exists(self, session_id: str) -> bool:
        """Check if session exists."""
        return session_id in self._sessions

    # ================================
    # Termination
    # ================================

    def terminate_session(self, session_id: str) -> bool:
        """Terminate a session.

        Returns True if session existed and was terminated, False otherwise.
        """
        client_id = self._sessions.pop(session_id, None)
        if client_id is not None:
            logger.debug(f"Terminated session {session_id} for client {client_id}")
            return True
        return False

    def terminate_all_sessions(self) -> None:
        """Terminate all sessions."""
        self._sessions.clear()
        logger.debug("Terminated all sessions")
