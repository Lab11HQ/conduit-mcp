import asyncio
from .conftest import BaseSessionTest


class TestMessageProcessing(BaseSessionTest):
    async def test_message_loop_calls_handler_for_each_message(self):
        """Happy path: message loop processes messages by calling the handler."""
        # Arrange: mock the handler method
        handler_calls = []

        async def mock_handler(message):
            handler_calls.append(message.payload)

        self.session._handle_message = mock_handler

        # Act: start the session (which starts the message loop)
        await self.session._start()

        # Act: send a few messages from the server
        self.server.send_message({"method": "notifications/test1"})
        self.server.send_message({"method": "notifications/test2"})
        self.server.send_message({"method": "notifications/test3"})

        await asyncio.sleep(0.01)

        # Act: stop the session
        await self.session.stop()

        # Assert: verify handler was called for each message
        assert len(handler_calls) == 3
        assert handler_calls == [
            {"method": "notifications/test1"},
            {"method": "notifications/test2"},
            {"method": "notifications/test3"},
        ]

    async def test_handler_error_doesnt_stop_loop(self):
        """Error isolation: handler crashes don't kill the message loop."""
        # Arrange: mock the handler method
        handler_calls = []

        async def mock_handler(message):
            handler_calls.append(message.payload)
            # Crash on the second message
            if len(handler_calls) == 2:
                raise ValueError("Handler crashed!")

        self.session._handle_message = mock_handler

        # Act: start the session
        await self.session._start()

        # Act: send messages - second one will crash the handler
        self.server.send_message({"method": "notifications/test1"})
        self.server.send_message({"method": "notifications/crash"})
        self.server.send_message({"method": "notifications/test3"})

        # Act: give the loop time to process
        await asyncio.sleep(0.01)

        # Act: stop the session
        await self.session.stop()

        # Assert: verify all messages were attempted (including the one that crashed)
        assert len(handler_calls) == 3
        assert handler_calls == [
            {"method": "notifications/test1"},
            {"method": "notifications/crash"},
            {"method": "notifications/test3"},
        ]

    async def test_transport_error_stops_loop_and_cleans_up(self):
        """Transport errors stop the loop and trigger proper cleanup."""
        # Arrange: mock the handler method
        handler_calls = []

        async def mock_handler(message):
            handler_calls.append(message.payload)

        self.session._handle_message = mock_handler

        # Act: start the session
        await self.session._start()

        # Act: send a message to confirm loop is running
        self.server.send_message({"method": "notifications/test1"})
        await asyncio.sleep(0.01)  # Let it process

        # Act: simulate transport failure by closing it
        await self.transport.close()

        # Act: give the loop time to detect the failure and shut down
        await asyncio.sleep(0.01)

        # Assert: verify the loop detected the failure and cleaned up
        assert not self.session._running
        assert (
            self.session._message_loop_task is None
            or self.session._message_loop_task.done()
        )

        # Assert: verify we processed the message before the transport failed
        assert len(handler_calls) == 1
        assert handler_calls[0] == {"method": "notifications/test1"}

    async def test_loop_respects_running_flag_on_stop(self):
        """Loop exits cleanly when stop() is called, even with queued messages."""
        # Arrange: mock the handler method
        handler_calls = []

        async def mock_handler(message):
            handler_calls.append(message.payload)

        self.session._handle_message = mock_handler

        # Act: start the session
        await self.session._start()

        # Act: send one message and let it process
        self.server.send_message({"method": "notifications/processed"})
        await asyncio.sleep(0.01)

        # Act: stop the session immediately
        await self.session.stop()

        # Act: queue up more messages after the session is stopped
        self.server.send_message({"method": "notifications/queued1"})
        self.server.send_message({"method": "notifications/queued2"})

        # Assert: verify only the first message was processed
        assert len(handler_calls) == 1
        assert handler_calls[0] == {"method": "notifications/processed"}

        # Assert: verify session is properly stopped
        assert not self.session._running
        assert self.session._message_loop_task is None
