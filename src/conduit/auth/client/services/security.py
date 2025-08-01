"""Security utilities for OAuth 2.1 flows.

Provides cryptographically secure parameter generation and validation
for OAuth security mechanisms including state parameters and URI validation.
"""

from __future__ import annotations

import secrets
import string
from urllib.parse import urlparse

from conduit.auth.client.models.errors import StateValidationError


def generate_state() -> str:
    """Generate cryptographically secure state parameter.

    The state parameter provides CSRF protection by ensuring the callback
    matches the original authorization request.

    Returns:
        Cryptographically secure random state string (32 characters)
    """
    # Generate 32 characters of URL-safe random data
    alphabet = string.ascii_letters + string.digits + "-._~"
    return "".join(secrets.choice(alphabet) for _ in range(32))


def validate_state(expected: str, actual: str) -> None:
    """Validate state parameter matches expected value.

    Args:
        expected: State parameter from original authorization request
        actual: State parameter from callback URL

    Raises:
        StateValidationError: If state parameters don't match
    """
    if not secrets.compare_digest(expected, actual):
        raise StateValidationError("State parameter mismatch - possible CSRF attack")


def validate_redirect_uri(uri: str) -> bool:
    """Validate redirect URI meets OAuth 2.1 security requirements.

    Args:
        uri: Redirect URI to validate

    Returns:
        True if URI is valid for OAuth 2.1
    """
    try:
        parsed = urlparse(uri)
        # Must be HTTPS or localhost
        return parsed.scheme == "https" or (
            parsed.scheme == "http" and parsed.hostname == "localhost"
        )
    except Exception:
        return False
