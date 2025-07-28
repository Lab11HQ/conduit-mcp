from typing import Any, AsyncIterator

from src.conduit.transport.server import ClientMessage, ServerTransport


class MockServerTransport(ServerTransport):
    def __init__(self):
        self.registered_clients = {}

    async def send(self, client_id: str, message: dict[str, Any]) -> None:
        pass

    async def client_messages(self) -> AsyncIterator[ClientMessage]:
        pass

    async def disconnect_client(self, client_id: str) -> None:
        self.registered_clients.pop(client_id, None)

    async def close(self) -> None:
        """Close the transport and clean up all resources."""
        pass
