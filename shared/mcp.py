"""Optional MCP client manager for Gateway tool integrations.

The Gateway keeps STDIO MCP sessions stateful and lazy: configuring a server
does not spawn a subprocess until a request lists or invokes one of its tools.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MCPDependencyError(RuntimeError):
    """Raised when an MCP operation is requested without the optional SDK."""


@dataclass(frozen=True)
class MCPServerConfig:
    """Validated STDIO launch configuration for one MCP server."""

    command: str
    args: tuple[str, ...] = ()
    env: Optional[dict[str, str]] = None


def _load_mcp_sdk():
    """Import the optional MCP SDK only when an MCP server is used."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise MCPDependencyError(
            "MCP support requires the optional 'mcp' package. "
            "Install project requirements before invoking MCP tools."
        ) from exc
    return ClientSession, StdioServerParameters, stdio_client


class MCPClientManager:
    """Register MCP servers and maintain lazy, stateful STDIO sessions."""

    def __init__(self):
        self.sessions: dict[str, Any] = {}
        self.exit_stacks: dict[str, AsyncExitStack] = {}
        self.server_configs: dict[str, MCPServerConfig] = {}
        self._registry_lock = asyncio.Lock()
        self._connect_locks: dict[str, asyncio.Lock] = {}

    async def register_server(
        self,
        name: str,
        command: str,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
    ) -> None:
        """Register a STDIO MCP server without starting its subprocess."""
        normalized_name = name.strip()
        normalized_command = command.strip()
        if not normalized_name:
            raise ValueError("MCP server name must not be empty")
        if not normalized_command:
            raise ValueError(
                f"MCP server '{normalized_name}' command must not be empty"
            )
        if args is not None and not all(isinstance(arg, str) for arg in args):
            raise ValueError(f"MCP server '{normalized_name}' args must be strings")
        if env is not None and not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in env.items()
        ):
            raise ValueError(
                f"MCP server '{normalized_name}' environment values must be strings"
            )

        config = MCPServerConfig(
            command=normalized_command,
            args=tuple(args or ()),
            env=dict(env) if env else None,
        )
        async with self._registry_lock:
            if normalized_name in self.sessions:
                if self.server_configs[normalized_name] != config:
                    raise RuntimeError(
                        f"MCP server '{normalized_name}' is already connected"
                    )
                return
            self.server_configs[normalized_name] = config
            self._connect_locks.setdefault(normalized_name, asyncio.Lock())
        logger.info("Registered MCP server: %s", normalized_name)

    def configured_servers(self) -> list[str]:
        """Return registered server names in stable order."""
        return sorted(self.server_configs)

    async def get_session(self, name: str):
        """Return an initialized session, connecting lazily when necessary."""
        if name in self.sessions:
            return self.sessions[name]
        if name not in self.server_configs:
            raise ValueError(f"MCP server '{name}' is not registered")

        connect_lock = self._connect_locks[name]
        async with connect_lock:
            if name in self.sessions:
                return self.sessions[name]

            ClientSession, StdioServerParameters, stdio_client = _load_mcp_sdk()
            config = self.server_configs[name]
            params = StdioServerParameters(
                command=config.command,
                args=list(config.args),
                env=config.env,
            )
            exit_stack = AsyncExitStack()
            try:
                read, write = await exit_stack.enter_async_context(stdio_client(params))
                session = await exit_stack.enter_async_context(
                    ClientSession(read, write)
                )
                await session.initialize()
            except Exception as exc:
                await exit_stack.aclose()
                raise RuntimeError(
                    f"Could not connect to MCP server '{name}': {exc}"
                ) from exc

            self.sessions[name] = session
            self.exit_stacks[name] = exit_stack
            logger.info("Connected to MCP server: %s", name)
            return session

    async def inspect_tools(self, server_name: Optional[str] = None) -> dict[str, Any]:
        """Return serializable tool inventory and per-server connection errors."""
        if server_name and server_name not in self.server_configs:
            raise ValueError(f"MCP server '{server_name}' is not registered")

        names = [server_name] if server_name else self.configured_servers()
        tools: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        for name in names:
            try:
                session = await self.get_session(name)
                result = await session.list_tools()
                for tool in result.tools:
                    tools.append(
                        {
                            "server": name,
                            "name": tool.name,
                            "description": tool.description or "",
                            "input_schema": tool.inputSchema,
                        }
                    )
            except Exception as exc:
                logger.warning("Could not list MCP tools for %s: %s", name, exc)
                errors[name] = str(exc)
        return {
            "servers": names,
            "tools": tools,
            "errors": errors,
        }

    async def list_tools(
        self, server_name: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Return available tool descriptors for one or all registered servers."""
        return (await self.inspect_tools(server_name))["tools"]

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ):
        """Invoke one tool through a lazily initialized MCP session."""
        session = await self.get_session(server_name)
        return await session.call_tool(tool_name, arguments)

    async def close_all(self) -> None:
        """Close every active MCP session. Safe to call repeatedly."""
        async with self._registry_lock:
            stacks = list(self.exit_stacks.items())
            self.sessions.clear()
            self.exit_stacks.clear()

        for name, stack in stacks:
            try:
                await stack.aclose()
                logger.info("Closed MCP server connection: %s", name)
            except Exception as exc:
                logger.warning("Failed to close MCP server %s: %s", name, exc)


_mcp_manager: Optional[MCPClientManager] = None


def get_mcp_manager() -> MCPClientManager:
    """Return the process-wide MCP client manager."""
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPClientManager()
    return _mcp_manager
