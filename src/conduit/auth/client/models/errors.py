"""Exception hierarchy for OAuth 2.1 authentication errors.

Provides specific exception types for different failure modes to enable
precise error handling and recovery strategies.
"""

from __future__ import annotations


class OAuth2Error(Exception):
    """Base exception for all OAuth 2.1 related errors."""

    pass


class DiscoveryError(OAuth2Error):
    """Raised when OAuth server discovery fails."""

    pass


class ProtectedResourceMetadataError(DiscoveryError):
    """Raised when Protected Resource Metadata discovery fails."""

    pass


class AuthorizationServerMetadataError(DiscoveryError):
    """Raised when Authorization Server Metadata discovery fails."""

    pass


class RegistrationError(OAuth2Error):
    """Raised when dynamic client registration fails."""

    pass


class TokenError(OAuth2Error):
    """Raised when token operations fail."""

    pass


class TokenRefreshError(TokenError):
    """Raised when token refresh fails."""

    pass


class TokenExchangeError(TokenError):
    """Raised when authorization code to token exchange fails."""

    pass


class AuthorizationError(OAuth2Error):
    """Raised when user authorization fails."""

    pass


class AuthorizationResponseError(OAuth2Error):
    """Raised when authorization response is malformed or invalid."""

    pass


class UserAuthCancelledError(AuthorizationError):
    """Raised when user cancels the authorization flow."""

    pass


class PKCEError(OAuth2Error):
    """Raised when PKCE parameter generation or validation fails."""

    pass


class AuthorizationCallbackError(OAuth2Error):
    """Raised when authorization server callback data is malformed or invalid.

    This indicates the authorization server sent an invalid callback URL,
    not that our callback handling code failed.
    """

    pass


class StateValidationError(AuthorizationCallbackError):
    """Raised when OAuth state parameter validation fails.

    This indicates either a missing state parameter or a state mismatch,
    which could indicate a CSRF attack or authorization server issue.
    """

    pass
