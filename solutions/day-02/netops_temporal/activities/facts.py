"""Day 2: the first activity that talks to a device."""

from temporalio import activity

from netops_temporal.devices.eapi import run_show


# A plain `def`, not `async def`: pyeapi blocks while it waits for the device, so this
# activity runs on the worker's thread pool instead of its event loop.
@activity.defn
def get_device_facts(device: str) -> dict:
    activity.logger.info("Getting facts from %s", device)
    [version] = run_show(device, ["show version"])
    return {
        "device": device,
        "model": version["modelName"],
        # EOS reports e.g. "4.32.0F-36401836.4320F (engineering build)"; keep the release.
        "version": version["version"].split("-")[0],
    }
