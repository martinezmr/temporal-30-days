"""Day 28: the agent's device tools as an MCP server.

MCP (Model Context Protocol) is a standard way to offer tools to a model. Written once, these
tools serve the Temporal agent (through the plugin, as activities) and an assistant in your
editor alike. Same guardrail as Day 26: read-only, whoever is asking.

    uv run python -m netops_temporal.mcp_server.netops_tools    # speaks MCP on stdin/stdout
"""

import asyncio

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from netops_temporal.devices.eapi import run_show
from netops_temporal.devices.errors import DeviceAuthError, UnknownDeviceError
from netops_temporal.devices.ssh import cli_session
from netops_temporal.guardrails import CommandNotAllowed, check_command

server = MCPServer("netops")


def run_cli(device: str, command: str) -> str:
    with cli_session(device) as send:
        return send(command)


@server.tool()
async def show(device: str, command: str) -> str:
    """Run one read-only `show` command on an Arista EOS device and return its output. Only
    commands starting with `show` are allowed, optionally piped to `include` or `section`."""
    try:
        check_command(command)  # before any device is contacted
        # The device libraries block: run them off the server's event loop.
        return await asyncio.to_thread(run_cli, device, command)
    except (CommandNotAllowed, DeviceAuthError, UnknownDeviceError) as err:
        raise ToolError(str(err)) from err  # an error result the model reads


@server.tool()
async def facts(device: str) -> str:
    """The model and EOS version of a device."""
    try:
        [version] = await asyncio.to_thread(run_show, device, ["show version"])
    except (DeviceAuthError, UnknownDeviceError) as err:
        raise ToolError(str(err)) from err
    return f"{device}: {version['modelName']}, EOS {version['version'].split('-')[0]}"


if __name__ == "__main__":
    server.run()  # stdio by default
