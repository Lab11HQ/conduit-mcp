"""PKCE (Proof Key for Code Exchange) manager for OAuth 2.1 security.

Implements RFC 7636 PKCE parameters generation and validation to prevent
authorization code interception attacks. This is required for OAuth 2.1.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import string

from conduit.auth.client.models.errors import PKCEError
from conduit.auth.client.models.security import PKCEParameters


class PKCEManager:
    """Manages PKCE parameter generation for OAuth 2.1 flows.

    PKCE (Proof Key for Code Exchange) is a security extension that prevents
    authorization code interception attacks by requiring clients to prove
    they initiated the authorization request.

    This implementation follows RFC 7636 requirements:
    - Uses S256 code challenge method (SHA256 + base64url)
    - Generates cryptographically secure code verifiers
    """

    def generate_parameters(self) -> PKCEParameters:
        """Generate new PKCE parameters for an authorization flow.

        Creates a cryptographically secure code verifier and derives the
        corresponding code challenge using SHA256.

        Returns:
            PKCEParameters: Immutable PKCE parameters for the authorization flow

        Raises:
            PKCEError: If parameter generation fails
        """
        try:
            code_verifier = self._generate_code_verifier()
            code_challenge = self._generate_code_challenge(code_verifier)

            return PKCEParameters(
                code_verifier=code_verifier,
                code_challenge=code_challenge,
                code_challenge_method="S256",
            )

        except Exception as e:
            raise PKCEError(f"Failed to generate PKCE parameters: {e}") from e

    def _generate_code_verifier(self) -> str:
        """Generate a cryptographically secure code verifier.

        RFC 7636 Section 4.1: code verifier must be 43-128 characters long
        and use only unreserved characters:
            [A-Z] / [a-z] / [0-9] / "-" / "." / "_" / "~"

        Returns:
            A 128-character code verifier (maximum length for best security)
        """
        alphabet = string.ascii_letters + string.digits + "-._~"
        return "".join(secrets.choice(alphabet) for _ in range(128))

    def _generate_code_challenge(self, code_verifier: str) -> str:
        """Generate code challenge from code verifier using S256 method.

        RFC 7636 Section 4.2: For S256, the code challenge is:
        BASE64URL-ENCODE(SHA256(ASCII(code_verifier)))

        Args:
            code_verifier: The code verifier to hash

        Returns:
            Base64url-encoded SHA256 hash of the code verifier
        """
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return challenge
