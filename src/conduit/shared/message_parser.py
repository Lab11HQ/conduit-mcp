"""JSON-RPC message parsing utilities for MCP protocol.

Handles parsing and validation of JSON-RPC messages into typed MCP objects.
Used by both client and server sessions for consistent message handling.
"""

from typing import Any

from conduit.protocol.base import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    Error,
    Notification,
    Request,
    Result,
)
from conduit.protocol.unions import NOTIFICATION_CLASSES, REQUEST_CLASSES


class MessageParser:
    """Parses JSON-RPC payloads into typed MCP protocol objects.

    Handles parsing and validation for requests, responses, and notifications
    with proper error handling and type safety.
    """

    # ================================
    # Request parsing
    # ================================

    def is_valid_request(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a valid JSON-RPC request."""
        id_value = payload.get("id")
        has_valid_id = (
            id_value is not None
            and isinstance(id_value, (int, str))
            and not isinstance(id_value, bool)  # Exclude booleans explicitly
        )
        return "method" in payload and has_valid_id

    def parse_request(self, payload: dict[str, Any]) -> Request | Error:
        """Parse a JSON-RPC request payload into a typed Request object or Error.

        Returns an Error object for any parsing failures instead of raising exceptions.

        Args:
            payload: Raw JSON-RPC request payload

        Returns:
            Typed Request object on success, or Error for parsing failures
        """
        method = payload["method"]
        request_class = REQUEST_CLASSES.get(method)

        if request_class is None:
            return Error(code=METHOD_NOT_FOUND, message=f"Unknown method: {method}")

        try:
            return request_class.from_protocol(payload)
        except Exception as e:
            return Error(
                code=INVALID_PARAMS,
                message=f"Failed to deserialize {method} request: {str(e)}",
                data={
                    "id": payload.get("id", "unknown"),
                    "method": method,
                    "params": payload.get("params", {}),
                },
            )

    # ================================
    # Response parsing
    # ================================

    def is_valid_response(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a valid JSON-RPC response."""
        id_value = payload.get("id")
        has_valid_id = (
            id_value is not None
            and isinstance(id_value, (int, str))
            and not isinstance(id_value, bool)
        )
        has_result = "result" in payload
        has_error = "error" in payload
        has_exactly_one_response_field = has_result ^ has_error

        return has_valid_id and has_exactly_one_response_field

    def parse_response(
        self, payload: dict[str, Any], original_request: Request
    ) -> Result | Error:
        """Parse JSON-RPC response into typed Result or Error objects.

        If we can't parse the response, we return an error.

        Args:
            payload: Raw JSON-RPC response from peer.
            original_request: Request that triggered this response.

        Returns:
            Typed Result object for success, or Error object for failures.
        """
        if "result" in payload:
            try:
                result_type = original_request.expected_result_type()
                return result_type.from_protocol(payload)
            except Exception as e:
                return Error(
                    code=INTERNAL_ERROR,
                    message=f"Failed to parse {result_type.__name__} response",
                    data={
                        "expected_type": result_type.__name__,
                        "full_response": payload,
                        "parse_error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
        else:
            try:
                return Error.from_protocol(payload)
            except Exception as e:
                return Error(
                    code=INTERNAL_ERROR,
                    message="Failed to parse response",
                    data={
                        "full_response": payload,
                        "parse_error": str(e),
                        "error_type": type(e).__name__,
                    },
                )

    # ================================
    # Notification parsing
    # ================================

    def parse_notification(self, payload: dict[str, Any]) -> Notification | None:
        """Parse a JSON-RPC notification payload into a typed Notification object.

        Returns None for unknown notification types since notifications are
        fire-and-forget.

        Args:
            payload: Raw JSON-RPC notification payload

        Returns:
            Typed Notification object on success, None for unknown types or parse
            failures
        """
        method = payload["method"]
        notification_class = NOTIFICATION_CLASSES.get(method)

        if notification_class is None:
            print(f"Unknown notification method: {method}")
            return None

        try:
            return notification_class.from_protocol(payload)
        except Exception as e:
            print(f"Failed to deserialize {method} notification: {e}")
            return None

    def is_valid_notification(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a valid JSON-RPC notification."""
        return "method" in payload and "id" not in payload
