"""Day 26: a read-only CLI tool for the troubleshooting agent.

A model decides which command to run, so the tool must not trust it. Only `show` commands get
through, and a pipe only to `include` or `section`: `show run | bash rm -rf /` stays on the
model's side of the fence. Day 28: the rule moved to guardrails.py, shared with the MCP server.
"""

from temporalio import activity
from temporalio.exceptions import ApplicationError

from netops_temporal.devices.errors import DeviceAuthError, UnknownDeviceError
from netops_temporal.devices.ssh import cli_session
from netops_temporal.guardrails import CommandNotAllowed, check_command


# Two plain parameters instead of one model (Day 3's rule): this activity is a tool, and the
# model writes its arguments. Small models get nested arguments wrong; flat ones they manage.
@activity.defn
def show_command(device: str, command: str) -> str:
    """Run one read-only `show` command on a device and return its output. Only commands
    starting with `show` are allowed, optionally piped to `include` or `section`."""
    try:
        check_command(command)
    except CommandNotAllowed as err:
        # Non-retryable: the same command is just as forbidden on the next attempt.
        raise ApplicationError(str(err), type="CommandNotAllowed", non_retryable=True) from err
    try:
        with cli_session(device) as send:
            return send(command)
    except DeviceAuthError as err:
        raise ApplicationError(str(err), type="AuthError", non_retryable=True) from err
    except UnknownDeviceError as err:
        raise ApplicationError(str(err), type="UnknownDevice", non_retryable=True) from err
