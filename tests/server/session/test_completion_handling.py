from unittest.mock import AsyncMock

from conduit.protocol.base import INTERNAL_ERROR, METHOD_NOT_FOUND, Error
from conduit.protocol.completions import (
    CompleteRequest,
    CompleteResult,
    Completion,
    CompletionArgument,
)
from conduit.protocol.prompts import PromptReference
from conduit.server.managers.completions import CompletionNotConfiguredError

from .conftest import ServerSessionTest


class TestComplete(ServerSessionTest):
    async def test_returns_result_from_manager_when_capability_enabled(self):
        """Test successful completion when completions capability is enabled."""
        # Arrange
        self.config.capabilities.completions = True  # Enable completions

        completion = Completion(
            values=["python", "pytest"],
            total=2,
            has_more=False,
        )
        expected_result = CompleteResult(completion=completion)

        # Mock the manager to return success
        self.session.completions.handle_complete = AsyncMock(
            return_value=expected_result
        )

        request = CompleteRequest(
            ref=PromptReference(name="test_prompt"),
            argument=CompletionArgument(name="run_command", value="py"),
        )

        # Act
        result = await self.session._handle_complete(request)

        # Assert
        assert isinstance(result, CompleteResult)
        assert result.completion == completion

        # Verify manager was called
        self.session.completions.handle_complete.assert_awaited_once_with(request)

    async def test_rejects_complete_when_capability_not_set(self):
        """Test error when completions capability is not configured."""
        # Arrange
        self.config.capabilities.completions = False  # No completions capability
        request = CompleteRequest(
            ref=PromptReference(name="test_prompt"),
            argument=CompletionArgument(name="language", value="py"),
        )

        # Act
        result = await self.session._handle_complete(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "Server does not support completion capability"

    async def test_returns_method_not_found_when_handler_not_configured(self):
        """Test error when manager raises CompletionNotConfiguredError."""
        # Arrange
        self.config.capabilities.completions = True  # Enable capability

        # Mock the manager to raise CompletionNotConfiguredError
        self.session.completions.handle_complete = AsyncMock(
            side_effect=CompletionNotConfiguredError("No completion handler registered")
        )

        request = CompleteRequest(
            ref=PromptReference(name="test_prompt"),
            argument=CompletionArgument(name="language", value="py"),
        )

        # Act
        result = await self.session._handle_complete(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "No completion handler registered."

        # Verify manager was called
        self.session.completions.handle_complete.assert_awaited_once_with(request)

    async def test_returns_internal_error_when_manager_raises_exception(self):
        """Test error when manager raises unexpected exception."""
        # Arrange
        self.config.capabilities.completions = True  # Enable capability

        # Mock the manager to raise generic exception
        self.session.completions.handle_complete = AsyncMock(
            side_effect=ValueError("Completion generation failed")
        )

        request = CompleteRequest(
            ref=PromptReference(name="test_prompt"),
            argument=CompletionArgument(name="language", value="py"),
        )

        # Act
        result = await self.session._handle_complete(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR
        assert result.message == "Error generating completions."

        # Verify manager was called
        self.session.completions.handle_complete.assert_awaited_once_with(request)
