# Feature checklist

Tick these off as you go. Each maps to where it lives in the finished orchestrator.

- [ ] Activities with timeouts, retry policies, non-retryable errors — Days 2–3 — every pyeapi, Netmiko, NAPALM and Nautobot call
- [ ] Pydantic data converter — Day 3 — all models
- [ ] Determinism and the sandbox — Day 4 — every workflow
- [ ] Thread-pool (sync) activities, heartbeats, activity cancellation — Days 2 and 5 — pyeapi and Netmiko show tech
- [ ] Time-skipping tests, stubbed activities, mock lab, replay tests — Day 6 — CI gate
- [ ] Parallel activities with `asyncio.gather`, partial failure as data — Day 7 — NAPALM backups + Nautobot intent
- [ ] Signals, queries, updates with validators — Days 8–10 — orchestrator control plane
- [ ] Update-with-start, signal-with-start — Day 10 — device entity workflows
- [ ] Durable timers, `wait_condition` with timeout — Day 11 — intervals, maintenance windows, approval deadlines
- [ ] Continue-As-New, `all_handlers_finished` — Day 12 — orchestrator lifetime
- [ ] Entity workflow pattern — Day 13 — orchestrator, per-device entities
- [ ] Child workflows, parent close policy — Day 15 — compliance and upgrade children
- [ ] Workflow ID conflict policy — Day 16 — no duplicate remediation
- [ ] Saga / compensation — Day 17 — NAPALM candidate/commit/rollback
- [ ] Schedules — Day 18 — nightly full audit
- [ ] Patching and Worker Versioning — Days 19 and 30 — v1 and v2 workers side by side, locally
- [ ] Search attributes, user metadata, metrics, tracing — Day 20 — operations
- [ ] Task-queue routing, rate limits, graceful shutdown, payload codec — Day 21 — production-shaped workers, locally
- [ ] Nexus sync and workflow-backed operations, endpoints, cancellation — Days 22–24 — compliance team boundary
- [ ] LLM calls as activities (GitHub Copilot models), durable agents, human in the loop, MCP — Days 25–28 — explain, troubleshoot, propose

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
