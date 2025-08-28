import asyncio
import logging

from conduit.protocol.content import TextContent
from conduit.protocol.tools import CallToolRequest, CallToolResult, JSONSchema, Tool
from conduit.server.message_context import MessageContext
from conduit.server.session import ServerSession
from conduit.transport.stdio import StdioServerTransport


async def main():
    server = ServerSession(transport=StdioServerTransport())

    tool = Tool(
        name="calculate",
        description="Calculate the sum of two numbers",
        input_schema=JSONSchema(
            type="object", properties={"a": {"type": "number"}, "b": {"type": "number"}}
        ),
    )

    async def calculate_handler(
        context: MessageContext, request: CallToolRequest
    ) -> CallToolResult:
        logging.info(f"Context: {context}")
        logging.info(f"Request: {request}")
        logging.info(f"Arguments: {request.arguments}")
        a = request.arguments["a"]
        b = request.arguments["b"]
        result = a + b
        return CallToolResult(
            content=[TextContent(text=f"The sum of {a} and {b} is {result}")]
        )

    server.tools.add_tool(tool, calculate_handler)

    await server._start()  # TODO: This is a hack to start the server


if __name__ == "__main__":
    asyncio.run(main())
