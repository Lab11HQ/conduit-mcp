import asyncio

from conduit.protocol.common import PingRequest


class TestMessageLoop:
    async def test_processes_messages_from_transport(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange
        handled_messages = []

        async def tracking_handler(server_message):
            handled_messages.append((server_message.server_id, server_message.payload))

        coordinator._route_server_message = tracking_handler

        # Act
        await coordinator.start()
        mock_transport.add_server_message(
            "server1", {"jsonrpc": "2.0", "method": "test/one"}
        )
        mock_transport.add_server_message(
            "server2", {"jsonrpc": "2.0", "method": "test/two"}
        )

        await yield_loop()
        await coordinator.stop()

        # Assert
        assert len(handled_messages) == 2
        assert handled_messages[0] == (
            "server1",
            {"jsonrpc": "2.0", "method": "test/one"},
        )
        assert handled_messages[1] == (
            "server2",
            {"jsonrpc": "2.0", "method": "test/two"},
        )

    async def test_handler_error_does_not_stop_loop(
        self, coordinator, mock_transport, yield_loop
    ):
        handled_messages = []

        async def crashing_handler(server_message):
            handled_messages.append((server_message.server_id, server_message.payload))
            if len(handled_messages) == 2:
                raise ValueError("Handler crashed!")

        coordinator._route_server_message = crashing_handler

        # Act
        await coordinator.start()
        mock_transport.add_server_message(
            "server1", {"jsonrpc": "2.0", "method": "first"}
        )
        mock_transport.add_server_message(
            "server2", {"jsonrpc": "2.0", "method": "crash"}
        )
        mock_transport.add_server_message(
            "server3", {"jsonrpc": "2.0", "method": "third"}
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
        # Arrange
        handled_messages = []

        async def tracking_handler(server_message):
            handled_messages.append((server_message.server_id, server_message.payload))

        coordinator._route_server_message = tracking_handler

        # Act
        await coordinator.start()
        mock_transport.add_server_message(
            "server1", {"jsonrpc": "2.0", "method": "before_crash"}
        )
        await yield_loop()

        # Simulate transport failure
        mock_transport.simulate_error()
        await yield_loop()

        # Assert
        assert len(handled_messages) == 1
        assert handled_messages[0][1]["method"] == "before_crash"
        assert not coordinator.running

    async def test_done_callback_cleans_up_server_state(
        self, coordinator, mock_transport, server_manager, yield_loop
    ):
        # Arrange
        await coordinator.start()

        task1 = asyncio.create_task(asyncio.sleep(10))
        future1 = asyncio.Future()

        server_manager.register_server("server1")
        server_manager.track_request_from_server(
            "server1", "ping_from_server", PingRequest(), task1
        )
        server_manager.track_request_to_server(
            "server1", "ping_to_server", PingRequest(), future1
        )

        assert server_manager.server_count() == 1
        assert (
            server_manager.get_request_from_server("server1", "ping_from_server")
            is not None
        )
        assert (
            server_manager.get_request_to_server("server1", "ping_to_server")
            is not None
        )

        # Act - simulate transport failure (unexpected exit)
        mock_transport.simulate_error()
        await yield_loop()

        # Assert - all server state cleaned up
        assert not coordinator.running
        assert (
            server_manager.get_request_from_server("server1", "ping_from_server")
            is None
        )
        assert server_manager.get_request_to_server("server1", "ping_to_server") is None

    async def test_loop_respects_stop_call(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange
        handled_messages = []

        async def tracking_handler(server_message):
            handled_messages.append((server_message.server_id, server_message.payload))

        coordinator._route_server_message = tracking_handler

        # Act
        await coordinator.start()
        mock_transport.add_server_message(
            "server1", {"jsonrpc": "2.0", "method": "processed"}
        )
        await yield_loop()

        await coordinator.stop()

        # Send more messages after stopping
        mock_transport.add_server_message(
            "server1", {"jsonrpc": "2.0", "method": "ignored"}
        )
        await yield_loop()

        # Assert
        assert len(handled_messages) == 1
        assert handled_messages[0][1]["method"] == "processed"
