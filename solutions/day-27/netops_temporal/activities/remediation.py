"""Day 17: the two device-changing steps of a config remediation: push, and its undo."""

from temporalio import activity
from temporalio.exceptions import ApplicationError

from netops_temporal.devices import config_push
from netops_temporal.devices.errors import DeviceAuthError, UnknownDeviceError
from netops_temporal.models import PushRequest, RollbackRequest


def _non_retryable(device: str, err: Exception) -> ApplicationError:
    if isinstance(err, DeviceAuthError):
        return ApplicationError(f"auth failed for {device}", type="AuthError", non_retryable=True)
    return ApplicationError(str(err), type="UnknownDevice", non_retryable=True)


@activity.defn
def push_config(req: PushRequest) -> str:
    """Merge the lines and commit. Safe to retry: lines already present give an empty diff."""
    try:
        return config_push.push_lines(req.device, req.lines)
    except (DeviceAuthError, UnknownDeviceError) as err:
        raise _non_retryable(req.device, err) from err


@activity.defn
def rollback_config(req: RollbackRequest) -> None:
    try:
        config_push.rollback(req.device)
    except (DeviceAuthError, UnknownDeviceError) as err:
        raise _non_retryable(req.device, err) from err
