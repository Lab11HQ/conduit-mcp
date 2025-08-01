"""Authorization flow models for OAuth 2.1.

Contains models for authorization requests and callback handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode


@dataclass(frozen=True)
class AuthorizationRequest:
    """Authorization request parameters for OAuth 2.1 flow."""

    authorization_endpoint: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str
    state: str
    resource: str | None = None  # RFC 8707
    scope: str | None = None

    def build_authorization_url(self) -> str:
        """Build the complete authorization URL."""
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "code_challenge": self.code_challenge,
            "code_challenge_method": self.code_challenge_method,
            "state": self.state,
        }

        if self.resource:
            params["resource"] = self.resource
        if self.scope:
            params["scope"] = self.scope

        return f"{self.authorization_endpoint}?{urlencode(params)}"


@dataclass(frozen=True)
class AuthorizationResponse:
    code: str | None = None
    state: str | None = None
    error: str | None = None
    error_description: str | None = None
    error_uri: str | None = None

    def is_success(self) -> bool:
        return self.error is None and self.code is not None

    def is_error(self) -> bool:
        return self.error is not None
