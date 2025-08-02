import asyncio

from conduit.client.message_context import MessageContext
from conduit.protocol.base import INTERNAL_ERROR, METHOD_NOT_FOUND
from conduit.protocol.common import EmptyResult, PingRequest
from conduit.protocol.elicitation import ElicitRequest, ElicitResult


class TestRequestHandling:
    async def test_sends_success_on_valid_request(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange: Set up a simple request handler
        handled_requests = []

        async def mock_handler(
            context: MessageContext, request: PingRequest
        ) -> EmptyResult:
            handled_requests.append((context, request))
            return EmptyResult()

        # Register the handler
        coordinator.register_request_handler("ping", mock_handler)

        # Start the coordinator
        await coordinator.start()

        # Register server in both transport and manager
        await mock_transport.add_server(
            "test-server", {"host": "test-server", "port": 8080}
        )
        coordinator.server_manager.register_server("test-server")

        await yield_loop()  # Let message loop start

        # Act: Send a request through the transport
        request_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "ping",
        }

        mock_transport.add_server_message("test-server", request_payload)
        await yield_loop()  # Let coordinator process the message

        # Assert: Handler was called correctly
        assert len(handled_requests) == 1
        context, request = handled_requests[0]
        assert isinstance(context, MessageContext)
        assert context.server_id == "test-server"
        assert request.method == "ping"

        # Assert: Response was sent back to server
        assert "test-server" in mock_transport.sent_messages
        responses = mock_transport.sent_messages["test-server"]
        assert len(responses) == 1

        response = responses[0]
        assert response["result"] == {}
        assert response["id"] == "test-123"

        await yield_loop()  # Let server manager clean up
        # Assert: Request cleaned up
        assert (
            coordinator.server_manager.get_request_from_server(
                "test-server", "test-123"
            )
            is None
        )

    async def test_sends_error_on_parsing_failure_to_protocol(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange: Set up a handler that should NOT be called
        handler_called = False

        async def should_not_be_called(
            context: MessageContext,
            request: ElicitRequest,
        ) -> ElicitResult:
            nonlocal handler_called
            handler_called = True
            # This shouldn't be reached
            return ElicitResult(action="accept", content={})

        coordinator.register_request_handler("elicitation/create", should_not_be_called)

        # Start the coordinator
        await coordinator.start()

        # Register server in both transport and manager
        await mock_transport.add_server(
            "test-server", {"host": "test-server", "port": 8080}
        )
        coordinator.server_manager.register_server("test-server")

        await yield_loop()

        # Valid method but missing required params
        cant_parse_to_protocol = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "elicitation/create",
            "params": {
                # Missing required 'message' and 'requestedSchema' fields
                "some_other_field": "value",
            },
        }

        # Act: Send the malformed ElicitRequest through the transport
        mock_transport.add_server_message("test-server", cant_parse_to_protocol)
        await yield_loop()

        # Assert: Handler was not called
        assert not handler_called

        # Assert: Error response was sent back to server
        assert "test-server" in mock_transport.sent_messages
        responses = mock_transport.sent_messages["test-server"]
        assert len(responses) == 1

        response = responses[0]
        assert response["id"] == "test-123"
        assert "error" in response

        # Assert: No request tracking since parsing failed
        assert (
            coordinator.server_manager.get_request_from_server(
                "test-server", "test-123"
            )
            is None
        )

    async def test_handler_exception_returns_internal_error(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange: Set up a handler that throws an exception
        async def failing_handler(
            context: MessageContext, request: PingRequest
        ) -> EmptyResult:
            raise ValueError("Something went wrong in the handler")

        coordinator.register_request_handler("roots/list", failing_handler)

        # Start the coordinator
        await coordinator.start()

        # Register server in both transport and manager
        await mock_transport.add_server(
            "test-server", {"host": "test-server", "port": 8080}
        )
        coordinator.server_manager.register_server("test-server")

        # Act: Send a valid request that will trigger the exception
        request_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "roots/list",
        }

        mock_transport.add_server_message("test-server", request_payload)
        await yield_loop()

        # Assert: Error response was sent back to server
        assert "test-server" in mock_transport.sent_messages
        responses = mock_transport.sent_messages["test-server"]
        assert len(responses) == 1

        response = responses[0]
        assert response["id"] == "test-123"
        assert "error" in response
        error = response["error"]
        assert error["code"] == INTERNAL_ERROR

    async def test_cancel_request_and_cleanup(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange: Set up a slow handler that we can cancel
        handler_started = asyncio.Event()
        handler_cancelled = False

        async def slow_handler(
            context: MessageContext, request: PingRequest
        ) -> EmptyResult:
            nonlocal handler_cancelled
            handler_started.set()  # Signal that handler has started
            try:
                await asyncio.sleep(10)  # Long-running operation
                return EmptyResult()
            except asyncio.CancelledError:
                handler_cancelled = True
                raise  # Re-raise to properly handle cancellation

        coordinator.register_request_handler("roots/list", slow_handler)

        # Start the coordinator
        await coordinator.start()

        # Register server in both transport and manager
        await mock_transport.add_server(
            "test-server", {"host": "test-server", "port": 8080}
        )
        coordinator.server_manager.register_server("test-server")

        await yield_loop()

        # Act: Send a request that will start the slow handler
        request_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "roots/list",
        }

        mock_transport.add_server_message("test-server", request_payload)
        await yield_loop()

        # Wait for handler to start
        await handler_started.wait()

        # Verify request is being tracked
        assert (
            coordinator.server_manager.get_request_from_server(
                "test-server", "test-123"
            )
            is not None
        )

        # Cancel the request using the coordinator's cancel method
        await coordinator.cancel_request_from_server("test-server", "test-123")

        # Give time for cancellation to propagate
        await yield_loop()

        # Assert: Handler was cancelled
        assert handler_cancelled

        # Assert: Request was cleaned up from tracking
        assert (
            coordinator.server_manager.get_request_from_server(
                "test-server", "test-123"
            )
            is None
        )

        # Assert: No response was sent (cancelled before completion)
        assert "test-server" not in mock_transport.sent_messages

    async def test_returns_method_not_found_on_unregistered_method(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange: Don't register any handlers
        await coordinator.start()

        # Register server in both transport and manager
        await mock_transport.add_server(
            "test-server", {"host": "test-server", "port": 8080}
        )
        coordinator.server_manager.register_server("test-server")

        await yield_loop()

        request_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "roots/list",
        }

        # Act: Send a roots/list request with no handler registered
        mock_transport.add_server_message("test-server", request_payload)
        await yield_loop()

        # Assert: Error response was sent back to server
        assert "test-server" in mock_transport.sent_messages
        responses = mock_transport.sent_messages["test-server"]
        assert len(responses) == 1

        response = responses[0]

        assert response["id"] == "test-123"
        assert "error" in response

        error = response["error"]
        assert error["code"] == METHOD_NOT_FOUND
