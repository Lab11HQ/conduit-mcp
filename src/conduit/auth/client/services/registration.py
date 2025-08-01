"""OAuth 2.1 dynamic client registration service.

Implements RFC 7591 (OAuth 2.0 Dynamic Client Registration Protocol)
to automatically register MCP clients with authorization servers.
"""

from __future__ import annotations

import logging

import httpx
from pydantic import ValidationError

from conduit.auth.client.models.errors import RegistrationError
from conduit.auth.client.models.registration import (
    ClientCredentials,
    ClientMetadata,
    ClientRegistration,
)

logger = logging.getLogger(__name__)


class OAuth2Registration:
    """Handles OAuth 2.1 dynamic client registration for MCP authentication.

    Implements RFC 7591 to automatically register clients with authorization
    servers, eliminating the need for manual client configuration.

    Supports both confidential and public client registration with proper
    error handling and validation.
    """

    def __init__(self, timeout: float = 30.0):
        """Initialize OAuth registration.

        Args:
            timeout: HTTP request timeout in seconds
        """
        self.timeout = timeout
        self._http_client = httpx.AsyncClient(timeout=timeout)

    async def register_client(
        self,
        registration_endpoint: str,
        client_metadata: ClientMetadata,
        initial_access_token: str | None = None,
    ) -> ClientRegistration:
        """Register a new OAuth client with the authorization server.

        Args:
            registration_endpoint: Client registration endpoint URL
            client_metadata: Client metadata to register
            initial_access_token: Optional initial access token for protected
                registration endpoints

        Returns:
            Complete client registration result

        Raises:
            RegistrationError: If registration fails
        """
        logger.debug(f"Registering client at {registration_endpoint}")

        try:
            # Prepare registration request
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            # Add initial access token if provided (RFC 7591 Section 3.1)
            if initial_access_token:
                headers["Authorization"] = f"Bearer {initial_access_token}"

            # Send registration request
            response = await self._http_client.post(
                registration_endpoint,
                json=client_metadata.model_dump(exclude_none=True, mode="json"),
                headers=headers,
            )

            # Handle response
            if response.status_code == 201:
                return await self._handle_successful_registration(
                    response, registration_endpoint, client_metadata
                )
            else:
                await self._handle_registration_error(response)

        except httpx.HTTPError as e:
            raise RegistrationError(f"HTTP error during registration: {e}") from e
        except Exception as e:
            raise RegistrationError(f"Unexpected error during registration: {e}") from e

    async def _handle_successful_registration(
        self,
        response: httpx.Response,
        registration_endpoint: str,
        original_metadata: ClientMetadata,
    ) -> ClientRegistration:
        """Handle successful registration response.

        Args:
            response: Successful HTTP response
            registration_endpoint: Registration endpoint used
            original_metadata: Original client metadata sent

        Returns:
            Complete client registration result

        Raises:
            RegistrationError: If response parsing fails
        """
        try:
            response_data = response.json()

            # Validate required fields are present
            if "client_id" not in response_data:
                raise RegistrationError(
                    "Registration response missing required client_id"
                )

            # Parse client credentials from response
            credentials = ClientCredentials(**response_data)

            logger.info(
                f"Successfully registered client {credentials.client_id} "
                f"at {registration_endpoint}"
            )

            return ClientRegistration(
                metadata=original_metadata,
                credentials=credentials,
                registration_endpoint=registration_endpoint,
            )

        except (ValueError, ValidationError) as e:
            raise RegistrationError(f"Invalid registration response format: {e}") from e
        except Exception as e:
            raise RegistrationError(
                f"Failed to parse registration response: {e}"
            ) from e

    async def _handle_registration_error(self, response: httpx.Response) -> None:
        """Handle registration error response.

        Args:
            response: Error HTTP response

        Raises:
            RegistrationError: Always raises with appropriate error message
        """
        try:
            error_data = response.json()
            error_code = error_data.get("error", "unknown_error")
            error_description = error_data.get(
                "error_description", "No description provided"
            )

            logger.error(
                f"Client registration failed with {response.status_code}: "
                f"{error_code} - {error_description}"
            )

            # Map common OAuth error codes to more specific messages
            if error_code == "invalid_client_metadata":
                raise RegistrationError(f"Invalid client metadata: {error_description}")
            elif error_code == "invalid_redirect_uri":
                raise RegistrationError(f"Invalid redirect URI: {error_description}")
            elif error_code == "invalid_client_uri":
                raise RegistrationError(f"Invalid client URI: {error_description}")
            elif response.status_code == 401:
                raise RegistrationError(
                    "Registration endpoint requires authentication "
                    "(initial access token)"
                )
            elif response.status_code == 403:
                raise RegistrationError(
                    "Registration forbidden - check authorization server policy"
                )
            else:
                raise RegistrationError(
                    f"Registration failed ({response.status_code}): {error_code} - "
                    f"{error_description}"
                )

        except (ValueError, KeyError):
            # Fallback for non-JSON error responses
            raise RegistrationError(
                f"Registration failed with HTTP {response.status_code}: {response.text}"
            )

    async def close(self) -> None:
        """Close the HTTP client and clean up resources."""
        await self._http_client.aclose()
