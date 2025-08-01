"""Discovery-related models for OAuth 2.1 server metadata.

Contains models for Protected Resource Metadata (RFC 9728) and
Authorization Server Metadata (RFC 8414) discovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class ProtectedResourceMetadata(BaseModel):
    """OAuth 2.0 Protected Resource Metadata (RFC 9728).

    Metadata returned by MCP servers to indicate their authorization servers
    and resource configuration.
    """

    resource: str | None = None
    authorization_servers: list[str] = Field(min_length=1)

    # Optional fields from RFC 9728
    bearer_methods_supported: list[str] | None = None
    resource_documentation: str | None = None
    resource_policy_uri: str | None = None
    resource_tos_uri: str | None = None

    @field_validator("authorization_servers")
    @classmethod
    def validate_auth_servers(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("At least one authorization server is required")
        return v


class AuthorizationServerMetadata(BaseModel):
    """OAuth 2.0 Authorization Server Metadata (RFC 8414).

    Metadata returned by authorization servers describing their endpoints
    and supported capabilities.
    """

    # Required by RFC 8414
    issuer: str
    response_types_supported: list[str] = Field(min_length=1)

    # Required for authorization code flow (our use case)
    authorization_endpoint: str
    token_endpoint: str

    # PKCE support (required for OAuth 2.1)
    code_challenge_methods_supported: list[str] = Field(default=["S256"])

    # Dynamic registration (RFC 7591)
    registration_endpoint: str | None = None

    # Optional but commonly used
    revocation_endpoint: str | None = None
    introspection_endpoint: str | None = None
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

    def get_resource_url(self) -> str:
        """Get the resource URL for RFC 8707 resource parameter.

        Uses the most specific URI (the actual server URL) as per MCP spec
        guidance to provide the most specific URI possible.
        """
        # Canonicalize the server URL per RFC 3986 and MCP spec
        parsed = urlparse(self.server_url)
        canonical = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        if parsed.path and parsed.path != "/":
            canonical += parsed.path.rstrip("/")  # Preserve case, remove trailing slash

        return canonical

    # TODO: Consider if we ever need PRM resource override
    # The spec is unclear about when to use PRM resource vs server URL
