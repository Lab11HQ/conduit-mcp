"""Client registration models for OAuth 2.0 Dynamic Client Registration.

Contains models for client metadata (RFC 7591) and registration results.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class ClientMetadata(BaseModel):
    """OAuth 2.0 Client Metadata for dynamic registration (RFC 7591)."""

    client_name: str
    redirect_uris: list[str] = Field(min_length=1)

    # Optional metadata
    client_uri: str | None = None
    logo_uri: str | None = None
    scope: str | None = None
    contacts: list[str] | None = None
    tos_uri: str | None = None
    policy_uri: str | None = None

    # OAuth 2.1 specific
    token_endpoint_auth_method: str = "none"  # Public client
    grant_types: list[str] = Field(default=["authorization_code"])
    response_types: list[str] = Field(default=["code"])

    @field_validator("redirect_uris")
    @classmethod
    def validate_redirect_uris(cls, v: list[str]) -> list[str]:
        """Validate redirect URIs meet OAuth 2.1 security requirements."""
        for uri in v:
            parsed = urlparse(uri)
            # Must be HTTPS or localhost
            if parsed.scheme == "http" and parsed.hostname != "localhost":
                raise ValueError(f"Redirect URI must use HTTPS or localhost: {uri}")
        return v

    @field_validator("client_uri", "logo_uri", "tos_uri", "policy_uri")
    @classmethod
    def validate_https_uris(cls, v: str | None) -> str | None:
        """Validate optional URIs use HTTPS when provided."""
        if v is not None and not v.startswith("https://"):
            raise ValueError(f"URI must use HTTPS: {v}")
        return v


class ClientCredentials(BaseModel):
    """OAuth 2.0 Client Credentials from registration response."""

    client_id: str
    client_secret: str | None = None  # None for public clients
    registration_access_token: str | None = None
    registration_client_uri: str | None = None
    client_id_issued_at: int | None = None
    client_secret_expires_at: int | None = None

    def is_expired(self) -> bool:
        """Check if client credentials have expired."""
        if self.client_secret_expires_at is None:
            return False
        return time.time() >= self.client_secret_expires_at


@dataclass(frozen=True)
class ClientRegistration:
    """Complete client registration result.

    Immutable result containing client metadata and credentials.
    """

    metadata: ClientMetadata
    credentials: ClientCredentials
    registration_endpoint: str
