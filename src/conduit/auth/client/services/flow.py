"""OAuth 2.1 authorization flow orchestration service.

Coordinates the complete authorization code flow including PKCE security,
state validation, and callback handling for MCP client authentication.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

from conduit.auth.client.models.discovery import DiscoveryResult
from conduit.auth.client.models.errors import (
    AuthorizationCallbackError,
    AuthorizationError,
    StateValidationError,
)
from conduit.auth.client.models.flow import AuthorizationRequest, AuthorizationResponse
from conduit.auth.client.models.registration import ClientCredentials
from conduit.auth.client.models.security import PKCEParameters
from conduit.auth.client.services.pkce import PKCEManager
from conduit.auth.client.services.security import generate_state, validate_state

logger = logging.getLogger(__name__)


class OAuth2FlowManager:
    """Orchestrates OAuth 2.1 authorization code flows for MCP authentication.

    Handles the complete authorization flow from initial request generation
    through callback processing, including:
    - PKCE parameter generation and validation
    - State parameter security (CSRF protection)
    - Authorization URL construction
    - Callback URL parsing and validation
    - Resource parameter handling (RFC 8707)
    """

    def __init__(self):
        """Initialize the OAuth flow manager."""
        self._pkce_manager = PKCEManager()

    async def start_authorization_flow(
        self,
        discovery_result: DiscoveryResult,
        client_credentials: ClientCredentials,
        redirect_uri: str,
        scope: str | None = None,
    ) -> tuple[str, PKCEParameters, str]:
        """Start an OAuth 2.1 authorization flow.

        Generates secure PKCE parameters and state, then builds the authorization
        URL that users should visit to grant permissions.

        Args:
            discovery_result: OAuth server discovery results
            client_credentials: Registered client credentials
            redirect_uri: URI to redirect to after authorization
            scope: Optional scope to request

        Returns:
            Tuple of (authorization_url, pkce_parameters, state)
            - authorization_url: URL for user to visit
            - pkce_parameters: Store these for token exchange
            - state: Store this for callback validation

        Raises:
            AuthorizationError: If flow setup fails
        """
        try:
            # Generate security parameters
            pkce_params = self._pkce_manager.generate_parameters()
            state = generate_state()

            # Get resource URL for RFC 8707
            resource_url = discovery_result.get_resource_url()

            logger.debug(
                f"Starting authorization flow for client"
                f"{client_credentials.client_id} with resource"
                f" {resource_url}"
            )

            # Build authorization request
            auth_endpoint = (
                discovery_result.authorization_server_metadata.authorization_endpoint
            )
            auth_request = AuthorizationRequest(
                authorization_endpoint=auth_endpoint,
                client_id=client_credentials.client_id,
                redirect_uri=redirect_uri,
                code_challenge=pkce_params.code_challenge,
                code_challenge_method=pkce_params.code_challenge_method,
                state=state,
                resource=resource_url,
                scope=scope,
            )

            # Generate authorization URL
            authorization_url = auth_request.build_authorization_url()

            logger.info(
                f"Generated authorization URL for client {client_credentials.client_id}"
            )

            return authorization_url, pkce_params, state

        except Exception as e:
            raise AuthorizationError(f"Failed to start authorization flow: {e}") from e

    async def handle_authorization_callback(
        self,
        callback_url: str,
        expected_state: str,
    ) -> AuthorizationResponse:
        """Handle OAuth authorization callback from the authorization server.

        Parses the callback URL, validates the state parameter for CSRF protection,
        and returns the authorization response for further processing.

        Args:
            callback_url: Full callback URL received from authorization server
            expected_state: State parameter that was sent in authorization request

        Returns:
            AuthorizationResponse: Parsed callback response

        Raises:
            CallbackError: If callback URL is malformed
            StateValidationError: If state parameter doesn't match
        """
        try:
            logger.debug(f"Processing authorization callback: {callback_url}")

            # Parse callback URL
            auth_response = self._parse_callback_url(callback_url)

            if auth_response.state is None:
                raise StateValidationError(
                    "Authorization server callback missing required state parameter"
                )

            # Validate state parameter (CSRF protection)
            validate_state(expected_state, auth_response.state)

            if auth_response.is_success():
                logger.info(
                    "Authorization callback successful - received authorization code"
                )
            elif auth_response.is_error():
                logger.warning(
                    f"Authorization callback contained error: {auth_response.error} - "
                    f"{auth_response.error_description}"
                )
            else:
                logger.warning("Authorization callback missing both code and error")

            return auth_response

        except StateValidationError:
            raise  # Re-raise state validation errors as-is
        except Exception as e:
            raise AuthorizationCallbackError(
                f"Failed to process authorization callback: {e}"
            ) from e

    def _parse_callback_url(self, callback_url: str) -> AuthorizationResponse:
        """Parse OAuth callback URL into AuthorizationResponse.

        Args:
            callback_url: Full callback URL from authorization server

        Returns:
            AuthorizationResponse: Parsed callback parameters

        Raises:
            CallbackError: If URL is malformed
        """
        try:
            parsed = urlparse(callback_url)
            query_params = parse_qs(parsed.query)

            # Extract single values from query parameter lists
            def get_single_param(key: str) -> str | None:
                values = query_params.get(key, [])
                return values[0] if values else None

            return AuthorizationResponse(
                code=get_single_param("code"),
                state=get_single_param("state"),
                error=get_single_param("error"),
                error_description=get_single_param("error_description"),
                error_uri=get_single_param("error_uri"),
            )

        except Exception as e:
            raise AuthorizationCallbackError(
                f"Failed to parse callback URL: {e}"
            ) from e
