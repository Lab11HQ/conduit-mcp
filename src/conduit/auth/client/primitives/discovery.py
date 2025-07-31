"""OAuth 2.1 server discovery primitive.

Implements RFC 9728 (Protected Resource Metadata) and RFC 8414
(Authorization Server Metadata) discovery to find OAuth endpoints and capabilities
for MCP servers.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import ValidationError

from conduit.auth.client.models.discovery import (
    AuthorizationServerMetadata,
    DiscoveryResult,
    ProtectedResourceMetadata,
)
from conduit.auth.client.models.errors import (
    AuthorizationServerMetadataError,
    DiscoveryError,
    ProtectedResourceMetadataError,
)

logger = logging.getLogger(__name__)


class OAuth2Discovery:
    """Handles OAuth 2.1 server discovery for MCP authentication.

    Implements the two-step discovery process:
    1. Protected Resource Metadata (RFC 9728) - find authorization servers
    2. Authorization Server Metadata (RFC 8414) - find OAuth endpoints

    Supports discovery from 401 responses (WWW-Authenticate header) and
    direct URL discovery with proper fallback strategies.
    """

    def __init__(self, timeout: float = 30.0):
        """Initialize OAuth discovery.

        Args:
            timeout: HTTP request timeout in seconds
        """
        self.timeout = timeout
        self._http_client = httpx.AsyncClient(timeout=timeout)

    async def discover_from_401(self, response: httpx.Response) -> DiscoveryResult:
        """Discover OAuth configuration from a 401 Unauthorized response.

        Extracts the resource metadata URL from the WWW-Authenticate header
        and performs the complete discovery chain.

        Args:
            response: 401 response from MCP server

        Returns:
            Complete discovery results

        Raises:
            DiscoveryError: If discovery fails
        """
        if response.status_code != 401:
            raise DiscoveryError(f"Expected 401 response, got {response.status_code}")

        # Extract server URL from the original request
        server_url = str(response.request.url)

        # Try to get resource metadata URL from WWW-Authenticate header
        resource_metadata_url = self._extract_resource_metadata_from_www_auth(response)

        if resource_metadata_url:
            logger.debug(
                "Found resource metadata URL in WWW-Authenticate: "
                f"{resource_metadata_url}"
            )
            prm = await self._fetch_protected_resource_metadata(resource_metadata_url)
        else:
            logger.debug(
                "No resource metadata URL in WWW-Authenticate, using fallbackdiscovery"
            )
            prm = await self._discover_protected_resource_metadata(server_url)

        # Get authorization server metadata
        auth_server_url = str(prm.authorization_servers[0])
        asm = await self._discover_authorization_server_metadata(auth_server_url)

        return DiscoveryResult(
            server_url=server_url,
            protected_resource_metadata=prm,
            authorization_server_metadata=asm,
            auth_server_url=auth_server_url,
        )

    async def discover_from_url(self, server_url: str) -> DiscoveryResult:
        """Discover OAuth configuration from an MCP server URL.

        Performs discovery using well-known endpoints without requiring
        a 401 response first.

        Args:
            server_url: MCP server URL to discover OAuth config for

        Returns:
            Complete discovery results

        Raises:
            DiscoveryError: If discovery fails
        """
        # Discover protected resource metadata
        prm = await self._discover_protected_resource_metadata(server_url)

        # Get authorization server metadata
        auth_server_url = str(prm.authorization_servers[0])
        asm = await self._discover_authorization_server_metadata(auth_server_url)

        return DiscoveryResult(
            server_url=server_url,
            protected_resource_metadata=prm,
            authorization_server_metadata=asm,
            auth_server_url=auth_server_url,
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http_client.aclose()

    def _extract_resource_metadata_from_www_auth(
        self, response: httpx.Response
    ) -> str | None:
        """Extract resource metadata URL from WWW-Authenticate header.

        RFC 9728 Section 5.1: WWW-Authenticate response should contain
        resource_metadata parameter pointing to the metadata URL.

        Args:
            response: HTTP response containing WWW-Authenticate header

        Returns:
            Resource metadata URL if found, None otherwise
        """
        www_auth_header = response.headers.get("WWW-Authenticate")
        if not www_auth_header:
            return None

        # Pattern matches: resource_metadata="url" or resource_metadata=url (unquoted)
        pattern = r'resource_metadata=(?:"([^"]+)"|([^\s,]+))'
        match = re.search(pattern, www_auth_header)

        if match:
            # Return quoted value if present, otherwise unquoted value
            return match.group(1) or match.group(2)

        return None

    async def _discover_protected_resource_metadata(
        self, server_url: str
    ) -> ProtectedResourceMetadata:
        """Discover protected resource metadata using well-known endpoint.

        RFC 9728: Protected resource metadata should be available at
        /.well-known/oauth-protected-resource

        Args:
            server_url: MCP server URL

        Returns:
            Protected resource metadata

        Raises:
            ProtectedResourceMetadataError: If discovery fails
        """
        # Build well-known URL
        parsed = urlparse(server_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        metadata_url = urljoin(base_url, "/.well-known/oauth-protected-resource")

        return await self._fetch_protected_resource_metadata(metadata_url)

    async def _fetch_protected_resource_metadata(
        self, metadata_url: str
    ) -> ProtectedResourceMetadata:
        """Fetch and parse protected resource metadata.

        Args:
            metadata_url: URL to fetch metadata from

        Returns:
            Parsed protected resource metadata

        Raises:
            ProtectedResourceMetadataError: If fetch or parsing fails
            httpx.HTTPStatusError: If an HTTP error occurs
        """
        try:
            logger.debug(f"Fetching protected resource metadata from: {metadata_url}")
            response = await self._http_client.get(metadata_url)
            response.raise_for_status()

            content = response.text
            metadata = ProtectedResourceMetadata.model_validate_json(content)

            logger.debug(
                f"Successfully discovered protected resource metadata: "
                f"{len(metadata.authorization_servers)} auth servers"
            )
            return metadata

        except httpx.HTTPStatusError as e:
            raise ProtectedResourceMetadataError(
                f"Failed to fetch protected resource metadata from {metadata_url}: {e}"
            ) from e
        except ValidationError as e:
            raise ProtectedResourceMetadataError(
                f"Invalid protected resource metadata from {metadata_url}: {e}"
            ) from e
        except Exception as e:
            raise ProtectedResourceMetadataError(
                f"Unexpected error fetching protected resource metadata: {e}"
            ) from e

    async def _discover_authorization_server_metadata(
        self, auth_server_url: str
    ) -> AuthorizationServerMetadata:
        """Discover authorization server metadata.

        RFC 8414: Authorization server metadata should be available at
        /.well-known/oauth-authorization-server (with path-aware discovery)

        Args:
            auth_server_url: Authorization server URL

        Returns:
            Authorization server metadata

        Raises:
            AuthorizationServerMetadataError: If discovery fails
        """
        discovery_urls = self._build_discovery_urls(auth_server_url)

        for url in discovery_urls:
            try:
                logger.debug(f"Trying authorization server metadata discovery: {url}")
                response = await self._http_client.get(url)

                if response.status_code == 200:
                    content = response.text
                    metadata = AuthorizationServerMetadata.model_validate_json(content)
                    logger.debug(
                        f"Successfully discovered authorization server metadata from: "
                        f"{url}"
                    )
                    return metadata
                elif response.status_code >= 500:
                    # Server error - don't try other URLs
                    break

            except ValidationError:
                # Invalid metadata - try next URL
                continue
            except httpx.RequestError:
                # Network error - try next URL
                continue

        raise AuthorizationServerMetadataError(
            f"Failed to discover authorization server metadata for {auth_server_url}. "
            f"Tried URLs: {discovery_urls}"
        )

    def _build_discovery_urls(self, auth_server_url: str) -> list[str]:
        """Build ordered list of discovery URLs to try.

        RFC 8414 Section 3: Path-aware discovery should be tried first,
        then fallback to root discovery.

        Args:
            auth_server_url: Authorization server URL

        Returns:
            Ordered list of URLs to try for discovery
        """
        parsed = urlparse(auth_server_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        urls = []

        # RFC 8414: Path-aware OAuth discovery
        if parsed.path and parsed.path != "/":
            oauth_path = (
                f"/.well-known/oauth-authorization-server{parsed.path.rstrip('/')}"
            )
            urls.append(urljoin(base_url, oauth_path))

        # OAuth root fallback
        urls.append(urljoin(base_url, "/.well-known/oauth-authorization-server"))

        # OIDC discovery fallback (many servers support this)
        if parsed.path and parsed.path != "/":
            oidc_path = f"/.well-known/openid-configuration{parsed.path.rstrip('/')}"
            urls.append(urljoin(base_url, oidc_path))

        urls.append(urljoin(base_url, "/.well-known/openid-configuration"))

        return urls
