# conduit-mcp

A Python SDK that makes Model Context Protocol (MCP) development delightful.

## What is MCP?

Model Context Protocol is a JSON-RPC 2.0 standard that connects LLMs to external tools, resources, and data through a host-client-server architecture. Hosts (LLM applications) create clients that communicate with MCP servers to access tools, resources, and prompts.

## Why conduit-mcp?

The MCP specification is TypeScript-first, we're building a Python SDK that feels natural. We're focused on designing clean abstractions that make MCP development intuitive and powerful.

**Key Design Principles:**
- **Pythonic conventions** - Built for Python developers
- **1:many architecture** - Explicit client/server context handling
- **Rich context objects** - Full client/server state and capabilities available
- **Layered design** - Transport, session, and protocol concerns properly separated

## Architecture

```
Transport Layer    →  ServerTransport (stdio, HTTP, etc.)
Session Layer      →  ServerSession (protocol conversations)
Protocol Layer     →  Managers (tools, resources, prompts)
```

Clean separation of concerns with explicit client context threading through the entire stack.

## Status

🚧 **Pre-launch** - Core architecture complete, transport implementations coming next.

## Development Goals

- **Intuitive APIs** - Works the way developers expect
- **Narrative docs** - Confident and considerate tone  
- **Comprehensive tests** - Every documented promise gets tested
- **Clean abstractions** - Single responsibilities, proper separation

## Contributing

Contributions welcome! Read our [contributing guide](./contributing.md) for more info.