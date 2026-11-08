"""Day 7: back up a running config (NAPALM) and fetch intent (Nautobot)."""

from temporalio import activity
from temporalio.exceptions import ApplicationError

from netops_temporal.constants import OUTPUT_DIR
from netops_temporal.devices.errors import DeviceAuthError, UnknownDeviceError
from netops_temporal.devices.napalm_eos import get_running_config
from netops_temporal.models import BackupConfigRequest, DeviceIntent, IntentRequest
from netops_temporal.sot.nautobot import get_device_intent


@activity.defn
def backup_running_config(req: BackupConfigRequest) -> str:
    """Save the running config to OUTPUT_DIR/backups/<device>/<timestamp>.cfg; return the path."""
    try:
        config = get_running_config(req.device)
    except DeviceAuthError as err:
        raise ApplicationError(
            f"auth failed for {req.device}", type="AuthError", non_retryable=True
        ) from err
    except UnknownDeviceError as err:
        raise ApplicationError(str(err), type="UnknownDevice", non_retryable=True) from err
    path = OUTPUT_DIR / "backups" / req.device / f"{req.timestamp}.cfg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config)
    return str(path)


@activity.defn
def fetch_device_intent(req: IntentRequest) -> DeviceIntent:
    try:
        return get_device_intent(req.device)
    except UnknownDeviceError as err:
        raise ApplicationError(str(err), type="UnknownDevice", non_retryable=True) from err
