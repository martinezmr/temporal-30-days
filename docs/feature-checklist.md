# Feature checklist

Tick these off as you go. Each maps to where it lives in the finished orchestrator.

- [ ] Activities with timeouts, retry policies, non-retryable errors — Days [2](../days/week-1/day-02-eapi-activity/README.md)–[3](../days/week-1/day-03-models-and-failures/README.md) — every pyeapi, Netmiko, NAPALM and Nautobot call
- [ ] Pydantic data converter — Day [3](../days/week-1/day-03-models-and-failures/README.md) — all models
- [ ] Determinism and the sandbox — Day [4](../days/week-1/day-04-determinism/README.md) — every workflow
- [ ] Thread-pool (sync) activities, heartbeats, activity cancellation — Days [2](../days/week-1/day-02-eapi-activity/README.md) and [5](../days/week-1/day-05-heartbeats-and-threads/README.md) — pyeapi and Netmiko show tech
- [ ] Time-skipping tests, stubbed activities, mock lab, replay tests — Day [6](../days/week-1/day-06-testing/README.md) — CI gate
- [ ] Parallel activities with `asyncio.gather`, partial failure as data — Day [7](../days/week-1/day-07-parallel-backup/README.md) — NAPALM backups + Nautobot intent
- [ ] Signals, queries, updates with validators — Days [8](../days/week-2/day-08-signals/README.md)–[10](../days/week-2/day-10-updates/README.md) — orchestrator control plane
- [ ] Update-with-start, signal-with-start — Day [10](../days/week-2/day-10-updates/README.md) — device entity workflows
- [ ] Durable timers, `wait_condition` with timeout — Day [11](../days/week-2/day-11-timers/README.md) — intervals, maintenance windows, approval deadlines
- [ ] Continue-As-New, `all_handlers_finished` — Day [12](../days/week-2/day-12-continue-as-new/README.md) — orchestrator lifetime
- [ ] Entity workflow pattern — Day [13](../days/week-2/day-13-entity-workflows/README.md) — orchestrator, per-device entities
- [ ] Child workflows, parent close policy — Day [15](../days/week-3/day-15-child-workflows/README.md) — compliance and upgrade children
- [ ] Workflow ID conflict policy — Day [16](../days/week-3/day-16-fan-out/README.md) — no duplicate remediation
- [ ] Saga / compensation — Day [17](../days/week-3/day-17-saga-rollback/README.md) — NAPALM candidate/commit/rollback
- [ ] Schedules — Day [18](../days/week-3/day-18-schedules/README.md) — nightly full audit
- [ ] Patching and Worker Versioning (pinned, auto-upgrade, ramping) — Days [19](../days/week-3/day-19-versioning/README.md) and [30](../days/capstone/day-30-worker-versioning/README.md) — v1 and v2 workers side by side, locally
- [ ] Search attributes, user metadata, metrics, tracing — Day [20](../days/week-3/day-20-observability/README.md) — operations
- [ ] Task-queue routing, rate limits, graceful shutdown, payload codec — Day [21](../days/week-3/day-21-production-workers/README.md) — production-shaped workers, locally
- [ ] Nexus sync and workflow-backed operations, endpoints, cancellation — Days [22](../days/week-4/day-22-nexus-sync/README.md)–[24](../days/week-4/day-24-nexus-contracts/README.md) — compliance team boundary
- [ ] LLM calls as activities (any OpenAI-compatible API), durable agents, human in the loop, MCP — Days [25](../days/week-4/day-25-llm-activity/README.md)–[28](../days/week-4/day-28-mcp-guardrails/README.md) — explain, troubleshoot, propose

## After Day 30

- **Standalone Activities** (Public Preview) — run an activity without a workflow
- **Task Queue Priority and Fairness** (GA)
- **External Payload Storage** (Public Preview) — keep large configs out of history
- **Workflow Streams** (Public Preview) — stream progress/LLM output to a UI
- **Serverless Workers**, **Temporal Cloud**, and running workers on Kubernetes/OpenShift (the [Temporal Worker Controller](https://docs.temporal.io/production-deployment/worker-deployments/kubernetes-controller))

## Sources

- [Python SDK developer guide index](https://docs.temporal.io/develop/python/llms.txt)
- [temporalio on PyPI](https://pypi.org/project/temporalio/) · [sdk-python releases](https://github.com/temporalio/sdk-python/releases)
- [Replay 2026 product announcements](https://temporal.io/blog/replay-2026-product-announcements)
- [Nexus Python quickstart](https://docs.temporal.io/develop/python/nexus/quickstart) · [feature guide](https://docs.temporal.io/develop/python/nexus/feature-guide)
- [OpenAI Agents SDK integration](https://docs.temporal.io/develop/python/integrations/openai-agents)
- [Configure a worker for versioning](https://docs.temporal.io/production-deployment/worker-deployments/worker-versioning/configure-worker)
