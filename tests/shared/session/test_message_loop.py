import asyncio

from conduit.protocol.base import Error
from conduit.protocol.common import PingRequest

from .conftest import BaseSessionTest


class TestMessageLoop(BaseSessionTest):
    _default_yield_time = 0.01

    async def test_processes_messages_from_transport(self):
        """Message loop reads from transport and calls _handle_message for each."""
        # Arrange: Mock _handle_message to track calls
        handled_messages = []

        async def tracking_handler(payload):
            handled_messages.append(payload)

        self.session._handle_message = tracking_handler

        # Act: Start session and send messages
        await self.session.start()

        self.transport.receive_message(
            {"jsonrpc": "2.0", "id": 1, "method": "test/one"}
        )
        self.transport.receive_message(
            {"jsonrpc": "2.0", "id": 2, "method": "test/two"}
        )

        await self.yield_to_event_loop()
        await self.session.stop()

        # Assert: Both messages were handled
        assert len(handled_messages) == 2
        assert handled_messages[0] == {"jsonrpc": "2.0", "id": 1, "method": "test/one"}
        assert handled_messages[1] == {"jsonrpc": "2.0", "id": 2, "method": "test/two"}

    async def test_handler_error_doesnt_stop_loop(self):
        """Individual message handling errors don't crash the message loop."""
        # Arrange: Mock handler that crashes on the second message
        handled_messages = []

        async def crashing_handler(payload):
            handled_messages.append(payload)
            if len(handled_messages) == 2:
                raise ValueError("Handler crashed!")

        self.session._handle_message = crashing_handler

        # Act: Start session and send messages
        await self.session.start()

        self.transport.receive_message({"jsonrpc": "2.0", "method": "first"})
        self.transport.receive_message({"jsonrpc": "2.0", "method": "crash"})
        self.transport.receive_message({"jsonrpc": "2.0", "method": "third"})

        await self.yield_to_event_loop()
        await self.session.stop()

        # Assert: All messages were attempted, loop kept running
        assert len(handled_messages) == 3
        assert handled_messages[0]["method"] == "first"
        assert handled_messages[1]["method"] == "crash"  # This one crashed
        assert handled_messages[2]["method"] == "third"  # But loop continued

    async def test_transport_error_stops_message_processing(self):
        """Transport errors stop the message loop from processing new messages."""
        # Arrange
        handled_messages = []

        async def tracking_handler(payload):
            handled_messages.append(payload)

        self.session._handle_message = tracking_handler

        # Act: Process a message, then simulate transport failure
        await self.session.start()

        self.transport.receive_message({"jsonrpc": "2.0", "method": "before_crash"})
        await self.yield_to_event_loop()

        # Simulate transport failure
        self.transport.simulate_error()
        await self.yield_to_event_loop()

        # Assert: Message was processed before failure
        assert len(handled_messages) == 1
        assert handled_messages[0]["method"] == "before_crash"

        # Assert: Session stopped due to transport error
        assert not self.session._running

    async def test_loop_respects_stop_call(self):
        """Message loop stops processing when _running flag is set to False."""
        # Arrange: Mock handler to track messages
        handled_messages = []

        async def tracking_handler(payload):
            handled_messages.append(payload)

        self.session._handle_message = tracking_handler

        # Act: Start session, process one message, then stop
        await self.session.start()

        self.transport.receive_message({"jsonrpc": "2.0", "method": "processed"})
        await self.yield_to_event_loop()

        await self.session.stop()  # This sets _running = False

        # Send more messages after stopping
        self.transport.receive_message({"jsonrpc": "2.0", "method": "ignored"})
        await self.yield_to_event_loop()

        # Assert: Only the first message was processed
        assert len(handled_messages) == 1
        assert handled_messages[0]["method"] == "processed"

    async def test_loop_always_sets_running_false_on_exit(self):
        """Message loop always sets _running = False when exiting."""
        # Act: Start and force exit via transport error
        await self.session.start()
        assert self.session._running  # Confirm it started

        self.transport.simulate_error()
        await self.yield_to_event_loop()

        # Assert: Always cleaned up
        assert not self.session._running

    async def test_transport_failure_resolves_pending_requests(self):
        """Transport failure resolves pending requests with connection error."""
        # Arrange: Create a pending request
        await self.session.start()

        request_task = asyncio.create_task(
            self.session.send_request(PingRequest(), timeout=10.0)
        )

        # Wait for request to be sent (so it's pending)
        await self.wait_for_sent_message("ping")
        assert len(self.session._pending_requests) == 1

        # Act: Simulate transport failure
        self.transport.simulate_error()
        await self.yield_to_event_loop()

        # Assert: Pending request was resolved with error
        assert len(self.session._pending_requests) == 0
        assert request_task.done()

        error = request_task.result()
        assert isinstance(error, Error)
        assert "connection closed" in error.message.lower()
