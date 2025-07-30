"""
OAuth 2.1 client for MCP server authentication.

Provides a simple, Pythonic interface for authenticating with MCP servers
that require OAuth 2.1 authorization following the MCP authorization specification.
"""

from __future__ import annotations

from typing import Protocol

import httpx


class TokenStorage(Protocol):
    """Protocol for token storage implementations."""

    async def get_tokens(self) -> dict[str, str] | None:
        """Get stored tokens for the server."""
        ...

    async def set_tokens(self, tokens: dict[str, str]) -> None:
        """Store tokens for the server."""
        ...

    async def clear_tokens(self) -> None:
        """Clear stored tokens."""
        ...


class AuthHandler(Protocol):
    """Protocol for handling user authorization flow."""

    async def handle_authorization(self, auth_url: str) -> tuple[str, str | None]:
        """
        Handle user authorization.

        Args:
            auth_url: The authorization URL to present to the user

        Returns:
            Tuple of (authorization_code, state) from the callback
        """
        ...


class MCPOAuthClient:
    """
    OAuth 2.1 client for MCP servers.

    Handles the complete OAuth flow including:
    - Server discovery (RFC 9728, RFC 8414)
    - Dynamic client registration (RFC 7591)
    - PKCE authorization flow (OAuth 2.1)
    - Token management and refresh

    Example:
        ```python
        oauth_client = MCPOAuthClient("https://api.example.com/mcp")
        http_client = await oauth_client.get_authenticated_http_client()

        # Use the authenticated client for MCP requests
        response = await http_client.post("/mcp", json=mcp_request)
        ```
    """

    def __init__(
        self,
        server_url: str,
        *,
        client_name: str = "Conduit MCP Client",
        storage: TokenStorage | None = None,
        auth_handler: AuthHandler | None = None,
        timeout: float = 300.0,
    ) -> None:
        """
        Initialize OAuth client for an MCP server.

        Args:
            server_url: The MCP server URL to authenticate with
            client_name: Name for dynamic client registration
            storage: Token storage implementation (defaults to file-based)
            auth_handler: Authorization handler (defaults to browser-based)
            timeout: Timeout for the authorization flow in seconds
        """
        self.server_url = server_url
        self.client_name = client_name
        self.timeout = timeout

        # Use defaults if not provided
        self.storage = storage or self._default_storage()
        self.auth_handler = auth_handler or self._default_auth_handler()

    async def get_authenticated_http_client(self) -> httpx.AsyncClient:
        """
        Get an authenticated HTTP client for the MCP server.

        This method handles the complete OAuth flow if needed:
        1. Check for valid cached tokens
        2. Attempt token refresh if expired
        3. Perform full OAuth flow if no valid tokens

        Returns:
            An httpx.AsyncClient configured with OAuth authentication

        Raises:
            OAuthError: If authentication fails
        """
        await self._ensure_authenticated()
        return httpx.AsyncClient(auth=self._create_auth_provider())

    async def clear_authentication(self) -> None:
        """Clear stored authentication data."""
        await self.storage.clear_tokens()

    def _default_storage(self) -> TokenStorage:
        """Create default file-based token storage."""
        # TODO: Implement FileTokenStorage
        raise NotImplementedError("Default storage not yet implemented")

    def _default_auth_handler(self) -> AuthHandler:
        """Create default browser-based auth handler."""
        # TODO: Implement BrowserAuthHandler
        raise NotImplementedError("Default auth handler not yet implemented")

    async def _ensure_authenticated(self) -> None:
        """Ensure we have valid authentication."""
        # TODO: Implement OAuth flow
        raise NotImplementedError("OAuth flow not yet implemented")

    def _create_auth_provider(self) -> httpx.Auth:
        """Create httpx auth provider with current tokens."""
        # TODO: Implement token-based auth provider
        raise NotImplementedError("Auth provider not yet implemented")


class OAuthError(Exception):
    """Base exception for OAuth-related errors."""

    pass


class AuthenticationError(OAuthError):
    """Raised when authentication fails."""

    pass


class TokenError(OAuthError):
    """Raised when token operations fail."""

    pass
