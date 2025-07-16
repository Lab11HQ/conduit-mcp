import asyncio

import pytest

from conduit.transport.stdio.client import StdioClientTransport
from conduit.transport.stdio.shared import serialize_message


class TestStdioClientMessageSending:
    """Test stdio client transport message sending behavior."""

    async def test_send_writes_message_to_subprocess_stdin(self, tmp_path):
        # Arrange
        output_file = tmp_path / "subprocess_output.txt"

        script = f"""
import sys
with open(r'{output_file}', 'w') as f:
    for line in sys.stdin:
        f.write(line)
        f.flush()
"""

        transport = StdioClientTransport(["python", "-c", script])
        await transport.open()

        message = {"jsonrpc": "2.0", "method": "test", "id": 1}

        # Act
        await transport.send(message)
        await asyncio.sleep(0.01)  # Let subprocess write

        # Assert
        expected = serialize_message(message) + "\n"
        written_content = output_file.read_text()
        assert written_content == expected

        # Cleanup
        await transport.close()

    async def test_send_raises_when_transport_not_open(self):
        # Arrange
        transport = StdioClientTransport(["python", "-c", "pass"])
        # Note: We intentionally do NOT call transport.open()

        message = {"jsonrpc": "2.0", "method": "test", "id": 1}

        # Act & Assert
        with pytest.raises(ConnectionError):
            await transport.send(message)
