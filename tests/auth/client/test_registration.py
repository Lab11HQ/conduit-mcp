"""Tests for OAuth 2.1 dynamic client registration.

High-impact tests covering the core registration flow for public clients:
- Successful registration with proper request/response handling
- Error response parsing and appropriate exception raising
- Request body validation and header construction
- Edge cases and malformed responses
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from conduit.auth.client.models.errors import RegistrationError
from conduit.auth.client.models.registration import (
    ClientMetadata,
    ClientRegistration,
)
from conduit.auth.client.services.registration import OAuth2Registration


class TestSuccessfulRegistration:
    """Test successful registration flow for public clients."""

    def setup_method(self):
        # Arrange
        self.registration_service = OAuth2Registration()
        self.registration_service._http_client = AsyncMock()

    async def test_successful_public_client_registration(self):
        """Test successful registration of public client with all fields."""
        # Arrange
        client_metadata = ClientMetadata(
            client_name="Test MCP Client",
            redirect_uris=["https://localhost:8080/callback"],
            client_uri="https://example.com/client",
            scope="mcp:read mcp:write",
        )

        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "client_id": "generated-client-id-123",
            "client_name": "Test MCP Client",
            "redirect_uris": ["https://localhost:8080/callback"],
            "client_uri": "https://example.com/client",
            "scope": "mcp:read mcp:write",
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "client_id_issued_at": 1640995200,
        }
        self.registration_service._http_client.post.return_value = mock_response

        # Act
        result = await self.registration_service.register_client(
            "https://auth.example.com/register", client_metadata
        )

        # Assert
        assert isinstance(result, ClientRegistration)
        assert result.credentials.client_id == "generated-client-id-123"
        assert result.credentials.client_secret is None  # Public client
        assert result.metadata == client_metadata
        assert result.registration_endpoint == "https://auth.example.com/register"

        # Verify HTTP request was made correctly
        self.registration_service._http_client.post.assert_awaited_once()
        call_args = self.registration_service._http_client.post.call_args

        # Check endpoint
        assert call_args[0][0] == "https://auth.example.com/register"

        # Check request body contains client metadata
        request_json = call_args[1]["json"]
        assert request_json["client_name"] == "Test MCP Client"
        assert request_json["redirect_uris"] == ["https://localhost:8080/callback"]
        assert request_json["token_endpoint_auth_method"] == "none"
        assert request_json["grant_types"] == ["authorization_code"]

        # Check headers
        headers = call_args[1]["headers"]
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"

    async def test_registration_with_initial_access_token(self):
        """Test registration with initial access token for protected endpoints."""
        # Arrange
        client_metadata = ClientMetadata(
            client_name="Protected Client",
            redirect_uris=["https://localhost:8080/callback"],
        )

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "client_id": "protected-client-123",
            "client_name": "Protected Client",
            "redirect_uris": ["https://localhost:8080/callback"],
        }
        self.registration_service._http_client.post.return_value = mock_response

        # Act
        await self.registration_service.register_client(
            "https://auth.example.com/register",
            client_metadata,
            initial_access_token="bearer-token-xyz",
        )

        # Assert
        call_args = self.registration_service._http_client.post.call_args
        headers = call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer bearer-token-xyz"

    async def test_minimal_client_metadata_registration(self):
        """Test registration with only required fields."""
        # Arrange
        client_metadata = ClientMetadata(
            client_name="Minimal Client",
            redirect_uris=["https://localhost:8080/callback"],
        )

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "client_id": "minimal-client-456",
            "client_name": "Minimal Client",
            "redirect_uris": ["https://localhost:8080/callback"],
        }
        self.registration_service._http_client.post.return_value = mock_response

        # Act
        result = await self.registration_service.register_client(
            "https://auth.example.com/register", client_metadata
        )

        # Assert
        assert result.credentials.client_id == "minimal-client-456"

        # Verify request excludes None values
        call_args = self.registration_service._http_client.post.call_args
        request_json = call_args[1]["json"]
        assert "client_uri" not in request_json  # Should be excluded
        assert "scope" not in request_json  # Should be excluded


class TestRegistrationErrors:
    """Test error handling and OAuth error response parsing."""

    def setup_method(self):
        # Arrange
        self.registration_service = OAuth2Registration()
        self.registration_service._http_client = AsyncMock()

    async def test_invalid_client_metadata_error(self):
        """Test handling of invalid_client_metadata OAuth error."""
        # Arrange
        client_metadata = ClientMetadata(
            client_name="Test Client", redirect_uris=["ftp://some.invalid.uri"]
        )

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "invalid_client_metadata",
            "error_description": "redirect_uris must use HTTPS",
        }
        self.registration_service._http_client.post.return_value = mock_response

        # Act & Assert
        with pytest.raises(RegistrationError):
            await self.registration_service.register_client(
                "https://auth.example.com/register", client_metadata
            )

    async def test_unauthorized_registration_endpoint(self):
        """Test handling of 401 Unauthorized (missing initial access token)."""
        # Arrange
        client_metadata = ClientMetadata(
            client_name="Test Client", redirect_uris=["https://localhost:8080/callback"]
        )

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {
            "error": "invalid_token",
            "error_description": "Initial access token required",
        }
        self.registration_service._http_client.post.return_value = mock_response

        # Act & Assert
        with pytest.raises(RegistrationError):
            await self.registration_service.register_client(
                "https://auth.example.com/register", client_metadata
            )

    async def test_forbidden_registration(self):
        """Test handling of 403 Forbidden (policy rejection)."""
        # Arrange
        client_metadata = ClientMetadata(
            client_name="Blocked Client",
            redirect_uris=["https://localhost:8080/callback"],
        )

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "error": "access_denied",
            "error_description": "Client registration not allowed for this issuer",
        }
        self.registration_service._http_client.post.return_value = mock_response

        # Act & Assert
        with pytest.raises(RegistrationError):
            await self.registration_service.register_client(
                "https://auth.example.com/register", client_metadata
            )

    async def test_missing_client_id_in_response(self):
        """Test handling of malformed success response missing client_id."""
        # Arrange
        client_metadata = ClientMetadata(
            client_name="Test Client", redirect_uris=["https://localhost:8080/callback"]
        )

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "client_name": "Test Client",
            # Missing client_id!
        }
        self.registration_service._http_client.post.return_value = mock_response

        # Act & Assert
        with pytest.raises(RegistrationError):
            await self.registration_service.register_client(
                "https://auth.example.com/register", client_metadata
            )


class TestRequestValidation:
    """Test request body construction and validation."""

    def setup_method(self):
        # Arrange
        self.registration_service = OAuth2Registration()
        self.registration_service._http_client = AsyncMock()

    async def test_request_body_is_valid_json(self):
        """Test that request body contains valid JSON with proper OAuth fields."""
        # Arrange
        client_metadata = ClientMetadata(
            client_name="JSON Test Client",
            redirect_uris=[
                "https://localhost:8080/callback",
                "https://localhost:8081/callback",
            ],
            client_uri="https://example.com/client",
            scope="read write",
            contacts=["admin@example.com"],
        )

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"client_id": "test-123"}
        self.registration_service._http_client.post.return_value = mock_response

        # Act
        await self.registration_service.register_client(
            "https://auth.example.com/register", client_metadata
        )

        # Assert
        call_args = self.registration_service._http_client.post.call_args
        request_json = call_args[1]["json"]

        # Verify OAuth 2.1 required fields
        assert request_json["client_name"] == "JSON Test Client"
        assert request_json["redirect_uris"] == [
            "https://localhost:8080/callback",
            "https://localhost:8081/callback",
        ]
        assert request_json["token_endpoint_auth_method"] == "none"
        assert request_json["grant_types"] == ["authorization_code"]
        assert request_json["response_types"] == ["code"]

        # Verify optional fields
        assert request_json["client_uri"] == "https://example.com/client"
        assert request_json["scope"] == "read write"
        assert request_json["contacts"] == ["admin@example.com"]

    async def test_exclude_none_values_from_request(self):
        """Test that None values are excluded from the request body."""
        # Arrange
        client_metadata = ClientMetadata(
            client_name="Minimal Client",
            redirect_uris=["https://localhost:8080/callback"],
            # All other fields are None
        )

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"client_id": "minimal-123"}
        self.registration_service._http_client.post.return_value = mock_response

        # Act
        await self.registration_service.register_client(
            "https://auth.example.com/register", client_metadata
        )

        # Assert
        call_args = self.registration_service._http_client.post.call_args
        request_json = call_args[1]["json"]

        # Required fields should be present
        assert "client_name" in request_json
        assert "redirect_uris" in request_json
        assert "token_endpoint_auth_method" in request_json

        # None fields should be excluded
        assert "client_uri" not in request_json
        assert "logo_uri" not in request_json
        assert "scope" not in request_json
        assert "contacts" not in request_json
        assert "tos_uri" not in request_json
        assert "policy_uri" not in request_json
