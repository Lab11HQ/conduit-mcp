"""Tests for OAuth 2.1 token exchange and management.

High-impact tests covering the token exchange flow:
- Successful authorization code to token exchange
- Token refresh functionality
- Error response handling and OAuth error codes
- Form encoding and request validation
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from conduit.auth.client.models.errors import TokenError
from conduit.auth.client.models.tokens import (
    RefreshTokenRequest,
    TokenRequest,
)
from conduit.auth.client.services.tokens import OAuth2TokenManager


class TestTokenExchange:
    """Test authorization code to access token exchange."""

    def setup_method(self):
        # Arrange
        self.token_manager = OAuth2TokenManager()
        self.token_manager._http_client = AsyncMock()
        self.code_verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"

    async def test_successful_token_exchange_with_all_fields(self):
        """Test successful token exchange with complete response."""
        # Arrange
        token_request = TokenRequest(
            token_endpoint="https://auth.example.com/token",
            code="auth-code-123",
            redirect_uri="https://myapp.com/callback",
            client_id="client-456",
            code_verifier=self.code_verifier,
            resource="https://mcp.example.com",
            scope="read write",
        )

        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "access-token-xyz",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "refresh-token-abc",
            "scope": "read write",
        }
        self.token_manager._http_client.post.return_value = mock_response

        # Act
        token_response = await self.token_manager.exchange_code_for_token(token_request)

        # Assert
        assert token_response.is_success()
        assert not token_response.is_error()
        assert token_response.access_token == "access-token-xyz"
        assert token_response.token_type == "Bearer"
        assert token_response.expires_in == 3600
        assert token_response.refresh_token == "refresh-token-abc"
        assert token_response.scope == "read write"
        assert token_response.error is None

        # Verify HTTP request was made correctly
        self.token_manager._http_client.post.assert_awaited_once()
        call_args = self.token_manager._http_client.post.call_args

        # Check endpoint
        assert call_args[0][0] == "https://auth.example.com/token"

        # Check form data
        form_data = call_args[1]["data"]
        assert form_data["grant_type"] == "authorization_code"
        assert form_data["code"] == "auth-code-123"
        assert form_data["redirect_uri"] == "https://myapp.com/callback"
        assert form_data["client_id"] == "client-456"
        assert form_data["code_verifier"] == self.code_verifier
        assert form_data["resource"] == "https://mcp.example.com"
        assert form_data["scope"] == "read write"

        # Check headers
        headers = call_args[1]["headers"]
        assert headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert headers["Accept"] == "application/json"

    async def test_token_exchange_without_optional_fields(self):
        """Test token exchange with minimal required fields."""
        # Arrange
        token_request = TokenRequest(
            token_endpoint="https://auth.example.com/token",
            code="auth-code-123",
            redirect_uri="https://myapp.com/callback",
            client_id="client-456",
            code_verifier=self.code_verifier,
            # No resource or scope
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "access-token-xyz",
            "token_type": "Bearer",
        }
        self.token_manager._http_client.post.return_value = mock_response

        # Act
        token_response = await self.token_manager.exchange_code_for_token(token_request)

        # Assert
        assert token_response.is_success()
        assert token_response.access_token == "access-token-xyz"

        # Verify optional fields are excluded from form data
        call_args = self.token_manager._http_client.post.call_args
        form_data = call_args[1]["data"]
        assert "resource" not in form_data
        assert "scope" not in form_data

    async def test_token_response_conversion_to_token_state(self):
        """Test converting successful token response to TokenState."""
        # Arrange
        token_request = TokenRequest(
            token_endpoint="https://auth.example.com/token",
            code="auth-code-123",
            redirect_uri="https://myapp.com/callback",
            client_id="client-456",
            code_verifier=self.code_verifier,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "access-token-xyz",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "refresh-token-abc",
        }
        self.token_manager._http_client.post.return_value = mock_response

        # Act
        token_response = await self.token_manager.exchange_code_for_token(token_request)
        token_state = token_response.to_token_state()

        # Assert
        assert token_state.access_token == "access-token-xyz"
        assert token_state.refresh_token == "refresh-token-abc"
        assert token_state.token_type == "Bearer"
        assert token_state.expires_at is not None  # Should calculate expiry time
        assert token_state.is_valid()
        assert token_state.can_refresh()


class TestTokenExchangeErrors:
    """Test error handling in token exchange."""

    def setup_method(self):
        # Arrange
        self.token_manager = OAuth2TokenManager()
        self.token_manager._http_client = AsyncMock()
        self.code_verifier = "dBjftJeZ4CVP"

    async def test_invalid_grant_error(self):
        """Test handling of invalid_grant OAuth error."""
        # Arrange
        token_request = TokenRequest(
            token_endpoint="https://auth.example.com/token",
            code="expired-code-123",
            redirect_uri="https://myapp.com/callback",
            client_id="client-456",
            code_verifier=self.code_verifier,
        )

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Authorization code has expired",
        }
        self.token_manager._http_client.post.return_value = mock_response

        # Act
        token_response = await self.token_manager.exchange_code_for_token(token_request)

        # Assert
        assert not token_response.is_success()
        assert token_response.is_error()
        assert token_response.error == "invalid_grant"
        assert token_response.error_description == "Authorization code has expired"
        assert token_response.access_token is None

    async def test_invalid_client_error(self):
        """Test handling of invalid_client OAuth error."""
        # Arrange
        token_request = TokenRequest(
            token_endpoint="https://auth.example.com/token",
            code="auth-code-123",
            redirect_uri="https://myapp.com/callback",
            client_id="invalid-client",
            code_verifier=self.code_verifier,
        )

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {
            "error": "invalid_client",
            "error_description": "Client authentication failed",
        }
        self.token_manager._http_client.post.return_value = mock_response

        # Act
        token_response = await self.token_manager.exchange_code_for_token(token_request)

        # Assert
        assert token_response.is_error()
        assert token_response.error == "invalid_client"
        assert token_response.error_description == "Client authentication failed"

    async def test_missing_access_token_in_success_response(self):
        """Test handling of malformed success response missing access_token."""
        # Arrange
        token_request = TokenRequest(
            token_endpoint="https://auth.example.com/token",
            code="auth-code-123",
            redirect_uri="https://myapp.com/callback",
            client_id="client-456",
            code_verifier=self.code_verifier,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "token_type": "Bearer",
            # Missing access_token!
        }
        self.token_manager._http_client.post.return_value = mock_response

        # Act & Assert
        with pytest.raises(TokenError) as exc_info:
            await self.token_manager.exchange_code_for_token(token_request)

        assert "missing required access_token" in str(exc_info.value)


class TestTokenRefresh:
    """Test token refresh functionality."""

    def setup_method(self):
        # Arrange
        self.token_manager = OAuth2TokenManager()
        self.token_manager._http_client = AsyncMock()
        self.code_verifier = "dBjftJeZ4CVP"

    async def test_successful_token_refresh(self):
        """Test successful token refresh."""
        # Arrange
        refresh_request = RefreshTokenRequest(
            token_endpoint="https://auth.example.com/token",
            refresh_token="refresh-token-abc",
            client_id="client-456",
            resource="https://mcp.example.com",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-access-token-xyz",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "new-refresh-token-def",  # New refresh token
        }
        self.token_manager._http_client.post.return_value = mock_response

        # Act
        token_response = await self.token_manager.refresh_access_token(refresh_request)

        # Assert
        assert token_response.is_success()
        assert token_response.access_token == "new-access-token-xyz"
        assert token_response.refresh_token == "new-refresh-token-def"

        # Verify HTTP request
        call_args = self.token_manager._http_client.post.call_args
        form_data = call_args[1]["data"]
        assert form_data["grant_type"] == "refresh_token"
        assert form_data["refresh_token"] == "refresh-token-abc"
        assert form_data["client_id"] == "client-456"
        assert form_data["resource"] == "https://mcp.example.com"

    async def test_refresh_token_error(self):
        """Test handling of refresh token errors."""
        # Arrange
        refresh_request = RefreshTokenRequest(
            token_endpoint="https://auth.example.com/token",
            refresh_token="invalid-refresh-token",
            client_id="client-456",
        )

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Refresh token has expired",
        }
        self.token_manager._http_client.post.return_value = mock_response

        # Act
        token_response = await self.token_manager.refresh_access_token(refresh_request)

        # Assert
        assert token_response.is_error()
        assert token_response.error == "invalid_grant"
        assert token_response.error_description == "Refresh token has expired"


class TestFormEncoding:
    """Test form encoding requirements."""

    def setup_method(self):
        # Arrange
        self.token_manager = OAuth2TokenManager()
        self.token_manager._http_client = AsyncMock()
        self.code_verifier = "dBjftJeZ4CVP"

    async def test_form_encoding_content_type(self):
        """Test that requests use proper form encoding content type."""
        # Arrange
        token_request = TokenRequest(
            token_endpoint="https://auth.example.com/token",
            code="auth-code-123",
            redirect_uri="https://myapp.com/callback",
            client_id="client-456",
            code_verifier=self.code_verifier,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "token-xyz"}
        self.token_manager._http_client.post.return_value = mock_response

        # Act
        await self.token_manager.exchange_code_for_token(token_request)

        # Assert
        call_args = self.token_manager._http_client.post.call_args
        headers = call_args[1]["headers"]

        # Must use form encoding, not JSON
        assert headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert headers["Accept"] == "application/json"

        # Should use 'data' parameter (form), not 'json' parameter
        assert "data" in call_args[1]
        assert "json" not in call_args[1]


class TestHttpErrors:
    """Test HTTP-level errors and network issues."""

    def setup_method(self):
        # Arrange
        self.token_manager = OAuth2TokenManager()
        self.token_manager._http_client = AsyncMock()
        self.code_verifier = "dBjftJeZ4CVP"

    async def test_network_error_raises_token_error(self):
        """Test that network errors are wrapped in TokenError."""
        # Arrange
        token_request = TokenRequest(
            token_endpoint="https://auth.example.com/token",
            code="auth-code-123",
            redirect_uri="https://myapp.com/callback",
            client_id="client-456",
            code_verifier=self.code_verifier,
        )

        # Mock network failure
        import httpx

        self.token_manager._http_client.post.side_effect = httpx.ConnectError(
            "Connection failed"
        )

        # Act & Assert
        with pytest.raises(TokenError):
            await self.token_manager.exchange_code_for_token(token_request)

    async def test_non_json_error_response_raises_token_error(self):
        """Test that non-JSON error responses raise TokenError."""
        # Arrange
        token_request = TokenRequest(
            token_endpoint="https://auth.example.com/token",
            code="auth-code-123",
            redirect_uri="https://myapp.com/callback",
            client_id="client-456",
            code_verifier=self.code_verifier,
        )

        # Mock response that returns HTML instead of JSON (common for 401/500 errors)
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.side_effect = ValueError(
            "Not valid JSON"
        )  # JSON parsing fails

        self.token_manager._http_client.post.return_value = mock_response

        # Act & Assert
        with pytest.raises(TokenError):
            await self.token_manager.exchange_code_for_token(token_request)
