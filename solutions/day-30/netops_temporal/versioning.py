"""Day 30: worker versioning. Every worker joins the deployment "netops" as one build.

BUILD_ID (a git commit, say) turns it on. A new build's workers poll alongside the old ones;
when you make the new build current (lab/deploy.sh), new workflows start on it. What happens
to the ones already running depends on each workflow's versioning behavior:

    PINNED        finishes on the build it started on: no patching needed (short workflows)
    AUTO_UPGRADE  moves to the current build at its next task: needs patching (long workflows)

Without BUILD_ID, workers run unversioned, as on Days 1-29.
"""

import asyncio
import os

from temporalio.api.workflowservice.v1 import SetWorkerDeploymentCurrentVersionRequest
from temporalio.client import Client
from temporalio.common import VersioningBehavior, WorkerDeploymentVersion
from temporalio.service import RPCError
from temporalio.worker import WorkerDeploymentConfig

DEPLOYMENT_NAME = "netops"


def behavior(wanted: VersioningBehavior) -> VersioningBehavior:
    """For `@workflow.defn(versioning_behavior=...)`: `wanted` when this process's workers are
    versioned, otherwise UNSPECIFIED. The server rejects a workflow task that declares a
    behavior from an unversioned worker ("versioning behavior cannot be specified without
    deployment options"), so without BUILD_ID the workflows must not declare one."""
    return wanted if os.environ.get("BUILD_ID") else VersioningBehavior.UNSPECIFIED


def deployment_config() -> WorkerDeploymentConfig | None:
    """The deployment config for this process's workers, or None without BUILD_ID."""
    build_id = os.environ.get("BUILD_ID")
    if not build_id:
        return None
    return WorkerDeploymentConfig(
        version=WorkerDeploymentVersion(deployment_name=DEPLOYMENT_NAME, build_id=build_id),
        use_worker_versioning=True,
        # Workflows that don't say otherwise are short: they finish where they started.
        default_versioning_behavior=VersioningBehavior.PINNED,
    )


async def set_current_version(client: Client, build_id: str, tries: int = 100) -> None:
    """Make `build_id` the current version of the deployment in the client's namespace (what
    `temporal worker deployment set-current-version` does). The server only knows a version
    once its workers have polled, so this retries for a while."""
    for attempt in range(tries):
        try:
            await client.workflow_service.set_worker_deployment_current_version(
                SetWorkerDeploymentCurrentVersionRequest(
                    namespace=client.namespace,
                    deployment_name=DEPLOYMENT_NAME,
                    build_id=build_id,
                )
            )
            return
        except RPCError:
            if attempt == tries - 1:
                raise
            await asyncio.sleep(0.1)
