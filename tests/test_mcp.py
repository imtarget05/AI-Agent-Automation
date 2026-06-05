import asyncio
from unittest.mock import patch

from shared.mcp import MCPClientManager, MCPDependencyError


def test_mcp_registration_is_lazy_and_missing_sdk_is_reported_per_server():
    async def run():
        manager = MCPClientManager()
        await manager.register_server(
            name="fetch",
            command="uvx",
            args=["mcp-server-fetch"],
        )

        assert manager.configured_servers() == ["fetch"]
        assert manager.sessions == {}

        with patch(
            "shared.mcp._load_mcp_sdk",
            side_effect=MCPDependencyError("missing mcp sdk"),
        ):
            inventory = await manager.inspect_tools()

        assert inventory == {
            "servers": ["fetch"],
            "tools": [],
            "errors": {"fetch": "missing mcp sdk"},
        }
        assert manager.sessions == {}
        await manager.close_all()
        await manager.close_all()

    asyncio.run(run())


def test_mcp_registration_rejects_empty_command():
    async def run():
        manager = MCPClientManager()
        try:
            await manager.register_server(name="fetch", command="")
        except ValueError as exc:
            assert "command must not be empty" in str(exc)
        else:
            raise AssertionError("empty MCP command should be rejected")

    asyncio.run(run())
