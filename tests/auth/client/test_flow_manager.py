"""Tests for OAuth 2.1 authorization flow orchestration.

High-impact tests covering the complete authorization flow:
- Authorization URL generation with proper parameters
- Callback parsing and state validation
- Security parameter handling
- Error scenarios and edge cases
"""

from urllib.parse import parse_qs, urlparse

import pytest

from conduit.auth.client.models.discovery import (
    AuthorizationServerMetadata,
    DiscoveryResult,
    ProtectedResourceMetadata,
)
from conduit.auth.client.models.errors import (
    StateValidationError,
)
from conduit.auth.client.models.registration import ClientCredentials
from conduit.auth.client.models.security import PKCEParameters
from conduit.auth.client.services.flow import OAuth2FlowManager


class TestStartAuthorizationFlow:
    """Test authorization flow initiation and URL generation."""

    def setup_method(self):
        # Arrange
        self.flow_manager = OAuth2FlowManager()

        # Mock discovery result
        self.discovery_result = DiscoveryResult(
            server_url="https://mcp.example.com",
            protected_resource_metadata=ProtectedResourceMetadata(
                authorization_servers=["https://auth.example.com"]
            ),
            authorization_server_metadata=AuthorizationServerMetadata(
                issuer="https://auth.example.com",
                authorization_endpoint="https://auth.example.com/authorize",
                token_endpoint="https://auth.example.com/token",
                response_types_supported=["code"],
            ),
            auth_server_url="https://auth.example.com",
        )

        # Mock client credentials
        self.client_credentials = ClientCredentials(client_id="test-client-123")

    async def test_successful_flow_start_generates_valid_url(self):
        """Test successful authorization flow start with all parameters."""
        # Act
        auth_url, pkce_params, state = await self.flow_manager.start_authorization_flow(
            self.discovery_result,
            self.client_credentials,
            "https://myapp.com/callback",
            scope="read write",
        )

        # Assert - Parse the generated URL
        parsed = urlparse(auth_url)
        query_params = parse_qs(parsed.query)

        # Check base URL
        assert parsed.scheme == "https"
        assert parsed.netloc == "auth.example.com"
        assert parsed.path == "/authorize"

        # Check required OAuth 2.1 parameters
        assert query_params["response_type"] == ["code"]
        assert query_params["client_id"] == ["test-client-123"]
        assert query_params["redirect_uri"] == ["https://myapp.com/callback"]
        assert query_params["code_challenge_method"] == ["S256"]
        assert query_params["state"] == [state]

        # Check PKCE parameters
        assert "code_challenge" in query_params
        assert query_params["code_challenge"][0] == pkce_params.code_challenge

        # Check RFC 8707 resource parameter
        assert query_params["resource"] == ["https://mcp.example.com"]

        # Check scope
        assert query_params["scope"] == ["read write"]

        # Verify return values
        assert isinstance(pkce_params, PKCEParameters)
        assert len(state) == 32  # Security module generates 32-char state
        assert auth_url.startswith("https://auth.example.com/authorize?")

    async def test_flow_start_without_scope(self):
        """Test authorization flow start without optional scope parameter."""
        # Act
        auth_url, pkce_params, state = await self.flow_manager.start_authorization_flow(
            self.discovery_result,
            self.client_credentials,
            "https://myapp.com/callback",
            # No scope parameter
        )

        # Assert
        parsed = urlparse(auth_url)
        query_params = parse_qs(parsed.query)

        # Scope should not be present
        assert "scope" not in query_params

        # Other parameters should still be there
        assert query_params["response_type"] == ["code"]
        assert query_params["resource"] == ["https://mcp.example.com"]


class TestHandleAuthorizationCallback:
    """Test callback URL parsing and state validation."""

    def setup_method(self):
        # Arrange
        self.flow_manager = OAuth2FlowManager()

    async def test_successful_callback_with_authorization_code(self):
        """Test successful callback parsing with authorization code."""
        # Arrange
        expected_state = "test-state-123"
        callback_url = (
            "https://myapp.com/callback?code=auth-code-456&state=test-state-123"
        )

        # Act
        auth_response = await self.flow_manager.handle_authorization_callback(
            callback_url, expected_state
        )

        # Assert
        assert auth_response.is_success()
        assert not auth_response.is_error()
        assert auth_response.code == "auth-code-456"
        assert auth_response.state == "test-state-123"
        assert auth_response.error is None

    async def test_error_callback_with_oauth_error(self):
        """Test callback parsing with OAuth error response."""
        # Arrange
        expected_state = "test-state-123"
        callback_url = (
            "https://myapp.com/callback?"
            "error=access_denied&"
            "error_description=User+denied+access&"
            "state=test-state-123"
        )

        # Act
        auth_response = await self.flow_manager.handle_authorization_callback(
            callback_url, expected_state
        )

        # Assert
        assert not auth_response.is_success()
        assert auth_response.is_error()
        assert auth_response.error == "access_denied"
        assert auth_response.error_description == "User denied access"
        assert auth_response.code is None

    async def test_state_parameter_mismatch_raises_error(self):
        """Test state validation failure raises StateValidationError."""
        # Arrange
        expected_state = "expected-state-123"
        callback_url = (
            "https://myapp.com/callback?code=auth-code-456&state=wrong-state-456"
        )

        # Act & Assert
        with pytest.raises(StateValidationError) as exc_info:
            await self.flow_manager.handle_authorization_callback(
                callback_url, expected_state
            )

        assert "State parameter mismatch" in str(exc_info.value)
        assert "CSRF attack" in str(exc_info.value)

    async def test_missing_state_parameter_raises_error(self):
        """Test missing state parameter raises StateValidationError."""
        # Arrange
        expected_state = "expected-state-123"
        callback_url = "https://myapp.com/callback?code=auth-code-456"  # No state

        # Act & Assert
        with pytest.raises(StateValidationError):
            await self.flow_manager.handle_authorization_callback(
                callback_url, expected_state
            )

    async def test_callback_url_parsing_edge_cases(self):
        """Test edge cases in URL parsing that should work."""
        # Arrange
        expected_state = "test-state-123"

        # These URLs are weird but should parse successfully:
        weird_but_valid_urls = [
            "ftp://example.com/callback?code=abc&state=test-state-123",
            "https://example.com:8080/callback?code=abc&state=test-state-123",
            "https://example.com/path/callback?code=abc&state=test-state-123&extra=ignored",
        ]

        for callback_url in weird_but_valid_urls:
            # Act - Should not raise
            auth_response = await self.flow_manager.handle_authorization_callback(
                callback_url, expected_state
            )

            # Assert
            assert auth_response.code == "abc"
            assert auth_response.state == "test-state-123"
