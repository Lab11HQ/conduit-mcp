"""Discovery-related models for OAuth 2.1 server metadata.

Contains models for Protected Resource Metadata (RFC 9728) and
Authorization Server Metadata (RFC 8414) discovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from pydantic import BaseModel, Field, HttpUrl, field_validator


class ProtectedResourceMetadata(BaseModel):
    """OAuth 2.0 Protected Resource Metadata (RFC 9728).

    Metadata returned by MCP servers to indicate their authorization servers
    and resource configuration.
    """

    resource: HttpUrl | None = None
    authorization_servers: list[HttpUrl] = Field(min_length=1)

    # Optional fields from RFC 9728
    bearer_methods_supported: list[str] | None = None
    resource_documentation: HttpUrl | None = None
    resource_policy_uri: HttpUrl | None = None
    resource_tos_uri: HttpUrl | None = None

    @field_validator("authorization_servers")
    @classmethod
    def validate_auth_servers(cls, v: list[HttpUrl]) -> list[HttpUrl]:
        if not v:
            raise ValueError("At least one authorization server is required")
        return v


class AuthorizationServerMetadata(BaseModel):
    """OAuth 2.0 Authorization Server Metadata (RFC 8414).

    Metadata returned by authorization servers describing their endpoints
    and supported capabilities.
    """

    # Required fields
    issuer: HttpUrl
    authorization_endpoint: HttpUrl
    token_endpoint: HttpUrl
    response_types_supported: list[str] = Field(min_length=1)

    # PKCE support (required for OAuth 2.1)
    code_challenge_methods_supported: list[str] = Field(default=["S256"])

    # Dynamic registration (RFC 7591)
    registration_endpoint: HttpUrl | None = None

    # Optional but commonly used
    revocation_endpoint: HttpUrl | None = None
    introspection_endpoint: HttpUrl | None = None
    scopes_supported: list[str] | None = None
    grant_types_supported: list[str] = Field(default=["authorization_code"])

    @field_validator("code_challenge_methods_supported")
    @classmethod
    def validate_pkce_support(cls, v: list[str]) -> list[str]:
        if "S256" not in v:
            raise ValueError("Authorization server must support S256 PKCE method")
        return v


@dataclass(frozen=True)
class DiscoveryResult:
    """Complete discovery results for an MCP server.

    Immutable result containing all metadata needed for OAuth flow.
    Combines Protected Resource Metadata and Authorization Server Metadata.
    """

    server_url: str
    protected_resource_metadata: ProtectedResourceMetadata
    authorization_server_metadata: AuthorizationServerMetadata
    auth_server_url: str
    protocol_version: str | None = None

    def get_resource_url(self) -> str:
        """Get the resource URL for RFC 8707 resource parameter.

        Uses Protected Resource Metadata resource if available and valid,
        otherwise derives canonical URL from server_url.
        """
        # Start with canonical server URL
        parsed = urlparse(self.server_url)
        canonical = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        if parsed.path and parsed.path != "/":
            canonical += parsed.path.rstrip("/")

        # Use PRM resource if it's a valid parent of our server URL
        if self.protected_resource_metadata.resource:
            prm_resource = str(self.protected_resource_metadata.resource)
            if canonical.startswith(prm_resource):
                return prm_resource

        return canonical

    def should_include_resource_param(self) -> bool:
        """Determine if resource parameter should be included in OAuth requests.

        Returns True if we have Protected Resource Metadata or if the
        protocol version is 2025-06-18 or later.
        """
        # Always include if we discovered PRM
        if self.protected_resource_metadata:
            return True

        # Include for newer protocol versions
        if self.protocol_version and self.protocol_version >= "2025-06-18":
            return True

        return False
