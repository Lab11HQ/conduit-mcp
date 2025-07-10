import asyncio

from conduit.protocol.base import INTERNAL_ERROR, METHOD_NOT_FOUND
from conduit.protocol.common import EmptyResult
from conduit.protocol.jsonrpc import Request


class TestRequestHandling:
    """Test request handling in MessageCoordinator."""

    async def test_sends_success_on_valid_request(
        self, coordinator, mock_transport, yield_loop
    ):
        """Test complete happy path: register handler, send request, get response."""
        # Arrange: Set up a simple request handler
        handled_requests = []

        async def mock_handler(client_id: str, request: Request) -> EmptyResult:
            handled_requests.append((client_id, request))
            return EmptyResult()

        # Register the handler
        coordinator.register_request_handler("ping", mock_handler)

        # Start the coordinator
        await coordinator.start()
        await yield_loop()  # Let message loop start

        # Act: Send a request through the transport
        request_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "ping",
        }

        mock_transport.add_client_message("client-1", request_payload)
        await yield_loop()  # Let coordinator process the message

        # Assert: Handler was called correctly
        assert len(handled_requests) == 1
        client_id, request = handled_requests[0]
        assert client_id == "client-1"
        assert request.method == "ping"

        # Assert: Response was sent back to client
        assert "client-1" in mock_transport.sent_messages
        responses = mock_transport.sent_messages["client-1"]
        assert len(responses) == 1

        response = responses[0]
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "test-123"
        assert response["result"] == {}

        # Assert: Client was auto-registered
        assert coordinator.client_manager.get_client("client-1") is not None

        # Assert: Request was tracked and cleaned up
        await yield_loop()  # Let client manager clean up
        client = coordinator.client_manager.get_client("client-1")
        assert len(client.requests_from_client) == 0

    async def test_sends_error_on_parsing_failure_to_protocol(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange: Set up a handler that should NOT be called
        handler_called = False

        async def should_not_be_called(client_id: str, request: Request) -> EmptyResult:
            nonlocal handler_called
            handler_called = True
            return EmptyResult()

        coordinator.register_request_handler("ping", should_not_be_called)

        # Start the coordinator (needed for transport setup)
        await coordinator.start()
        await yield_loop()

        # Not a real MCP method
        cant_parse_to_protocol = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "not-an-mcp-method",
            "params": {"some": "data"},
        }

        # Act: Send the non-existent MCP method payload through the transport
        mock_transport.add_client_message("client-1", cant_parse_to_protocol)
        await yield_loop()

        # Assert: Handler was not called
        assert not handler_called

        # Assert: Error response was sent back to client
        assert "client-1" in mock_transport.sent_messages
        responses = mock_transport.sent_messages["client-1"]
        assert len(responses) == 1

        response = responses[0]
        assert response["jsonrpc"] == "2.0"
        assert "error" in response
        assert response["id"] == "test-123"

        # Assert: Client was still auto-registered
        assert coordinator.client_manager.get_client("client-1") is not None

        # Assert: No request tracking since parsing failed
        client = coordinator.client_manager.get_client("client-1")
        assert len(client.requests_from_client) == 0

    async def test_handler_exception_returns_internal_error(
        self, coordinator, mock_transport, yield_loop
    ):
        """Test that handler exceptions return INTERNAL_ERROR responses."""

        # Arrange: Set up a handler that throws an exception
        async def failing_handler(client_id: str, request: Request) -> EmptyResult:
            raise ValueError("Something went wrong in the handler")

        coordinator.register_request_handler("ping", failing_handler)

        # Start the coordinator
        await coordinator.start()
        await yield_loop()

        # Act: Send a valid request that will trigger the exception
        request_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "ping",
        }

        mock_transport.add_client_message("client-1", request_payload)
        await yield_loop()

        # Assert: Error response was sent back to client
        assert "client-1" in mock_transport.sent_messages
        responses = mock_transport.sent_messages["client-1"]
        assert len(responses) == 1

        response = responses[0]
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "test-123"
        assert "error" in response

        error = response["error"]
        assert error["code"] == INTERNAL_ERROR

        # Assert: Client was registered and request was tracked/cleaned up
        assert coordinator.client_manager.get_client("client-1") is not None
        client = coordinator.client_manager.get_client("client-1")
        assert len(client.requests_from_client) == 0  # Exception cleanup worked

    async def test_cancel_request_and_cleanup(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange: Set up a slow handler that we can cancel
        handler_started = asyncio.Event()
        handler_cancelled = False

        async def slow_handler(client_id: str, request: Request) -> EmptyResult:
            nonlocal handler_cancelled
            handler_started.set()  # Signal that handler has started
            try:
                await asyncio.sleep(10)  # Long-running operation
                return EmptyResult()
            except asyncio.CancelledError:
                handler_cancelled = True
                raise  # Re-raise to properly handle cancellation

        coordinator.register_request_handler("ping", slow_handler)

        # Start the coordinator
        await coordinator.start()
        await yield_loop()

        # Act: Send a request that will start the slow handler
        request_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "ping",
        }

        mock_transport.add_client_message("client-1", request_payload)
        await yield_loop()

        # Wait for handler to start
        await handler_started.wait()

        # Verify request is being tracked
        client = coordinator.client_manager.get_client("client-1")
        assert len(client.requests_from_client) == 1

        # Get the task and cancel it
        task = coordinator.client_manager.get_request_from_client(
            "client-1", "test-123"
        )
        assert task is not None
        task.cancel()

        # Give time for cancellation to propagate
        await yield_loop()

        # Assert: Handler was cancelled
        assert handler_cancelled

        # Assert: Request was cleaned up from tracking
        assert (
            coordinator.client_manager.get_request_from_client("client-1", "test-123")
            is None
        )
        assert len(client.requests_from_client) == 0

        # Assert: No response was sent (cancelled before completion)
        assert "client-1" not in mock_transport.sent_messages

    async def test_returns_method_not_found_on_unregistered_method(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange: Don't register any handlers
        await coordinator.start()
        await yield_loop()

        request_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "ping",
        }

        # Act: Send a ping request with no handler registered
        mock_transport.add_client_message("client-1", request_payload)
        await yield_loop()

        # Assert: Error response was sent back to client
        assert "client-1" in mock_transport.sent_messages
        responses = mock_transport.sent_messages["client-1"]
        assert len(responses) == 1

        response = responses[0]

        assert response["id"] == "test-123"
        assert "error" in response

        error = response["error"]
        assert error["code"] == METHOD_NOT_FOUND
