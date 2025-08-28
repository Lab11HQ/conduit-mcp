# conduit-mcp

A Python SDK for Model Context Protocol (MCP) development.

## What is MCP?

Model Context Protocol connects LLMs to external tools, resources, and data through a JSON-RPC 2.0 standard. Hosts create clients that communicate with MCP servers to access capabilities beyond text generation.

## Goals

- **Pythonic** - Feels natural for Python developers
- **Reliable** - Comprehensive tests, clean abstractions
- **Delightful** - Works the way you expect

## Architecture

```
Transport Layer    →  ServerTransport (stdio, HTTP, etc.)
Session Layer      →  ServerSession (protocol conversations)  
Protocol Layer     →  Managers (tools, resources, prompts)
```

## Quick Example

Here's a working MCP server that provides a calculator tool (needs a lot of polish but works with Claude Desktop!):

```python
import asyncio
from conduit.protocol.content import TextContent
from conduit.protocol.tools import CallToolRequest, CallToolResult, JSONSchema, Tool
from conduit.server.message_context import MessageContext
from conduit.server.session import ServerSession
from conduit.transport.stdio import StdioServerTransport

async def main():
    server = ServerSession(transport=StdioServerTransport())
    
    # Define a calculator tool
    tool = Tool(
        name="calculate",
        description="Calculate the sum of two numbers",
        input_schema=JSONSchema(
            type="object", 
            properties={"a": {"type": "number"}, "b": {"type": "number"}}
        ),
    )
    
    # Handle tool calls
    async def calculate_handler(context: MessageContext, request: CallToolRequest) -> CallToolResult:
        a = request.arguments["a"]
        b = request.arguments["b"]
        result = a + b
        return CallToolResult(
            content=[TextContent(text=f"The sum of {a} and {b} is {result}")]
        )
    
    server.tools.add_tool(tool, calculate_handler)
    await server._start()
    
    # Keep server running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await server._stop()

if __name__ == "__main__":
    asyncio.run(main())
```

See [src/conduit/examples/calculator.py](src/conduit/examples/calculator.py) for the full example.

## Status

🚧 **In developement** - Core architecture complete. stdio transport complete. Integrating OAuth 2.1 client into HTTP transport

## Contributing

Read our [contributing guide](./contributing.md) to get started.