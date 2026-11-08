"""Day 28: the device tools as an MCP server, usable by the agent and by Copilot alike."""

import pytest
from mcp import Client

from netops_temporal.mcp_server.netops_tools import server


async def call(tool: str, **arguments):
    async with Client(server) as client:
        return await client.call_tool(tool, arguments)


def text(result) -> str:
    return "\n".join(c.text for c in result.content)


async def test_mcp_lists_read_only_tools():
    async with Client(server) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
    assert tools == {"show", "facts"}


@pytest.mark.parametrize("command", ["configure terminal", "reload", "show run | bash ls"])
async def test_mcp_tool_rejects_config_commands(command):
    result = await call("show", device="bos-acc-01", command=command)
    # An error result the model (or Copilot) reads, before any device is contacted.
    assert result.is_error
    assert "not allowed" in text(result)


async def test_mcp_show_runs_show_commands():
    result = await call("show", device="bos-acc-01", command="show interfaces status | include Et1")
    assert not result.is_error
    assert all("Et1" in line for line in text(result).splitlines())


async def test_mcp_facts():
    result = await call("facts", device="bos-acc-01")
    assert not result.is_error
    assert "4.3" in text(result)  # the EOS version
