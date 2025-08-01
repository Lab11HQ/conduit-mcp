"""Tests for URL parsing and building in OAuth discovery.

Tests the mechanical URL operations that are prone to edge cases:
- WWW-Authenticate header parsing
- Discovery URL construction
- Resource URL canonicalization
"""

from unittest.mock import Mock

from conduit.auth.client.models.discovery import (
    AuthorizationServerMetadata,
    DiscoveryResult,
    ProtectedResourceMetadata,
)
from conduit.auth.client.services.discovery import OAuth2Discovery


class TestWWWAuthenticateHeaderParsing:
    """Test extraction of resource metadata URLs from WWW-Authenticate headers."""

    def setup_method(self):
        self.discovery = OAuth2Discovery()

    def test_extract_quoted_resource_metadata_from_www_auth(self):
        # Arrange
        response = Mock()
        response.headers = {
            "WWW-Authenticate": 'Bearer resource_metadata="https://api.example.com/.well-known/oauth-protected-resource"'
        }

        # Act
        url = self.discovery._extract_resource_metadata_from_www_auth(response)

        # Assert
        assert url == "https://api.example.com/.well-known/oauth-protected-resource"

    def test_extract_unquoted_resource_metadata_from_www_auth(self):
        # Arrange
        response = Mock()
        response.headers = {
            "WWW-Authenticate": "Bearer resource_metadata=https://api.example.com/.well-known/oauth-protected-resource"
        }

        # Act
        url = self.discovery._extract_resource_metadata_from_www_auth(response)

        # Assert
        assert url == "https://api.example.com/.well-known/oauth-protected-resource"

    def test_complex_www_authenticate_header(self):
        # Arrange
        response = Mock()
        response.headers = {
            "WWW-Authenticate": 'Bearer realm="api", error="invalid_token",'
            'resource_metadata="https://api.example.com/.well-known/oauth-protected-resource",'
            'error_description="Token expired"'
        }

        # Act
        url = self.discovery._extract_resource_metadata_from_www_auth(response)

        # Assert
        assert url == "https://api.example.com/.well-known/oauth-protected-resource"

    def test_no_resource_metadata_parameter(self):
        # Arrange
        response = Mock()
        response.headers = {
            "WWW-Authenticate": 'Bearer realm="api", error="invalid_token"'
        }

        # Act
        url = self.discovery._extract_resource_metadata_from_www_auth(response)

        # Assert
        assert url is None

    def test_missing_www_authenticate_header(self):
        # Arrange
        response = Mock()
        response.headers = {}

        # Act
        url = self.discovery._extract_resource_metadata_from_www_auth(response)

        # Assert
        assert url is None

    def test_url_with_path_and_query(self):
        # Arrange
        response = Mock()
        response.headers = {
            "WWW-Authenticate": 'Bearer resource_metadata="https://api.example.com/v1/.well-known/oauth-protected-resource?version=2"'
        }

        # Act
        url = self.discovery._extract_resource_metadata_from_www_auth(response)

        # Assert
        assert (
            url
            == "https://api.example.com/v1/.well-known/oauth-protected-resource?version=2"
        )


class TestDiscoveryURLBuilding:
    """Test construction of discovery URLs with path-aware logic."""

    def setup_method(self):
        self.discovery = OAuth2Discovery()

    def test_root_authorization_server(self):
        # Arrange & Act
        urls = self.discovery._build_discovery_urls("https://auth.example.com")

        expected = [
            "https://auth.example.com/.well-known/oauth-authorization-server",
        ]

        # Assert
        assert urls == expected

    def test_authorization_server_with_path(self):
        # Arrange & Act
        urls = self.discovery._build_discovery_urls("https://auth.example.com/oauth")

        expected = [
            "https://auth.example.com/.well-known/oauth-authorization-server/oauth",
            "https://auth.example.com/.well-known/oauth-authorization-server",
        ]

        # Assert
        assert urls == expected

    def test_authorization_server_with_nested_path(self):
        # Arrange & Act
        urls = self.discovery._build_discovery_urls("https://auth.example.com/v1/oauth")

        expected = [
            "https://auth.example.com/.well-known/oauth-authorization-server/v1/oauth",
            "https://auth.example.com/.well-known/oauth-authorization-server",
        ]

        # Assert
        assert urls == expected

    def test_authorization_server_with_trailing_slash(self):
        # Arrange & Act
        urls = self.discovery._build_discovery_urls("https://auth.example.com/oauth/")

        expected = [
            "https://auth.example.com/.well-known/oauth-authorization-server/oauth",
            "https://auth.example.com/.well-known/oauth-authorization-server",
        ]

        # Assert
        assert urls == expected

    def test_authorization_server_with_port(self):
        # Arrange & Act
        urls = self.discovery._build_discovery_urls(
            "https://auth.example.com:8443/oauth"
        )

        expected = [
            "https://auth.example.com:8443/.well-known/oauth-authorization-server/oauth",
            "https://auth.example.com:8443/.well-known/oauth-authorization-server",
        ]

        # Assert
        assert urls == expected


class TestResourceURLCanonicalization:
    """Test resource URL canonicalization logic in DiscoveryResult."""

    def test_basic_server_url_canonicalization(self):
        # Arrange
        prm = ProtectedResourceMetadata(
            authorization_servers=["https://auth.example.com"]
        )
        asm = AuthorizationServerMetadata(
            issuer="https://auth.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            response_types_supported=["code"],
        )

        result = DiscoveryResult(
            server_url="https://api.example.com/mcp",
            protected_resource_metadata=prm,
            authorization_server_metadata=asm,
            auth_server_url="https://auth.example.com",
        )

        # Act
        resource_url = result.get_resource_url()

        # Assert
        assert resource_url == "https://api.example.com/mcp"

    def test_server_url_with_trailing_slash_normalization(self):
        # Arrange
        prm = ProtectedResourceMetadata(
            authorization_servers=["https://auth.example.com"]
        )
        asm = AuthorizationServerMetadata(
            issuer="https://auth.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            response_types_supported=["code"],
        )

        result = DiscoveryResult(
            server_url="https://api.example.com/mcp/",  # Trailing slash
            protected_resource_metadata=prm,
            authorization_server_metadata=asm,
            auth_server_url="https://auth.example.com",
        )

        # Act
        resource_url = result.get_resource_url()

        # Assert
        assert resource_url == "https://api.example.com/mcp"  # No trailing slash

    def test_case_insensitive_scheme_and_host(self):
        # Arrange
        prm = ProtectedResourceMetadata(
            authorization_servers=["https://auth.example.com"]
        )
        asm = AuthorizationServerMetadata(
            issuer="https://auth.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            response_types_supported=["code"],
        )

        result = DiscoveryResult(
            server_url="HTTPS://API.EXAMPLE.COM/MCP",  # Uppercase
            protected_resource_metadata=prm,
            authorization_server_metadata=asm,
            auth_server_url="https://auth.example.com",
        )

        # Act
        resource_url = result.get_resource_url()

        # Assert
        assert (
            resource_url == "https://api.example.com/MCP"
        )  # Scheme/host lowercase, path preserved

    def test_port_preservation(self):
        # Arrange
        prm = ProtectedResourceMetadata(
            authorization_servers=["https://auth.example.com"]
        )
        asm = AuthorizationServerMetadata(
            issuer="https://auth.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            response_types_supported=["code"],
        )

        result = DiscoveryResult(
            server_url="https://api.example.com:8443/mcp",
            protected_resource_metadata=prm,
            authorization_server_metadata=asm,
            auth_server_url="https://auth.example.com",
        )

        # Act
        resource_url = result.get_resource_url()

        # Assert
        assert resource_url == "https://api.example.com:8443/mcp"


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def setup_method(self):
        self.discovery = OAuth2Discovery()

    def test_malformed_www_authenticate_header(self):
        # Arrange
        response = Mock()
        response.headers = {
            "WWW-Authenticate": "Bearer resource_metadata="  # Missing value
        }

        # Act
        url = self.discovery._extract_resource_metadata_from_www_auth(response)

        # Assert
        assert url is None

    def test_multiple_www_authenticate_headers(self):
        # Arrange
        response = Mock()
        # httpx normalizes multiple headers into a single comma-separated value
        response.headers = {
            "WWW-Authenticate": 'Bearer realm="api", Basic realm="api", Bearer resource_metadata="https://api.example.com/.well-known/oauth-protected-resource"'
        }

        # Act
        url = self.discovery._extract_resource_metadata_from_www_auth(response)

        # Assert
        assert url == "https://api.example.com/.well-known/oauth-protected-resource"

    def test_url_with_special_characters(self):
        # Arrange
        response = Mock()
        response.headers = {
            "WWW-Authenticate": 'Bearer resource_metadata="https://api.example.com/.well-known/oauth-protected-resource?client=test%20app"'
        }

        # Act
        url = self.discovery._extract_resource_metadata_from_www_auth(response)

        # Assert
        assert (
            url
            == "https://api.example.com/.well-known/oauth-protected-resource?client=test%20app"
        )
