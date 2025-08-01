"""Token state and lifecycle models for OAuth 2.1.

Contains mutable token state management and token response handling.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


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


@dataclass(frozen=True)
class TokenRequest:
    """OAuth 2.1 token exchange request parameters (RFC 6749 Section 4.1.3).

    Immutable request parameters for exchanging authorization codes for access tokens.
    Includes PKCE code_verifier (RFC 7636) and resource parameter (RFC 8707).
    """

    # Required fields first
    token_endpoint: str
    code: str
    redirect_uri: str
    client_id: str
    code_verifier: str  # RFC 7636 PKCE

    # Optional fields with defaults last
    grant_type: str = "authorization_code"
    resource: str | None = None  # RFC 8707 Resource Indicators
    scope: str | None = None

    def to_form_data(self) -> dict[str, str]:
        """Convert to form data for application/x-www-form-urlencoded request.

        Token requests must use form encoding, not JSON (RFC 6749 Section 4.1.3).

        Returns:
            Dictionary suitable for httpx data parameter
        """
        data = {
            "grant_type": self.grant_type,
            "code": self.code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": self.code_verifier,
        }

        # Add optional parameters
        if self.resource:
            data["resource"] = self.resource
        if self.scope:
            data["scope"] = self.scope

        return data


class TokenResponse(BaseModel):
    """OAuth 2.1 token response (RFC 6749 Section 5).

    Represents the response from a token endpoint, including both
    successful responses (Section 5.1) and error responses (Section 5.2).
    """

    # Success response fields (RFC 6749 Section 5.1)
    access_token: str | None = None
    token_type: str = "Bearer"
    expires_in: int | None = None  # Seconds until expiry
    refresh_token: str | None = None
    scope: str | None = None

    # Error response fields (RFC 6749 Section 5.2)
    error: str | None = None
    error_description: str | None = None
    error_uri: str | None = None

    def is_success(self) -> bool:
        """Check if token response indicates success."""
        return self.error is None and self.access_token is not None

    def is_error(self) -> bool:
        """Check if token response indicates an error."""
        return self.error is not None

    def calculate_expires_at(self) -> float | None:
        """Calculate absolute expiry timestamp from expires_in.

        Returns:
            Unix timestamp when token expires, or None if no expiry
        """
        if self.expires_in is None:
            return None
        return time.time() + self.expires_in

    def to_token_state(self) -> TokenState:
        """Convert successful token response to mutable TokenState.

        Returns:
            TokenState for ongoing token management

        Raises:
            ValueError: If response is not successful
        """
        if not self.is_success():
            raise ValueError("Cannot convert error response to TokenState")

        return TokenState(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            token_type=self.token_type,
            expires_at=self.calculate_expires_at(),
            scope=self.scope,
        )


@dataclass(frozen=True)
class RefreshTokenRequest:
    """OAuth 2.1 refresh token request parameters (RFC 6749 Section 6).

    Immutable request parameters for refreshing access tokens.
    """

    # Required fields first
    token_endpoint: str
    refresh_token: str
    client_id: str

    # Optional fields with defaults last
    grant_type: str = "refresh_token"
    resource: str | None = None  # RFC 8707 Resource Indicators
    scope: str | None = None

    def to_form_data(self) -> dict[str, str]:
        """Convert to form data for application/x-www-form-urlencoded request."""
        data = {
            "grant_type": self.grant_type,
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
        }

        if self.resource:
            data["resource"] = self.resource
        if self.scope:
            data["scope"] = self.scope

        return data
