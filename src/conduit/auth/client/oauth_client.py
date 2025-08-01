"""Complete OAuth 2.1 client orchestration for MCP authentication.

Coordinates discovery, registration, authorization, and token exchange
to provide a complete OAuth authentication flow.
"""

from __future__ import annotations

import logging
from typing import Protocol

from conduit.auth.client.models.discovery import DiscoveryResult
from conduit.auth.client.models.registration import ClientMetadata, ClientRegistration
from conduit.auth.client.models.tokens import TokenRequest, TokenState
from conduit.auth.client.services.discovery import OAuth2Discovery
from conduit.auth.client.services.flow import OAuth2FlowManager
from conduit.auth.client.services.registration import OAuth2Registration
from conduit.auth.client.services.tokens import OAuth2TokenManager

logger = logging.getLogger(__name__)


class AuthorizationHandler(Protocol):
    """Protocol for handling user authorization step.

    Allows different strategies for browser interaction:
    - Manual (return URL to developer)
    - Browser automation (open browser + local server)
    - Custom UI integration
    """

    async def handle_authorization(self, auth_url: str) -> str:
        """Handle user authorization and return callback URL.

        Args:
            auth_url: Authorization URL for user to visit

        Returns:
            Callback URL received after user authorization
        """
        ...


class ManualAuthorizationHandler:
    """Authorization handler that requires manual user interaction.

    Returns the authorization URL and waits for developer to provide
    the callback URL. Suitable for CLI tools and custom integrations.
    """

    def __init__(self, callback_handler: callable[[str], str] | None = None):
        """Initialize manual authorization handler.

        Args:
            callback_handler: Optional function to call with auth URL.
                             Should return the callback URL.
        """
        self.callback_handler = callback_handler

    async def handle_authorization(self, auth_url: str) -> str:
        """Handle authorization by delegating to callback handler or raising."""
        if self.callback_handler:
            return await self.callback_handler(auth_url)
        else:
            raise NotImplementedError(
                f"Please visit {auth_url} and provide the callback URL"
            )


class AuthenticatedSession:
    """Represents an authenticated session with an MCP server.

    Manages token lifecycle including automatic refresh when needed.
    """

    def __init__(
        self,
        server_url: str,
        token_state: TokenState,
        token_manager: OAuth2TokenManager,
        discovery_result: DiscoveryResult,
        client_registration: ClientRegistration,
    ):
        self.server_url = server_url
        self.token_state = token_state
        self._token_manager = token_manager
        self._discovery_result = discovery_result
        self._client_registration = client_registration

    @property
    def access_token(self) -> str | None:
        """Get current access token."""
        return self.token_state.access_token

    @property
    def is_valid(self) -> bool:
        """Check if session has valid access token."""
        return self.token_state.is_valid()

    async def refresh_if_needed(self) -> bool:
        """Refresh access token if needed and possible.

        Returns:
            True if token was refreshed or is still valid, False if refresh failed
        """
        if self.token_state.is_valid():
            return True

        if not self.token_state.can_refresh():
            logger.warning("Token expired and cannot be refreshed")
            return False

        try:
            # Attempt token refresh
            from conduit.auth.client.models.tokens import RefreshTokenRequest

            refresh_request = RefreshTokenRequest(
                token_endpoint=self._discovery_result.authorization_server_metadata.token_endpoint,
                refresh_token=self.token_state.refresh_token,
                client_id=self._client_registration.credentials.client_id,
                resource=self._discovery_result.get_resource_url(),
            )

            token_response = await self._token_manager.refresh_access_token(
                refresh_request
            )

            if token_response.is_success():
                # Update token state with new tokens
                new_token_state = token_response.to_token_state()
                self.token_state.access_token = new_token_state.access_token
                self.token_state.refresh_token = (
                    new_token_state.refresh_token or self.token_state.refresh_token
                )
                self.token_state.expires_at = new_token_state.expires_at
                self.token_state.scope = new_token_state.scope

                logger.info("Successfully refreshed access token")
                return True
            else:
                logger.error(f"Token refresh failed: {token_response.error}")
                return False

        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            return False


class OAuth2Client:
    """Complete OAuth 2.1 client for MCP authentication.

    Orchestrates the full OAuth flow from discovery through token exchange,
    providing a high-level interface for MCP client authentication.
    """

    def __init__(
        self,
        authorization_handler: AuthorizationHandler | None = None,
        redirect_uri: str = "http://localhost:8080/callback",
        client_name: str = "MCP Client",
        timeout: float = 30.0,
    ):
        """Initialize OAuth client.

        Args:
            authorization_handler: Handler for user authorization step
            redirect_uri: OAuth redirect URI for callbacks
            client_name: Name to use for dynamic client registration
            timeout: HTTP request timeout
        """
        self.authorization_handler = (
            authorization_handler or ManualAuthorizationHandler()
        )
        self.redirect_uri = redirect_uri
        self.client_name = client_name

        # Initialize service components
        self.discovery = OAuth2Discovery(timeout=timeout)
        self.registration = OAuth2Registration(timeout=timeout)
        self.flow_manager = OAuth2FlowManager()
        self.token_manager = OAuth2TokenManager(timeout=timeout)

    async def authenticate_with_server(
        self,
        server_url: str,
        scope: str | None = None,
        client_metadata: ClientMetadata | None = None,
    ) -> AuthenticatedSession:
        """Authenticate with an MCP server using OAuth 2.1.

        Performs the complete OAuth flow:
        1. Discover OAuth configuration
        2. Register client dynamically
        3. Handle authorization flow
        4. Exchange code for tokens
        5. Return authenticated session

        Args:
            server_url: MCP server URL to authenticate with
            scope: Optional OAuth scope to request
            client_metadata: Optional custom client metadata

        Returns:
            AuthenticatedSession: Session with valid access tokens

        Raises:
            Various OAuth errors if authentication fails
        """
        logger.info(f"Starting OAuth authentication with {server_url}")

        # 1. Discover OAuth configuration
        logger.debug("Discovering OAuth configuration")
        discovery_result = await self.discovery.discover_from_url(server_url)

        # 2. Register client (if registration endpoint available)
        logger.debug("Registering OAuth client")
        client_reg = await self._register_client(discovery_result, client_metadata)

        # 3. Start authorization flow
        logger.debug("Starting authorization flow")
        auth_url, pkce_params, state = await self.flow_manager.start_authorization_flow(
            discovery_result, client_reg.credentials, self.redirect_uri, scope
        )

        # 4. Handle user authorization
        logger.debug("Handling user authorization")
        callback_url = await self.authorization_handler.handle_authorization(auth_url)

        # 5. Process callback
        logger.debug("Processing authorization callback")
        auth_response = await self.flow_manager.handle_authorization_callback(
            callback_url, state
        )

        if not auth_response.is_success():
            raise ValueError(f"Authorization failed: {auth_response.error}")

        # 6. Exchange code for tokens
        logger.debug("Exchanging authorization code for tokens")

        token_request = TokenRequest(
            token_endpoint=discovery_result.authorization_server_metadata.token_endpoint,
            code=auth_response.code,
            redirect_uri=self.redirect_uri,
            client_id=client_reg.credentials.client_id,
            code_verifier=pkce_params.code_verifier,
            resource=discovery_result.get_resource_url(),
            scope=scope,
        )

        token_response = await self.token_manager.exchange_code_for_token(token_request)

        if not token_response.is_success():
            raise ValueError(f"Token exchange failed: {token_response.error}")

        # 7. Create authenticated session
        token_state = token_response.to_token_state()
        session = AuthenticatedSession(
            server_url, token_state, self.token_manager, discovery_result, client_reg
        )

        logger.info(f"Successfully authenticated with {server_url}")
        return session

    async def _register_client(
        self,
        discovery_result: DiscoveryResult,
        client_metadata: ClientMetadata | None = None,
    ) -> ClientRegistration:
        """Register OAuth client with authorization server."""
        if not discovery_result.authorization_server_metadata.registration_endpoint:
            raise ValueError("Server does not support dynamic client registration")

        if client_metadata is None:
            client_metadata = ClientMetadata(
                client_name=self.client_name,
                redirect_uris=[self.redirect_uri],
            )

        return await self.registration.register_client(
            discovery_result.authorization_server_metadata.registration_endpoint,
            client_metadata,
        )

    async def close(self) -> None:
        """Close all service connections."""
        await self.discovery.close()
        await self.registration.close()
        await self.token_manager.close()
