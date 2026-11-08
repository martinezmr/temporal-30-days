"""Day 26: a read-only CLI tool for the troubleshooting agent.

A model decides which command to run, so the tool must not trust it. Only `show` commands get
through, and a pipe only to `include` or `section`: `show run | bash rm -rf /` stays on the
model's side of the fence.
"""

from temporalio import activity
from temporalio.exceptions import ApplicationError

from netops_temporal.devices.errors import DeviceAuthError, UnknownDeviceError
from netops_temporal.devices.ssh import cli_session

ALLOWED_PIPES = ("include ", "section ")


def check_command(command: str) -> None:
    """Raise CommandNotAllowed unless `command` is a show command, piped only to filters."""
    first, *pipes = (part.strip() for part in command.split("|"))
    if not first.startswith("show "):
        raise ApplicationError(
            f"only show commands are allowed, not {command!r}",
            type="CommandNotAllowed",
            non_retryable=True,
        )
    for pipe in pipes:
        if not pipe.startswith(ALLOWED_PIPES):
            raise ApplicationError(
                f"only `| include` and `| section` are allowed, not `| {pipe}`",
                type="CommandNotAllowed",
                non_retryable=True,
            )


# Two plain parameters instead of one model (Day 3's rule): this activity is a tool, and the
# model writes its arguments. Small models get nested arguments wrong; flat ones they manage.
@activity.defn
def show_command(device: str, command: str) -> str:
    """Run one read-only `show` command on a device and return its output. Only commands
    starting with `show` are allowed, optionally piped to `include` or `section`."""
    check_command(command)
    try:
        with cli_session(device) as send:
            return send(command)
    except DeviceAuthError as err:
        raise ApplicationError(str(err), type="AuthError", non_retryable=True) from err
    except UnknownDeviceError as err:
        raise ApplicationError(str(err), type="UnknownDevice", non_retryable=True) from err
