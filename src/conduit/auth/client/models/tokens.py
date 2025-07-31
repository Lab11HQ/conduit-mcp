"""Token state and lifecycle models for OAuth 2.1.

Contains mutable token state management and token response handling.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class TokenState:
    """Mutable token state with lifecycle management.

    Represents the current state of OAuth tokens for a server.
    Mutable to allow token refresh without recreating the entire auth provider.
    """

    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "Bearer"
    expires_at: float | None = None  # Unix timestamp
    scope: str | None = None

    def is_valid(self, buffer_seconds: float = 30.0) -> bool:
        """Check if access token is valid with optional buffer.

        Args:
            buffer_seconds: Refresh token this many seconds before expiry
        """
        if not self.access_token:
            return False

        if self.expires_at is None:
            return True  # No expiry means token doesn't expire

        return time.time() < (self.expires_at - buffer_seconds)

    def can_refresh(self) -> bool:
        """Check if token can be refreshed."""
        return bool(self.refresh_token)

    def clear(self) -> None:
        """Clear all token data."""
        self.access_token = None
        self.refresh_token = None
        self.expires_at = None
        self.scope = None

    def update_from_response(self, token_response: dict[str, Any]) -> None:
        """Update token state from OAuth token response."""
        self.access_token = token_response.get("access_token")
        self.token_type = token_response.get("token_type", "Bearer")
        self.scope = token_response.get("scope")

        # Update refresh token if provided
        if "refresh_token" in token_response:
            self.refresh_token = token_response["refresh_token"]

        # Calculate expiry time
        if "expires_in" in token_response:
            expires_in = int(token_response["expires_in"])
            self.expires_at = time.time() + expires_in
        else:
            self.expires_at = None
