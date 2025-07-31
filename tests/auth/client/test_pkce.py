import base64
import hashlib

import pytest

from conduit.auth.client.models.errors import (
    AuthorizationError,
    AuthorizationResponseError,
)
from conduit.auth.client.models.flow import AuthorizationResponse
from conduit.auth.client.primitives.pkce import PKCEManager


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
        assert params1.state != params2.state

    def test_validate_authorization_response_state_happy_path(self) -> None:
        # Arrange
        pkce_manager = PKCEManager()
        parameters = pkce_manager.generate_parameters()

        # Act
        response = AuthorizationResponse(
            code="test_code",
            state=parameters.state,
        )

        # Act & Assert - No exception is raised
        pkce_manager.validate_authorization_response(response, parameters.state)

    def test_validate_authorization_response_raises_when_state_mismatch(self) -> None:
        # Arrange
        pkce_manager = PKCEManager()
        parameters = pkce_manager.generate_parameters()
        response = AuthorizationResponse(
            code="test_code",
            state="not_the_same_state",
        )

        # Act & Assert - AuthorizationResponseError is raised
        with pytest.raises(AuthorizationResponseError):
            pkce_manager.validate_authorization_response(response, parameters.state)

    def test_validate_authorization_response_raises_when_code_is_missing(self) -> None:
        # Arrange
        pkce_manager = PKCEManager()
        parameters = pkce_manager.generate_parameters()
        response = AuthorizationResponse(
            state=parameters.state,
        )

        # Act & Assert - AuthorizationResponseError is raised
        with pytest.raises(AuthorizationResponseError):
            pkce_manager.validate_authorization_response(response, parameters.state)

    def test_validate_authorization_response_raises_when_state_is_missing(self) -> None:
        # Arrange
        pkce_manager = PKCEManager()
        parameters = pkce_manager.generate_parameters()
        response = AuthorizationResponse(
            code="test_code",
        )

        # Act & Assert - AuthorizationResponseError is raised
        with pytest.raises(AuthorizationResponseError):
            pkce_manager.validate_authorization_response(response, parameters.state)

    def test_validate_authorization_response_with_error(self) -> None:
        # Arrange
        pkce_manager = PKCEManager()
        params = pkce_manager.generate_parameters()
        error_response = AuthorizationResponse(
            code=None,
            state=params.state,
            error="access_denied",
            error_description="User denied access",
        )

        # Act & Assert
        with pytest.raises(AuthorizationError):
            pkce_manager.validate_authorization_response(error_response, params.state)

    def test_validate_authorization_response_error_with_state_mismatch(self) -> None:
        # Arrange
        pkce_manager = PKCEManager()
        params = pkce_manager.generate_parameters()
        error_response = AuthorizationResponse(
            code=None, state="wrong_state", error="access_denied"
        )

        # Act & Assert - Should raise AuthorizationResponseError for state mismatch
        with pytest.raises(AuthorizationResponseError):
            pkce_manager.validate_authorization_response(error_response, params.state)

    def test_validate_authorization_response_error_without_state(self) -> None:
        # Arrange - Malformed error response missing state
        pkce_manager = PKCEManager()
        params = pkce_manager.generate_parameters()
        error_response = AuthorizationResponse(
            code=None, state=None, error="server_error"
        )

        # Act & Assert - Should still raise AuthorizationError (not validate state)
        with pytest.raises(AuthorizationError):
            pkce_manager.validate_authorization_response(error_response, params.state)
