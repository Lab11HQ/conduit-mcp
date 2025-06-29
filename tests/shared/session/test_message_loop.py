import asyncio
from unittest.mock import Mock

from .conftest import BaseSessionTest


class TestMessageLoop(BaseSessionTest):
    async def test_processes_messages_from_transport(self):
        """Message loop reads from transport and calls _handle_message for each."""
        # Arrange: Mock _handle_message to track calls
        handled_messages = []

        async def mock_handle_message(payload):
            handled_messages.append(payload)

        self.session._handle_message = mock_handle_message

        # Act: Start session and send messages
        await self.session.start()

        self.transport.receive_message(
            {"jsonrpc": "2.0", "id": 1, "method": "test/one"}
        )
        self.transport.receive_message(
            {"jsonrpc": "2.0", "id": 2, "method": "test/two"}
        )

        await asyncio.sleep(0.01)  # Let message loop process
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

        await asyncio.sleep(0.01)  # Let loop process all messages
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
        await asyncio.sleep(0.01)

        # Simulate transport failure
        self.transport.simulate_error()
        await asyncio.sleep(0.01)  # Let failure propagate

        # Try to send another message - it shouldn't be processed
        self.transport.receive_message({"jsonrpc": "2.0", "method": "after_crash"})
        await asyncio.sleep(0.01)

        # Assert: Only the first message was processed
        assert len(handled_messages) == 1
        assert handled_messages[0]["method"] == "before_crash"
        # The loop stopped, so "after_crash" was never handled

    async def test_loop_respects_running_flag_on_stop(self):
        """Message loop stops processing when _running flag is set to False."""
        # Arrange: Mock handler to track messages
        handled_messages = []

        async def tracking_handler(payload):
            handled_messages.append(payload)

        self.session._handle_message = tracking_handler

        # Act: Start session, process one message, then stop
        await self.session.start()

        self.transport.receive_message({"jsonrpc": "2.0", "method": "processed"})
        await asyncio.sleep(0.01)  # Let it process

        await self.session.stop()  # This sets _running = False

        # Send more messages after stopping
        self.transport.receive_message({"jsonrpc": "2.0", "method": "ignored"})
        await asyncio.sleep(0.01)

        # Assert: Only the first message was processed
        assert len(handled_messages) == 1
        assert handled_messages[0]["method"] == "processed"

    async def test_loop_always_sets_running_false_on_exit(self):
        """Message loop always sets _running = False when exiting."""
        # Act: Start and force exit via transport error
        await self.session.start()
        assert self.session._running  # Confirm it started

        self.transport.simulate_error()
        await asyncio.sleep(0.01)  # Let cleanup happen

        # Assert: Always cleaned up
        assert not self.session._running

    async def test_loop_calls_resolve_pending_requests_on_exit(self, monkeypatch):
        """Message loop calls _resolve_pending_requests when exiting."""
        # Arrange: Mock the cleanup method
        mock_resolve = Mock()
        monkeypatch.setattr(self.session, "_resolve_pending_requests", mock_resolve)

        # Act: Start and force exit via transport error
        await self.session.start()
        self.transport.simulate_error()
        await asyncio.sleep(0.01)  # Let cleanup happen

        # Assert: Cleanup method was called
        mock_resolve.assert_called_once_with("Message loop terminated")
