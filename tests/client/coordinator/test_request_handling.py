import asyncio

from conduit.protocol.base import INTERNAL_ERROR, METHOD_NOT_FOUND
from conduit.protocol.common import EmptyResult, PingRequest
from conduit.protocol.elicitation import ElicitRequest, ElicitResult


class TestRequestHandling:
    """Test request handling in ClientMessageCoordinator."""

    async def test_sends_success_on_valid_request(
        self, coordinator, mock_transport, yield_loop
    ):
        """Test complete happy path: register handler, send request, get response."""
        # Arrange: Set up a simple request handler
        handled_requests = []

        async def mock_handler(request: PingRequest) -> EmptyResult:
            handled_requests.append(request)
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

        mock_transport.add_server_message(request_payload)
        await yield_loop()  # Let coordinator process the message

        # Assert: Handler was called correctly
        assert len(handled_requests) == 1
        request = handled_requests[0]
        assert request.method == "ping"

        # Assert: Response was sent back to server
        assert len(mock_transport.sent_messages) == 1
        response = mock_transport.sent_messages[0]
        assert response["result"] == {}
        assert response["id"] == "test-123"

        # Assert: Request was tracked and cleaned up
        await yield_loop()  # Let server manager clean up
        context = coordinator.server_manager.get_server_context()
        assert len(context.requests_from_server) == 0

    async def test_sends_error_on_parsing_failure_to_protocol(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange: Set up a handler that should NOT be called
        handler_called = False

        async def should_not_be_called(
            request: ElicitRequest,
        ) -> ElicitResult:
            nonlocal handler_called
            handler_called = True
            # This shouldn't be reached
            return ElicitResult(action="accept", content={})

        coordinator.register_request_handler("elicitation/create", should_not_be_called)

        # Start the coordinator (needed for transport setup)
        await coordinator.start()
        await yield_loop()

        # Valid method but missing required URI parameter
        invalid_elicitation_create = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "elicitation/create",
            "params": {
                # Missing required 'message' and 'requestedSchema' fields
                "some_other_field": "value",
            },
        }

        # Act: Send the malformed ElicitRequest through the transport
        mock_transport.add_server_message(invalid_elicitation_create)
        await yield_loop()

        # Assert: Handler was not called
        assert not handler_called

        # Assert: Error response was sent back to server
        assert len(mock_transport.sent_messages) == 1
        response = mock_transport.sent_messages[0]
        assert "error" in response
        assert response["id"] == "test-123"

        # Assert: No request tracking since parsing failed
        context = coordinator.server_manager.get_server_context()
        assert len(context.requests_from_server) == 0

    async def test_handler_exception_returns_internal_error(
        self, coordinator, mock_transport, yield_loop
    ):
        """Test that handler exceptions return INTERNAL_ERROR responses."""

        # Arrange: Set up a handler that throws an exception
        async def failing_handler(request: PingRequest) -> EmptyResult:
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

        mock_transport.add_server_message(request_payload)
        await yield_loop()

        # Assert: Error response was sent back to server
        assert len(mock_transport.sent_messages) == 1
        response = mock_transport.sent_messages[0]
        assert response["id"] == "test-123"
        assert "error" in response

        error = response["error"]
        assert error["code"] == INTERNAL_ERROR

        # Assert: Request was tracked and cleaned up
        await yield_loop()  # Let server manager clean up
        context = coordinator.server_manager.get_server_context()
        assert len(context.requests_from_server) == 0

    async def test_cancel_request_and_cleanup(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange: Set up a slow handler that we can cancel
        handler_started = asyncio.Event()
        handler_cancelled = False

        async def slow_handler(request: PingRequest) -> EmptyResult:
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

        mock_transport.add_server_message(request_payload)
        await yield_loop()

        # Wait for handler to start
        await handler_started.wait()

        # Verify request is being tracked
        context = coordinator.server_manager.get_server_context()
        assert len(context.requests_from_server) == 1

        # Cancel the request using the coordinator's cancel method
        await coordinator.cancel_request_from_server("test-123")

        # Give time for cancellation to propagate
        await yield_loop()

        # Assert: Handler was cancelled
        assert handler_cancelled

        # Assert: Request was cleaned up from tracking
        assert len(context.requests_from_server) == 0

        # Assert: No response was sent (cancelled before completion)
        assert len(mock_transport.sent_messages) == 0

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
        mock_transport.add_server_message(request_payload)
        await yield_loop()

        # Assert: Error response was sent back to server
        assert len(mock_transport.sent_messages) == 1
        response = mock_transport.sent_messages[0]

        assert response["id"] == "test-123"
        assert "error" in response

        error = response["error"]
        assert error["code"] == METHOD_NOT_FOUND
