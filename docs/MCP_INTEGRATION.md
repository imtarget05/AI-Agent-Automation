# MCP Integration

The Gateway supports opt-in STDIO Model Context Protocol (MCP) servers. The
implementation is intentionally small: the existing LangGraph orchestrator
keeps ownership of planning, while MCP adds external tools behind the same
guardrail and operator-approval boundary used for sensitive platform actions.

## Why This Shape

- `agentscope/` was used as a reference for lazy, stateful MCP lifecycle
  management. The project does not import AgentScope at runtime.
- `intelligent-app-suite/` was used as a reference for routing tasks to named
  MCP servers instead of exposing every tool to every request.
- `mcp_reference/` remains a local catalog for selecting additional servers.
  It is not a runtime dependency.

## Configure Servers

Install project requirements, ensure each MCP launcher exists inside the
Gateway runtime, then set `MCP_SERVERS` to a JSON object:

```dotenv
MCP_ENABLED=true
MCP_SERVERS={"fetch":{"command":"uvx","args":["mcp-server-fetch"]}}
```

Servers are registered on Gateway startup but started lazily. Listing or
calling a tool opens the STDIO session and keeps it alive until Gateway
shutdown.

## Discover Tools

Use the authenticated inventory endpoint:

```bash
curl http://localhost:8000/mcp/tools \
  -H "Authorization: Bearer $API_SECRET_KEY"
```

The response includes `servers`, discovered `tools`, and per-server `errors`.
An unavailable optional launcher does not prevent the Gateway from starting.

## Execute Through The Orchestrator

The supervisor can create an MCP task with explicit server, tool, and arguments:

```json
{
  "agent": "MCP",
  "instruction": "call fetch:fetch",
  "context": {
    "server": "fetch",
    "tool": "fetch",
    "arguments": {"url": "https://example.com"}
  }
}
```

Every MCP invocation is checked by the input guardrail and tool guardrail.
When policy requires approval, the MCP subprocess is not invoked until the
session task has been approved.
