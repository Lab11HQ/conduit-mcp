class AuthManager:
    """Manages OAuth flows and token lifecycle for MCP clients."""

    async def get_token(self, server_id: str, server_endpoint: str) -> str | None:
        """Get valid access token for server, handling full OAuth flow if needed."""

        # Check if we have valid cached token
        # If not, initiate appropriate OAuth flow (auth code, device, etc.)
        # Handle user interaction (browser redirect, device code display)
        # Exchange for access token, store securely
        pass

    async def handle_unauthorized(self, server_id: str, www_authenticate_header: str):
        # Step 1: Parse WWW-Authenticate (same format everywhere)
        resource_metadata_url = self._parse_www_authenticate(www_authenticate_header)

        # Step 2: Fetch resource metadata (RFC 9728 - standard format)
        resource_metadata = await self._fetch_json(resource_metadata_url)
        auth_server_url = resource_metadata["authorization_servers"][0]

        # Step 3: Fetch auth server metadata (RFC 8414 - standard format)
        auth_metadata = await self._fetch_json(
            f"{auth_server_url}/.well-known/oauth-authorization-server"
        )

        # Step 4: Store endpoints (now we know how to talk to ANY OAuth server)
        self._server_auth_info[server_id] = {
            "authorization_endpoint": auth_metadata["authorization_endpoint"],
            "token_endpoint": auth_metadata["token_endpoint"],
            "device_authorization_endpoint": auth_metadata.get(
                "device_authorization_endpoint"
            ),
            # ... other OAuth metadata
        }

    async def clear_token(self, server_id: str) -> None:
        """Clear stored token (e.g., on repeated 401s)."""
        pass
