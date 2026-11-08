# Day 30 — Containers, CI/CD and OpenShift

[← Day 29](../day-29-assemble-orchestrator/README.md) · [Back to start](../../../README.md)

## Goal

Ship a workflow change through a pipeline: replay-tested, deployed as a new build, with running remediations finishing on the old code.

## Workers

One image (`Containerfile` from Day 21), three Deployments:

| Deployment | Namespace | Task queue | Runs |
| --- | --- | --- | --- |
| `orchestration-worker` | default | `netops-orchestration` | orchestrator, upgrade, agent workflows |
| `device-io-worker` | default | `netops-device-io` | eAPI / Nautobot / LLM activities |
| `compliance-worker` | compliance | `compliance-tq` | Nexus handler, `ConfigComplianceWorkflow` |

`BUILD_ID` = git SHA, passed as a build arg and used in `WorkerDeploymentVersion`.

## Pipeline

Extend `.github/workflows/ci.yml` (or OpenShift Pipelines/Tekton — same stages):

1. `ruff` + `pytest` (time-skipping, mocked devices).
2. **Replay tests** against `tests/histories/` — fail the build on non-determinism. Refresh histories from staging regularly.
3. Build and push the image (`ghcr.io/<you>/netops-worker:<sha>`).
4. Deploy the new build alongside the old one, ramp, then make it current (Day 19 commands).

Automate step 4 with the [Temporal Worker Controller](https://docs.temporal.io/production-deployment/worker-deployments/kubernetes-controller) (GA): it manages versioned worker Deployments on Kubernetes and retires old builds once their pinned workflows drain. Confirm it fits your OCP security constraints before committing to it.

## Temporal server and UI on OCP

Two options:

- **Self-hosted:** Temporal's Helm charts with an external PostgreSQL, UI exposed via a Route, mTLS between workers and frontend. [Self-hosted guide](https://docs.temporal.io/self-hosted-guide)
- **Temporal Cloud:** run only the workers in OCP. Far less to operate; Nexus endpoints and Worker Versioning work the same.

## OpenShift specifics

- Images run as an arbitrary non-root UID in group 0 (the default restricted SCC) — the Day 21 `Containerfile` handles it.
- Credentials from `Secret`s as env vars; `NetworkPolicy` so only `device-io-worker` can reach device management networks.
- Readiness: the worker is ready once connected to Temporal; liveness via a small health endpoint or process check.

## Rehearse locally (optional)

OpenShift Local (CRC) needs ~4 cores and 10+ GB free RAM. kind/k3d is lighter for practising Deployments + the Worker Controller.

## Done when

- [ ] A merged PR changes `ConfigComplianceWorkflow`; the pipeline replays old histories, deploys a new build, and in-flight remediations finish on the old build while new ones start on the new build.
- [ ] You've written your own `LEARNING.md` summary of the month. Congratulations.
