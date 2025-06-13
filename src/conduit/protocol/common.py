from typing import Literal

from pydantic import Field

from conduit.protocol.base import (
    Notification,
    ProgressToken,
    Request,
    RequestId,
    Result,
)


class PingRequest(Request):
    """
    Heartbeat to check connection health. Sent by client or server.

    Must be answered promptly to maintain connection.
    """

    method: Literal["ping"] = "ping"


class CancelledNotification(Notification):
    """
    Notifies that a request was cancelled.

    Sent when a request is terminated before execution or completion.
    """

    method: Literal["notifications/cancelled"] = "notifications/cancelled"
    request_id: RequestId = Field(alias="requestId")
    """
    ID of the cancelled request.
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

    total: float | int
    """
    Total expected amount when complete.
    """

    message: str | None = None
    """
    Optional progress description or status message.
    """


class EmptyResult(Result):
    """
    Result that indicates success but carries no data.
    """

    pass
