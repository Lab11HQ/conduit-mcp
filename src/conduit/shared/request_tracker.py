import asyncio

from conduit.protocol.base import Error, Request, Result

RequestId = str | int


class RequestTracker:
    def __init__(self):
        self._inbound_requests: dict[RequestId, Request] = {}
        self._outbound_requests: dict[RequestId, asyncio.Future[Result | Error]] = {}

    def track_inbound_request(self, request_id: RequestId, request: Request):
        pass

    def get_inbound_request(self, request_id: RequestId) -> Request | None:
        pass

    def untrack_inbound_request(self, request_id: RequestId):
        pass

    def track_outbound_request(
        self, request_id: RequestId, future: asyncio.Future[Result | Error]
    ):
        pass

    def get_outbound_request(
        self, request_id: RequestId
    ) -> asyncio.Future[Result | Error] | None:
        pass

    def untrack_outbound_request(self, request_id: RequestId):
        pass

    def cleanup_all_requests(self) -> None:
        pass
