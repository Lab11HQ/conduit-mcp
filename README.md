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

## Status

🚧 **In developement** - Core architecture complete. stdio transport complete. Integrating OAuth 2.1 client into HTTP transport

## Contributing

Read our [contributing guide](./contributing.md) to get started.