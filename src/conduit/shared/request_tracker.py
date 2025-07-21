import asyncio

from conduit.protocol.base import INTERNAL_ERROR, Error, Request, Result

RequestId = str | int


class RequestTracker:
    """
    Used to track requests between peers.

    This is used by the ServerManager to track client requests and used by the client
    manager to track server requests.
    """

    def __init__(self):
        # peer_id -> request_id -> (request, future/task)
        self._outbound_requests: dict[
            str, dict[RequestId, tuple[Request, asyncio.Future[Result | Error]]]
        ] = {}
        self._inbound_requests: dict[
            str, dict[RequestId, tuple[Request, asyncio.Task[None]]]
        ] = {}

    def _ensure_peer_tracking(self, peer_id: str) -> None:
        """Ensure tracking dicts exist for a peer."""
        if peer_id not in self._outbound_requests:
            self._outbound_requests[peer_id] = {}
        if peer_id not in self._inbound_requests:
            self._inbound_requests[peer_id] = {}

    # ==================
    # COMMANDS
    # ==================

    def track_outbound_request(
        self,
        peer_id: str,
        request_id: RequestId,
        request: Request,
        future: asyncio.Future[Result | Error],
    ) -> None:
        """Track a request we are sending to a specific peer.

        Args:
            peer_id: The ID of the peer we are sending the request to.
            request_id: The ID of the request.
            request: The MCP request to send.
            future: A future that will be resolved with the result or error of the
                request.
        """
        self._ensure_peer_tracking(peer_id)
        self._outbound_requests[peer_id][request_id] = (request, future)

    def track_inbound_request(
        self,
        peer_id: str,
        request_id: RequestId,
        request: Request,
        task: asyncio.Task[None],
    ) -> None:
        """Track a request we received from a specific peer.

        Args:
            peer_id: The ID of the peer we received the request from.
            request_id: The ID of the request.
            request: The MCP request we received.
            task: A task that will be completed when the request is processed.
        """
        self._ensure_peer_tracking(peer_id)
        self._inbound_requests[peer_id][request_id] = (request, task)

    def resolve_outbound_request(
        self, peer_id: str, request_id: RequestId, result_or_error: Result | Error
    ) -> None:
        """Resolve a pending outbound request for a specific peer.

        Safe to call multiple times.

        Args:
            peer_id: The ID of the peer we are resolving the request for.
            request_id: The ID of the request.
            result_or_error: The result or error to resolve the request with.
        """
        peer_requests = self._outbound_requests.get(peer_id, {})
        request_future_tuple = peer_requests.pop(request_id, None)
        if request_future_tuple:
            _, future = request_future_tuple
            if not future.done():
                future.set_result(result_or_error)

    def cancel_inbound_request(self, peer_id: str, request_id: RequestId) -> None:
        """Cancel an inbound request from a specific peer.

        Safe to call multiple times.

        Args:
            peer_id: The ID of the peer we are canceling the request for.
            request_id: The ID of the request.
        """
        peer_requests = self._inbound_requests.get(peer_id, {})
        request_task_tuple = peer_requests.pop(request_id, None)
        if request_task_tuple:
            _, task = request_task_tuple
            task.cancel()

    def cleanup_peer(self, peer_id: str) -> None:
        """Clean up all requests for a specific peer and remove it from tracking.

        Safe to call multiple times.

        Args:
            peer_id: The ID of the peer we are cleaning up the requests for.
        """
        # Cancel all inbound requests
        inbound_request_ids = self.get_peer_inbound_request_ids(peer_id)
        for request_id in inbound_request_ids:
            self.cancel_inbound_request(peer_id, request_id)

        # Resolve all outbound requests with errors
        outbound_request_ids = self.get_peer_outbound_request_ids(peer_id)
        for request_id in outbound_request_ids:
            error = Error(
                code=INTERNAL_ERROR,
                message="Resolved internally by request tracker.",
            )
            self.resolve_outbound_request(peer_id, request_id, error)

        # Remove empty peer entries
        self._outbound_requests.pop(peer_id, None)
        self._inbound_requests.pop(peer_id, None)

    def cleanup_all_peers(self) -> None:
        """Clean up all peers and their requests."""
        # Clean up each peer individually
        peer_ids = self.get_peer_ids()
        for peer_id in peer_ids:
            self.cleanup_peer(peer_id)

    def remove_outbound_request(self, peer_id: str, request_id: RequestId) -> None:
        """Remove an outbound request from tracking.

        Args:
            peer_id: The ID of the peer we are removing the request for.
            request_id: The ID of the request.
        """
        error = Error(
            code=INTERNAL_ERROR,
            message="Request removed from tracking.",
        )
        self.resolve_outbound_request(peer_id, request_id, error)

    def remove_inbound_request(self, peer_id: str, request_id: RequestId) -> None:
        """Removes an inbound request from tracking and cancels it.

        Args:
            peer_id: The ID of the peer we are removing the request for.
            request_id: The ID of the request.
        """
        self.cancel_inbound_request(peer_id, request_id)

    # ==================
    # QUERIES
    # ==================

    def get_outbound_request(
        self, peer_id: str, request_id: RequestId
    ) -> tuple[Request, asyncio.Future[Result | Error]] | None:
        """Get a pending outbound request for a specific peer.

        Args:
            peer_id: The ID of the peer we are getting the request for.
            request_id: The ID of the request.
        """
        peer_requests = self._outbound_requests.get(peer_id, {})
        return peer_requests.get(request_id)

    def get_inbound_request(
        self, peer_id: str, request_id: RequestId
    ) -> tuple[Request, asyncio.Task[None]] | None:
        """Get a pending inbound request without removing it.

        Args:
            peer_id: The ID of the peer we are getting the request for.
            request_id: The ID of the request.
        """
        peer_requests = self._inbound_requests.get(peer_id, {})
        return peer_requests.get(request_id)

    def get_peer_ids(self) -> list[str]:
        """Get all peer IDs that have tracked requests.

        For example, find all servers we are tracking requests for.
        """
        peer_ids = set(self._outbound_requests.keys()) | set(
            self._inbound_requests.keys()
        )
        return list(peer_ids)

    def get_peer_outbound_request_ids(self, peer_id: str) -> list[RequestId]:
        """Get all IDs for requests we sent to a specific peer.

        Args:
            peer_id: The ID of the peer we sent requests to.

        Returns:
            Request IDs we sent to the peer.
        """
        return list(self._outbound_requests.get(peer_id, {}).keys())

    def get_peer_inbound_request_ids(self, peer_id: str) -> list[RequestId]:
        """Get all IDs for requests we received from a specific peer.

        Args:
            peer_id: The ID of the peer we received requests from.

        Returns:
            IDs for requests we received from the peer.
        """
        return list(self._inbound_requests.get(peer_id, {}).keys())
