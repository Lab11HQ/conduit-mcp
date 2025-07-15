# import pytest

# from conduit.transport.stdio.client import StdioClientTransport

# """
# Eventual structure:
# tests/transport/stdio/
# ├── test_client_lifecycle.py       # Process management
# ├── test_client_messaging.py       # Send/receive core functionality
# ├── test_client_serialization.py   # JSON handling & validation
# ├── test_client_error_handling.py  # Error conditions & recovery
# ├── test_client_edge_cases.py      # Robustness & corner cases
# ├── test_client_integration.py     # End-to-end scenarios
# └── conftest.py                     # Shared fixtures & helpers
# """


# class TestStdioClientTransportLifecycle:
#     """Test subprocess lifecycle management."""

#     def test_init_does_not_start_process(self):
#         # Arrange & Act
#         transport = StdioClientTransport(["echo", "hello"])

#         # Assert
#         assert transport._process is None
#         assert not transport.is_open
#         assert transport._server_command == ["echo", "hello"]

#     async def test_start_server_spawns_subprocess(self):
#         # Arrange
#         transport = StdioClientTransport(
#             ["python", "-c", "import sys; sys.stdin.read()"]
#         )

#         # Act
#         await transport._start_server()

#         # Assert
#         assert transport._process is not None
#         assert transport.is_open
#         assert transport._is_process_alive()

#         # Cleanup
#         await transport._shutdown_process()

#     async def test_start_server_is_idempotent(self):
#         # Arrange
#         transport = StdioClientTransport(
#             ["python", "-c", "import sys; sys.stdin.read()"]
#         )

#         # Act - start multiple times
#         await transport._start_server()
#         process1 = transport._process

#         await transport._start_server()
#         process2 = transport._process

#         # Assert - same process instance
#         assert process1 is process2
#         assert transport.is_open

#         # Cleanup
#         await transport._shutdown_process()

#     async def test_start_server_raises_on_invalid_command(self):
#         # Arrange
#         transport = StdioClientTransport(["nonexistent-command-12345"])

#         # Act & Assert
#         with pytest.raises(ConnectionError, match="Failed to start server"):
#             await transport._start_server()

#         assert transport._process is None
#         assert not transport.is_open

#     async def test_is_process_alive_reflects_actual_state(self):
#         # Arrange
#         transport = StdioClientTransport(
#             ["python", "-c", "import sys; sys.stdin.read()"]
#         )

#         # Act & Assert - before starting
#         assert not transport._is_process_alive()

#         # Act & Assert - after starting
#         await transport._start_server()
#         assert transport._is_process_alive()

#         # Act & Assert - after explicit shutdown
#         await transport._shutdown_process()
#         assert not transport._is_process_alive()

#     async def test_shutdown_process_follows_spec_sequence(self):
#         # Arrange
#         transport = StdioClientTransport(
#             ["python", "-c", "import sys; sys.stdin.read()"]
#         )
#         await transport._start_server()

#         # Act
#         await transport._shutdown_process()

#         # Assert
#         assert transport._process is None
#         assert not transport.is_open

#     async def test_shutdown_process_handles_already_dead_process(self):
#         # Arrange - process that exits immediately (this is fine!)
#         transport = StdioClientTransport(["python", "-c", "exit(0)"])
#         await transport._start_server()

#         # Act & Assert - should not raise even if process already exited
#         await transport._shutdown_process()
#         assert not transport.is_open

#     async def test_shutdown_process_is_idempotent(self):
#         # Arrange
#         transport = StdioClientTransport(
#             ["python", "-c", "import sys; sys.stdin.read()"]
#         )
#         await transport._start_server()

#         # Act - shutdown multiple times
#         await transport._shutdown_process()
#         await transport._shutdown_process()  # Should be safe

#         # Assert
#         assert not transport.is_open

#     async def test_is_open_property_comprehensive_check(self):
#         # Arrange
#         transport = StdioClientTransport(
#             ["python", "-c", "import sys; sys.stdin.read()"]
#         )

#         # Act & Assert - initial state
#         assert not transport.is_open

#         # Act & Assert - after starting
#         await transport._start_server()
#         assert transport.is_open

#         # Act & Assert - after explicit shutdown
#         await transport._shutdown_process()
#         assert not transport.is_open


# class TestStdioClientTransportIntegration:

#     async def test_send_starts_server_lazily(self):
#         # Arrange
#         transport = StdioClientTransport(
#             ["python", "-c", "import sys; sys.stdin.read()"]
#         )
#         assert not transport.is_open

#         # Act - send should start the server
#         await transport.send({"method": "ping", "id": 1})

#         # Assert
#         assert transport.is_open
#         assert transport._process is not None

#         # Cleanup
#         await transport._shutdown_process()

#     async def test_send_and_receive_echo(self):
#         # Arrange - server that echoes one line and exits
#         transport = StdioClientTransport(
#             [
#                 "python",
#                 "-c",
#                 "import sys; "
#                 "line = sys.stdin.readline(); "
#                 "print(line.strip(), flush=True)",
#             ]
#         )

#         # Act - send message
#         await transport.send({"method": "ping", "id": 1})

#         # Act - receive echoed message
#         async for message in transport.server_messages():
#             # Assert
#             assert message == {"method": "ping", "id": 1}
#             break

#         # Cleanup
#         await transport.close()
