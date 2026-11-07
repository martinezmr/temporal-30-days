# Day 19 — Versioning (the CI/CD day)

[← Day 18](../day-18-schedules/README.md) · [Day 20 →](../day-20-observability/README.md)

## Goal

Deploy new workflow code while old workflows are still running, without a single non-determinism error.

## Learn

Two tools, often used together:

- **Patching** — branch inside one workflow type:

    ```python
    if workflow.patched("add-lldp-check"):
        await workflow.execute_activity(get_lldp_neighbors, ...)
    ```

    Later, once no old runs remain: `workflow.deprecate_patch("add-lldp-check")`, then remove it.

- **Worker Versioning** (GA) — each worker build declares a deployment name + build ID; the server routes each workflow to a compatible build.
    - **PINNED** — the workflow finishes on the build it started on. Best for short workflows (compliance, upgrade).
    - **AUTO_UPGRADE** — moves to the current build on its next task. For the long-lived orchestrator; protect changes with patches, or move it at continue-as-new.

- Docs: [Versioning](https://docs.temporal.io/develop/python/workflows/versioning) · [Worker Versioning](https://docs.temporal.io/worker-versioning) · [Configure a worker](https://docs.temporal.io/production-deployment/worker-deployments/worker-versioning/configure-worker)

## Build

```python
worker = Worker(
    client, task_queue=ORCHESTRATION_TASK_QUEUE, workflows=[...], activities=[...],
    deployment_config=WorkerDeploymentConfig(
        version=WorkerDeploymentVersion(deployment_name="netops", build_id=os.environ["BUILD_ID"]),
        use_worker_versioning=True,
        default_versioning_behavior=VersioningBehavior.PINNED,
    ),
)

@workflow.defn(versioning_behavior=VersioningBehavior.AUTO_UPGRADE)
class NetworkComplianceOrchestrator: ...
```

## Practice the rollout

```bash
BUILD_ID=a1 uv run python -m netops_temporal.workers.main   # build A
temporal worker deployment set-current-version --deployment-name netops --build-id a1
# start a few ConfigComplianceWorkflows that sleep
# change ConfigComplianceWorkflow, then:
BUILD_ID=b2 uv run python -m netops_temporal.workers.main   # build B, alongside A
temporal worker deployment set-ramping-version --deployment-name netops --build-id b2 --percentage 25
temporal worker deployment set-current-version --deployment-name netops --build-id b2
temporal worker deployment describe --deployment-name netops
```

Check `temporal worker deployment --help` for exact flags on your CLI version.

## Done when

- [ ] Old pinned runs finished on `a1` while new runs started on `b2` (visible in each run's details).
- [ ] You've written down which of your workflows are PINNED vs AUTO_UPGRADE, and why.
