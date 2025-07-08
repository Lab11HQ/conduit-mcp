"""JSON-RPC message parsing utilities for MCP protocol.

Handles parsing and validation of JSON-RPC messages into typed MCP objects.
Used by both client and server sessions for consistent message handling.
"""

from typing import Any

from conduit.protocol.base import Error, Notification, Request, Result


class MessageParser:
    """Parses JSON-RPC payloads into typed MCP protocol objects.

    Handles parsing and validation for requests, responses, and notifications
    with proper error handling and type safety.
    """

    def parse_request(self, payload: dict[str, Any]) -> Request | Error:
        """Parse a JSON-RPC request payload into a typed Request object or Error.

        Args:
            payload: Raw JSON-RPC request payload

        Returns:
            Typed Request object on success, or Error for parsing failures
        """
        pass

    def parse_response(
        self, payload: dict[str, Any], original_request: Request
    ) -> Result | Error:
        """Parse JSON-RPC response into typed Result or Error objects.

        Args:
            payload: Raw JSON-RPC response from peer
            original_request: Request that triggered this response

        Returns:
            Typed Result object for success, or Error object for failures
        """
        pass

    def parse_notification(self, payload: dict[str, Any]) -> Notification | None:
        """Parse a JSON-RPC notification payload into a typed Notification object.

        Args:
            payload: Raw JSON-RPC notification payload

        Returns:
            Typed Notification object on success, None for unknown types or parse
            failures
        """
        pass

    def is_valid_request(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a valid JSON-RPC request."""
        pass

    def is_valid_notification(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a valid JSON-RPC notification."""
        pass

    def is_valid_response(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a valid JSON-RPC response."""
        pass
