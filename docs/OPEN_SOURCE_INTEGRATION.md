# Open-source integration policy

The platform uses cloned repositories in two ways:

1. Curated documentation is indexed into the `open_source` vector-memory namespace.
2. Runtime adapters are disabled by default and must be enabled explicitly.

The curated index is defined in `shared/open_source_knowledge.py`. It includes a
small set of README and architecture files from AgentScope, MCP references,
intelligent-app-suite, Harness, claw-code, and the agent-project catalog. Source
trees are not imported wholesale. Docker Compose mounts the cloned repositories
read-only into the Gateway so startup seeding can see the same files as local
development. Repos can also define per-file chunk limits and heading filters so
large catalogs like `mcp_reference/README.md` keep coverage for both server and
framework sections instead of spending the full chunk budget on the start of the
document.

## Seeding controls

Use these environment variables to control startup ingestion:

```env
OPEN_SOURCE_SEED_ENABLED=true
OPEN_SOURCE_SEED_BACKGROUND=true
OPEN_SOURCE_SEED_FORCE=false
```

`OPEN_SOURCE_SEED_BACKGROUND=false` blocks startup until seeding completes.
`OPEN_SOURCE_SEED_FORCE=true` bypasses the local content-hash cache and
re-embeds unchanged curated docs.

## Optional AgentScope adapter

AgentScope 2.0 runs in its own Docker target because its dependency versions are
newer than the platform base image. Enable it with:

```env
AGENTSCOPE_ENABLED=true
```

Start the optional service with `docker compose --profile agentscope up`.

The adapter uses the AgentScope 2.0 `Agent`, credential, model, `UserMsg`, and
`await agent.reply(...)` APIs. Missing runtime dependencies produce a 503 error.

## Optional claw-code adapter

Build or install the `claw` binary, then configure:

```env
CLAW_ENABLED=true
CLAW_BINARY_PATH=/absolute/path/to/claw
CLAW_WORKING_DIRECTORY=/workspace
```

Claw tasks pass through the Gateway guardrail and operator-approval flow before
the CLI is invoked. The adapter resolves a local clone build or `PATH` when
`CLAW_BINARY_PATH` is empty.
