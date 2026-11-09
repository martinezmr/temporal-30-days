"""Day 14: check a device's running config against the policy lines for its role."""

from temporalio import activity
from temporalio.exceptions import ApplicationError

from netops_temporal.devices.errors import DeviceAuthError, UnknownDeviceError
from netops_temporal.devices.napalm_eos import get_running_config
from netops_temporal.models import ComplianceCheckRequest


@activity.defn
def check_config_compliance(req: ComplianceCheckRequest) -> list[str]:
    """Return the required lines the running config doesn't have.

    Only the missing lines come back. The config itself stays on the worker, out of workflow
    history (it's large, and it may contain secrets).
    """
    try:
        config = get_running_config(req.device)
    except DeviceAuthError as err:
        raise ApplicationError(
            f"auth failed for {req.device}", type="AuthError", non_retryable=True
        ) from err
    except UnknownDeviceError as err:
        raise ApplicationError(str(err), type="UnknownDevice", non_retryable=True) from err
    present = {line.strip() for line in config.splitlines()}
    return [line for line in req.required_lines if line not in present]
