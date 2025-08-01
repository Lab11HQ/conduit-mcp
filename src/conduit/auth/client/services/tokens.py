"""OAuth 2.1 token exchange and management service.

Implements RFC 6749 token endpoint interactions with PKCE (RFC 7636)
and Resource Indicators (RFC 8707) for secure MCP authentication.
"""

from __future__ import annotations

import logging

import httpx
from pydantic import ValidationError

from conduit.auth.client.models.errors import TokenError
from conduit.auth.client.models.tokens import (
    RefreshTokenRequest,
    TokenRequest,
    TokenResponse,
)

logger = logging.getLogger(__name__)


class OAuth2TokenManager:
    """Manages OAuth 2.1 token exchange and refresh operations.

    Handles the token endpoint interactions including:
    - Authorization code to access token exchange (RFC 6749 Section 4.1.3)
    - Access token refresh (RFC 6749 Section 6)
    - PKCE code verification (RFC 7636)
    - Resource parameter handling (RFC 8707)

    Uses application/x-www-form-urlencoded encoding as required by OAuth 2.1.
    """

    def __init__(self, timeout: float = 30.0):
        """Initialize OAuth token manager.

        Args:
            timeout: HTTP request timeout in seconds
        """
        self.timeout = timeout
        self._http_client = httpx.AsyncClient(timeout=timeout)

    async def exchange_code_for_token(
        self, token_request: TokenRequest
    ) -> TokenResponse:
        """Exchange authorization code for access token.

        Implements RFC 6749 Section 4.1.3 - Access Token Request.
        Includes PKCE code_verifier for security (RFC 7636).

        Args:
            token_request: Token exchange request parameters

        Returns:
            TokenResponse: Token response (success or error)

        Raises:
            TokenError: If token exchange fails due to network/parsing issues
        """
        logger.debug(f"Exchanging authorization code at {token_request.token_endpoint}")

        try:
            # Prepare form-encoded request (RFC 6749 requires this format)
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            }

            form_data = token_request.to_form_data()

            # Log request details (without sensitive data)
            logger.debug(
                f"Token request: grant_type={form_data['grant_type']}, "
                f"client_id={form_data['client_id']}, "
                f"resource={form_data.get('resource', 'none')}"
            )

            # Send token request
            response = await self._http_client.post(
                token_request.token_endpoint,
                data=form_data,
                headers=headers,
            )

            # Parse response (both success and error responses are JSON)
            return await self._parse_token_response(response)

        except httpx.HTTPError as e:
            raise TokenError(f"HTTP error during token exchange: {e}") from e
        except Exception as e:
            raise TokenError(f"Unexpected error during token exchange: {e}") from e

    async def refresh_access_token(
        self, refresh_request: RefreshTokenRequest
    ) -> TokenResponse:
        """Refresh an access token using a refresh token.

        Implements RFC 6749 Section 6 - Refreshing an Access Token.

        Args:
            refresh_request: Refresh token request parameters

        Returns:
            TokenResponse: New token response (success or error)

        Raises:
            TokenError: If token refresh fails due to network/parsing issues
        """
        logger.debug(f"Refreshing access token at {refresh_request.token_endpoint}")

        try:
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            }

            form_data = refresh_request.to_form_data()

            logger.debug(
                f"Refresh request: client_id={form_data['client_id']}, "
                f"resource={form_data.get('resource', 'none')}"
            )

            response = await self._http_client.post(
                refresh_request.token_endpoint,
                data=form_data,
                headers=headers,
            )

            return await self._parse_token_response(response)

        except httpx.HTTPError as e:
            raise TokenError(f"HTTP error during token refresh: {e}") from e
        except Exception as e:
            raise TokenError(f"Unexpected error during token refresh: {e}") from e

    async def _parse_token_response(self, response: httpx.Response) -> TokenResponse:
        """Parse token endpoint response into TokenResponse.

        Handles both successful responses (200) and error responses (400+)
        according to RFC 6749 Section 5.

        Args:
            response: HTTP response from token endpoint

        Returns:
            TokenResponse: Parsed response (success or error)

        Raises:
            TokenError: If response cannot be parsed
        """
        try:
            response_data = response.json()

            if response.status_code == 200:
                # Successful token response (RFC 6749 Section 5.1)
                logger.info("Token exchange successful")

                # Validate required fields
                if "access_token" not in response_data:
                    raise TokenError("Token response missing required access_token")

                return TokenResponse(**response_data)

            else:
                # Error response (RFC 6749 Section 5.2)
                error_code = response_data.get("error", "unknown_error")
                error_description = response_data.get(
                    "error_description", "No description provided"
                )

                logger.warning(
                    f"Token exchange failed with {response.status_code}: "
                    f"{error_code} - {error_description}"
                )

                return TokenResponse(**response_data)

        except (ValueError, ValidationError) as e:
            raise TokenError(f"Invalid token response format: {e}") from e
        except Exception as e:
            raise TokenError(f"Failed to parse token response: {e}") from e

    async def close(self) -> None:
        """Close the HTTP client and clean up resources."""
        await self._http_client.aclose()
