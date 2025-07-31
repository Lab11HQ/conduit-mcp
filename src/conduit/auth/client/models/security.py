"""Security-related models for OAuth 2.1 authentication.

Contains PKCE parameters and other cryptographic primitives needed
for secure OAuth flows.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PKCEParameters:
    """PKCE (Proof Key for Code Exchange) parameters for OAuth 2.1 security.

    Immutable parameters generated for each authorization flow to prevent
    authorization code interception attacks (RFC 7636).
    """

    code_verifier: str = field()
    code_challenge: str = field()
    code_challenge_method: str = field(default="S256")

    def __post_init__(self) -> None:
        """Validate PKCE parameters meet RFC 7636 requirements."""
        if not (43 <= len(self.code_verifier) <= 128):
            raise ValueError("code_verifier must be 43-128 characters")
        if not (43 <= len(self.code_challenge) <= 128):
            raise ValueError("code_challenge must be 43-128 characters")
        if self.code_challenge_method != "S256":
            raise ValueError("Only S256 code challenge method is supported")
