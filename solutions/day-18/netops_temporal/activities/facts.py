"""Day 2-3: the first activity that talks to a device."""

from temporalio import activity
from temporalio.exceptions import ApplicationError

from netops_temporal.devices.eapi import run_show
from netops_temporal.devices.errors import DeviceAuthError, UnknownDeviceError
from netops_temporal.models import DeviceFacts, FactsRequest


# A plain `def`, not `async def`: pyeapi blocks while it waits for the device, so this
# activity runs on the worker's thread pool instead of its event loop.
@activity.defn
def get_device_facts(req: FactsRequest) -> DeviceFacts:
    activity.logger.info("Getting facts from %s", req.device)
    try:
        [version] = run_show(req.device, ["show version"])
    except DeviceAuthError as err:
        # Retrying with the same wrong password only locks the account: fail now.
        raise ApplicationError(
            f"auth failed for {req.device}", type="AuthError", non_retryable=True
        ) from err
    except UnknownDeviceError as err:
        raise ApplicationError(str(err), type="UnknownDevice", non_retryable=True) from err
    # DeviceUnreachableError is not caught: it fails this attempt and Temporal retries.
    return DeviceFacts(
        device=req.device,
        model=version["modelName"],
        # EOS reports e.g. "4.32.0F-36401836.4320F (engineering build)"; keep the release.
        version=version["version"].split("-")[0],
    )
