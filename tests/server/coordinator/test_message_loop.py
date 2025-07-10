import asyncio

import pytest

from conduit.protocol.base import Error
from conduit.protocol.common import PingRequest


class TestMessageLoop:
    async def test_processes_messages_from_transport(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange
        handled_messages = []

        async def tracking_handler(client_message):
            handled_messages.append((client_message.client_id, client_message.payload))

        coordinator._handle_client_message = tracking_handler

        # Act
        await coordinator.start()
        mock_transport.add_client_message(
            "client1", {"jsonrpc": "2.0", "id": 1, "method": "test/one"}
        )
        mock_transport.add_client_message(
            "client2", {"jsonrpc": "2.0", "id": 2, "method": "test/two"}
        )

        await yield_loop()
        await coordinator.stop()

        # Assert
        assert len(handled_messages) == 2
        assert handled_messages[0] == (
            "client1",
            {"jsonrpc": "2.0", "id": 1, "method": "test/one"},
        )
        assert handled_messages[1] == (
            "client2",
            {"jsonrpc": "2.0", "id": 2, "method": "test/two"},
        )

    async def test_handler_error_does_not_stop_loop(
        self, coordinator, mock_transport, yield_loop
    ):
        """Individual message handling errors don't crash the message loop."""
        # Arrange
        handled_messages = []

        async def crashing_handler(client_message):
            handled_messages.append((client_message.client_id, client_message.payload))
            if len(handled_messages) == 2:
                raise ValueError("Handler crashed!")

        coordinator._handle_client_message = crashing_handler

        # Act
        await coordinator.start()

        mock_transport.add_client_message(
            "client1", {"jsonrpc": "2.0", "method": "first"}
        )
        mock_transport.add_client_message(
            "client2", {"jsonrpc": "2.0", "method": "crash"}
        )
        mock_transport.add_client_message(
            "client3", {"jsonrpc": "2.0", "method": "third"}
        )

        await yield_loop()
        await coordinator.stop()

        # Assert
        assert len(handled_messages) == 3
        assert handled_messages[0][1]["method"] == "first"
        assert (
            handled_messages[1][1]["method"] == "crash"
        )  # This one crashed the handler
        assert handled_messages[2][1]["method"] == "third"  # But loop continued

    async def test_transport_error_stops_message_loop(
        self, coordinator, mock_transport, yield_loop
    ):
        """Transport errors stop the message loop from processing new messages."""
        # Arrange
        handled_messages = []

        async def tracking_handler(client_message):
            handled_messages.append((client_message.client_id, client_message.payload))

        coordinator._handle_client_message = tracking_handler

        # Act
        await coordinator.start()

        mock_transport.add_client_message(
            "client1", {"jsonrpc": "2.0", "method": "before_crash"}
        )
        await yield_loop()

        # Simulate transport failure
        mock_transport.simulate_error()
        await yield_loop()

        # Assert
        assert len(handled_messages) == 1
        assert handled_messages[0][1]["method"] == "before_crash"
        assert not coordinator.running

    async def test_done_callback_cleans_up_client_state(
        self, coordinator, mock_transport, client_manager, yield_loop
    ):
        # Arrange
        await coordinator.start()

        # Create mock in-flight tasks and pending request futures
        task1 = asyncio.create_task(asyncio.sleep(10))
        future1 = asyncio.Future()

        # Set up clients with both types of requests
        client_manager.register_client("client1")
        client_context = client_manager.get_client("client1")

        client_context.requests_from_client["req1"] = task1

        ping_request = PingRequest()
        client_context.requests_to_client["ping1"] = (ping_request, future1)

        assert client_manager.client_count() == 1

        # Act - simulate transport failure (unexpected exit)
        mock_transport.simulate_error()
        await yield_loop()

        # Assert - all client state cleaned up
        assert not coordinator.running
        assert client_manager.client_count() == 0
        with pytest.raises(asyncio.CancelledError):
            await task1

        # Be explicit about error resolution
        assert future1.done()
        error = future1.result()
        assert isinstance(error, Error)
        assert "disconnected" in error.message.lower()

    async def test_loop_respects_stop_call(
        self, coordinator, mock_transport, yield_loop
    ):
        """Message loop stops processing when coordinator is stopped."""
        # Arrange
        handled_messages = []

        async def tracking_handler(client_message):
            handled_messages.append((client_message.client_id, client_message.payload))

        coordinator._handle_client_message = tracking_handler

        # Act
        await coordinator.start()

        mock_transport.add_client_message(
            "client1", {"jsonrpc": "2.0", "method": "processed"}
        )
        await yield_loop()

        await coordinator.stop()

        # Send more messages after stopping
        mock_transport.add_client_message(
            "client1", {"jsonrpc": "2.0", "method": "ignored"}
        )
        await yield_loop()

        # Assert
        assert len(handled_messages) == 1
        assert handled_messages[0][1]["method"] == "processed"
