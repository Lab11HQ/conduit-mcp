"""
MCP server to get sleep data from your Oura Ring.

You'll need to set the OURA_API_KEY environment variable.

Oura API: https://api.ouraring.com/v2/docs
"""

import asyncio
import json
import logging
import os
from datetime import date

import httpx
from dotenv import load_dotenv

from conduit.protocol.content import TextContent
from conduit.protocol.tools import CallToolRequest, CallToolResult, JSONSchema, Tool
from conduit.server.message_context import MessageContext
from conduit.server.session import ServerSession
from conduit.transport.stdio import StdioServerTransport

sleep_data_tool = Tool(
    name="oura-ring-sleep-data",
    description="Get sleep data for a given date or date range. If no end date is"
    " provided, the data for the given date will be returned.",
    input_schema=JSONSchema(
        properties={
            "start_date": {"type": "string", "format": "date"},
            "end_date": {"type": "string", "format": "date"},
        },
        required=["start_date"],
    ),
)


async def sleep_tool_handler(
    context: MessageContext, request: CallToolRequest
) -> CallToolResult:
    # Log the request
    logging.info(f"Context: {context}")
    logging.info(f"Request: {request}")
    logging.info(f"Arguments: {request.arguments}")

    # Parse arguments
    start_date = request.arguments["start_date"]
    end_date = request.arguments.get("end_date")
    start_date = date.fromisoformat(start_date)
    end_date = date.fromisoformat(end_date) if end_date else start_date

    # Get data from Oura API.
    # TODO: Add error handling.
    response = httpx.get(
        "https://api.ouraring.com/v2/usercollection/daily_sleep",
        headers={"Authorization": f"Bearer {os.getenv('OURA_API_KEY')}"},
        params={"start_date": start_date, "end_date": end_date},
    )
    response.raise_for_status()
    sleep_data = response.json()

    # Return the data.
    return CallToolResult(content=[TextContent(text=json.dumps(sleep_data))])


async def main():
    server = ServerSession(transport=StdioServerTransport())
    server.tools.add_tool(sleep_data_tool, sleep_tool_handler)
    await server._start()  # TODO: This is a hack to start the server.

    # HACK: Keep the server running indefinitely.
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await server._stop()


if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())
