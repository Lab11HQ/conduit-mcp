import asyncio

from conduit.protocol.base import Error
from conduit.protocol.common import PingRequest

from .conftest import BaseSessionTest


class TestMessageLoop(BaseSessionTest):
    _default_yield_time = 0.01

    async def test_processes_messages_from_transport(self):
        """Message loop reads from transport and calls _handle_message for each."""
        # Arrange
        handled_messages = []

        async def tracking_handler(payload):
            handled_messages.append(payload)

        self.session._handle_message = tracking_handler

        # Act
        await self.session.start()
        self.transport.receive_message(
            {"jsonrpc": "2.0", "id": 1, "method": "test/one"}
        )
        self.transport.receive_message(
            {"jsonrpc": "2.0", "id": 2, "method": "test/two"}
        )

        await self.yield_to_event_loop()
        await self.session.stop()

        # Assert
        assert len(handled_messages) == 2
        assert handled_messages[0] == {"jsonrpc": "2.0", "id": 1, "method": "test/one"}
        assert handled_messages[1] == {"jsonrpc": "2.0", "id": 2, "method": "test/two"}

    async def test_handler_error_doesnt_stop_loop(self):
        """Individual message handling errors don't crash the message loop."""
        # Arrange
        handled_messages = []

        async def crashing_handler(payload):
            handled_messages.append(payload)
            if len(handled_messages) == 2:
                raise ValueError("Handler crashed!")

        self.session._handle_message = crashing_handler

        # Act
        await self.session.start()

        self.transport.receive_message({"jsonrpc": "2.0", "method": "first"})
        self.transport.receive_message({"jsonrpc": "2.0", "method": "crash"})
        self.transport.receive_message({"jsonrpc": "2.0", "method": "third"})

        await self.yield_to_event_loop()
        await self.session.stop()

        # Assert
        assert len(handled_messages) == 3
        assert handled_messages[0]["method"] == "first"
        assert handled_messages[1]["method"] == "crash"
        assert handled_messages[2]["method"] == "third"

    async def test_transport_error_stops_message_loop(self):
        """Transport errors stop the message loop from processing new messages."""
        # Arrange
        handled_messages = []

        async def tracking_handler(payload):
            handled_messages.append(payload)

        self.session._handle_message = tracking_handler

        # Act
        await self.session.start()

        self.transport.receive_message({"jsonrpc": "2.0", "method": "before_crash"})
        await self.yield_to_event_loop()

        # Simulate transport failure
        self.transport.simulate_error()
        await self.yield_to_event_loop()

        # Assert
        assert len(handled_messages) == 1
        assert handled_messages[0]["method"] == "before_crash"

        # Assert
        assert not self.session.running

    async def test_loop_respects_stop_call(self):
        """Message loop stops processing when session is stopped."""
        # Arrange
        handled_messages = []

        async def tracking_handler(payload):
            handled_messages.append(payload)

        self.session._handle_message = tracking_handler

        # Act
        await self.session.start()

        self.transport.receive_message({"jsonrpc": "2.0", "method": "processed"})
        await self.yield_to_event_loop()

        await self.session.stop()

        # Send more messages after stopping
        self.transport.receive_message({"jsonrpc": "2.0", "method": "ignored"})
        await self.yield_to_event_loop()

        # Assert
        assert len(handled_messages) == 1
        assert handled_messages[0]["method"] == "processed"

    async def test_transport_failure_resolves_pending_requests(self):
        """Transport failure resolves pending requests with connection error.

        This test ensures the `on_done` callback is called on the message loop
        task and that it resolves pending requests.
        """
        # Arrange
        await self.session.start()

        request_task = asyncio.create_task(
            self.session.send_request(PingRequest(), timeout=10.0)
        )

        await self.wait_for_sent_message("ping")
        assert len(self.session._pending_requests) == 1

        # Act
        self.transport.simulate_error()
        await self.yield_to_event_loop()

        # Assert
        assert len(self.session._pending_requests) == 0
        assert request_task.done()

        error = request_task.result()
        assert isinstance(error, Error)
        assert "request failed" in error.message.lower()
