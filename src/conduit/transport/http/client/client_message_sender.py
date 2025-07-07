from typing import Any

import httpx
from httpx_sse import aconnect_sse

from conduit.protocol.base import PROTOCOL_VERSION
from conduit.transport.http.client.client_stream_manager import ClientStreamManager


class ClientMessageSender:
    """Handles all outbound HTTP requests from client to server.

    Coordinates with ClientStreamManager when server responds with SSE streams.
    Manages the three types of JSON-RPC messages: notifications, responses, requests.
    """

    def __init__(
        self,
        endpoint_url: str,
        http_client: httpx.AsyncClient,
        stream_manager: ClientStreamManager,
    ):
        self._endpoint_url = endpoint_url
        self._http_client = http_client
        self._stream_manager = stream_manager

    async def send_notification(self, notification: dict[str, Any]) -> None:
        """Send a JSON-RPC notification to the server.

        Args:
            notification: JSON-RPC notification object

        Raises:
            ConnectionError: If server doesn't return 202 Accepted
        """
        response = await self._post_message(notification)

        if response.status_code != 202:
            raise ConnectionError(
                f"Server rejected notification: {response.status_code} {response.text}"
            )

    async def send_response(self, response: dict[str, Any]) -> None:
        """Send a JSON-RPC response to the server.

        Args:
            response: JSON-RPC response object

        Raises:
            ConnectionError: If server doesn't return 202 Accepted
        """
        http_response = await self._post_message(response)

        if http_response.status_code != 202:
            raise ConnectionError(
                f"Server rejected response: {http_response.status_code} "
                f"{http_response.text}"
            )

    async def send_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Send a JSON-RPC request to the server.

        Args:
            request: JSON-RPC request object with 'id' field

        Returns:
            dict if server responds with immediate JSON
            None if server responds with SSE stream (response comes via stream)

        Raises:
            ConnectionError: If server returns error status
            ValueError: If request missing 'id' field
        """
        # Extract request ID for stream correlation
        request_id = request.get("id")
        if request_id is None:
            raise ValueError("Request must have 'id' field")

        # Send POST request with both content types accepted
        response = await self._post_message(request)

        # Check response content type
        content_type = response.headers.get("content-type", "").lower()

        if content_type.startswith("application/json"):
            # Immediate JSON response
            if response.status_code != 200:
                raise ConnectionError(
                    f"Server returned error: {response.status_code} {response.text}"
                )
            return response.json()

        elif content_type.startswith("text/event-stream"):
            # SSE stream response - coordinate with stream manager
            sse_response = aconnect_sse(
                self._http_client,
                "POST",
                self._endpoint_url,
                json=request,
                headers=self._get_headers(),
            )

            await self._stream_manager.create_request_stream(
                str(request_id), sse_response
            )

            return None  # Response will come via stream

        else:
            raise ConnectionError(
                f"Unexpected content type from server: {content_type}"
            )

    async def _post_message(self, message: dict[str, Any]) -> httpx.Response:
        """Send a JSON-RPC message via POST request.

        Args:
            message: JSON-RPC message to send

        Returns:
            HTTP response from server
        """
        try:
            response = await self._http_client.post(
                self._endpoint_url, json=message, headers=self._get_headers()
            )
            return response

        except httpx.RequestError as e:
            raise ConnectionError(f"Failed to send message: {e}") from e

    def _get_headers(self) -> dict[str, str]:
        """Get standard headers for MCP HTTP requests."""
        return {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
