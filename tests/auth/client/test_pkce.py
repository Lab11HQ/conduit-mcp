import base64
import hashlib

from conduit.auth.client.services.pkce import PKCEManager


class TestPKCEManager:
    def test_generate_parameters_crypto_requirements(self) -> None:
        # Arrange
        pkce_manager = PKCEManager()

        # Act
        params = pkce_manager.generate_parameters()

        # Assert RFC 7636 requirements
        assert 43 <= len(params.code_verifier) <= 128
        assert 43 <= len(params.code_challenge) <= 128
        assert params.code_challenge_method == "S256"

        # Verify code_challenge is base64url(sha256(code_verifier))
        expected_challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(params.code_verifier.encode("ascii")).digest()
            )
            .decode("ascii")
            .rstrip("=")
        )
        assert params.code_challenge == expected_challenge

    def test_generate_parameters_uniqueness(self) -> None:
        # Arrange
        pkce_manager = PKCEManager()

        # Act - Generate multiple parameters
        params1 = pkce_manager.generate_parameters()
        params2 = pkce_manager.generate_parameters()

        # Assert - Each generation is unique
        assert params1.code_verifier != params2.code_verifier
        assert params1.code_challenge != params2.code_challenge
