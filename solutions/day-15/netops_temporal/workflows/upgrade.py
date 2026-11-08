"""Day 15: upgrade one device's EOS version. A child workflow that outlives its parent.

cEOS can't really be upgraded in place, so the steps are stand-ins with the real shape:
pre-check, "reload" (a timer), post-check, compare.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.facts import get_device_facts
    from netops_temporal.models import FactsRequest, UpgradeRequest, UpgradeResult

RELOAD_TIME = timedelta(seconds=60)


@workflow.defn
class DeviceUpgradeWorkflow:
    @workflow.run
    async def run(self, req: UpgradeRequest) -> UpgradeResult:
        options = {
            "start_to_close_timeout": timedelta(seconds=30),
            "retry_policy": RetryPolicy(maximum_attempts=5),
        }
        before = await workflow.execute_activity(
            get_device_facts, FactsRequest(device=req.device), **options
        )
        workflow.logger.info(
            "%s: %s -> %s, reloading", req.device, before.version, req.target_version
        )
        await workflow.sleep(RELOAD_TIME)  # stand-in for "install image, reload, wait"
        after = await workflow.execute_activity(
            get_device_facts, FactsRequest(device=req.device), **options
        )
        if after.version == req.target_version:
            return UpgradeResult(device=req.device, ok=True, detail=f"now on {after.version}")
        return UpgradeResult(
            device=req.device,
            ok=False,
            detail=f"still on {after.version} (cEOS can't be upgraded in place: stand-in)",
        )
