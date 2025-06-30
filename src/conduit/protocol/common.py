"""
Common MCP message types used across different protocol areas.

This module contains the fundamental message types that appear throughout
MCP communication - notifications for progress updates and cancellations,
ping requests for connection health, and empty results for operations
that succeed without returning data.

These types form the operational backbone of MCP sessions. Progress
notifications keep long-running operations responsive, cancellation
notifications provide clean termination, pings maintain connection health,
and empty results acknowledge success without unnecessary payload.

Unlike domain-specific types (tools, resources, etc.), these messages
handle the mechanical aspects of protocol communication.
"""

from typing import Literal

from pydantic import Field

from conduit.protocol.base import (
    Notification,
    ProgressToken,
    Request,
    RequestId,
    Result,
)


class CancelledNotification(Notification):
    """
    Sent by either side to cancel a previous request.

    Receivers should cancel any ongoing work related to the request.
    """

    method: Literal["notifications/cancelled"] = "notifications/cancelled"
    request_id: RequestId = Field(alias="requestId")
    """
    ID of the request to cancel.
    """

    reason: str | None = None
    """
    Optional explanation for the cancellation.
    """


class ProgressNotification(Notification):
    """
    Reports progress on a long-running operation. Typically sent by servers.

    Links to a request via its progress_token.
    """

    method: Literal["notifications/progress"] = "notifications/progress"
    progress_token: ProgressToken = Field(alias="progressToken")
    """
    Token identifying the operation being tracked.
    """

    progress: float | int
    """
    Current progress amount.
    """

    total: float | int | None = None
    """
    Total expected amount when complete.
    """

    message: str | None = None
    """
    Optional progress description or status message.
    """


class PingRequest(Request):
    """
    Heartbeat to check connection health. Sent by client or server.

    Must be answered promptly to maintain connection.
    """

    method: Literal["ping"] = "ping"

    @classmethod
    def expected_result_type(cls) -> type["EmptyResult"]:
        return EmptyResult


class EmptyResult(Result):
    """
    Result that indicates success but carries no data.
    """

    pass
