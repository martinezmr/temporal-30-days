# Feature checklist

Tick these off as you go. Each maps to where it lives in the finished orchestrator.

- [ ] Activities with timeouts, retry policies, non-retryable errors — Days 2–3 — every eAPI and Nautobot call
- [ ] Pydantic data converter — Day 3 — all models
- [ ] Determinism and the sandbox — Day 4 — every workflow
- [ ] Thread-pool activities, heartbeats, activity cancellation — Day 5 — blocking SSH libraries, show tech
- [ ] Time-skipping tests, mocked activities, replay tests — Day 6 — CI gate
- [ ] Parallel activities with `asyncio.gather` — Day 7 — state collection
- [ ] Signals, queries, updates with validators — Days 8–10 — orchestrator control plane
- [ ] Update-with-start, signal-with-start — Day 10 — device entity workflows
- [ ] Durable timers, `wait_condition` with timeout — Day 11 — intervals, maintenance windows, approval deadlines
- [ ] Continue-As-New, `all_handlers_finished` — Day 12 — orchestrator lifetime
- [ ] Entity workflow pattern — Day 13 — orchestrator, per-device entities
- [ ] Child workflows, parent close policy — Day 15 — compliance and upgrade children
- [ ] Workflow ID conflict policy — Day 16 — no duplicate remediation
- [ ] Saga / compensation — Day 17 — config session commit and rollback
- [ ] Schedules — Day 18 — nightly full audit
- [ ] Patching and Worker Versioning — Day 19 — CI/CD rollouts
- [ ] Search attributes, user metadata, metrics, tracing — Day 20 — operations
- [ ] Task-queue routing, rate limits, graceful shutdown, payload codec — Day 21 — workers in OCP
- [ ] Nexus sync and workflow-backed operations, endpoints, cancellation — Days 22–24 — compliance team boundary
- [ ] LLM calls as activities, durable agents, human in the loop, MCP — Days 25–28 — explain, troubleshoot, propose

## After Day 30

- **Standalone Activities** (Public Preview) — run an activity without a workflow
- **Task Queue Priority and Fairness** (GA)
- **External Payload Storage** (Public Preview) — keep large configs out of history
- **Workflow Streams** (Public Preview) — stream progress/LLM output to a UI
- **Serverless Workers**, **Temporal Cloud**

## Sources

- [Python SDK developer guide index](https://docs.temporal.io/develop/python/llms.txt)
- [temporalio on PyPI](https://pypi.org/project/temporalio/) · [sdk-python releases](https://github.com/temporalio/sdk-python/releases)
- [Replay 2026 product announcements](https://temporal.io/blog/replay-2026-product-announcements)
- [Nexus Python quickstart](https://docs.temporal.io/develop/python/nexus/quickstart) · [feature guide](https://docs.temporal.io/develop/python/nexus/feature-guide)
- [OpenAI Agents SDK integration](https://docs.temporal.io/develop/python/integrations/openai-agents)
- [Configure a worker for versioning](https://docs.temporal.io/production-deployment/worker-deployments/worker-versioning/configure-worker)
- [Temporal Worker Controller](https://docs.temporal.io/production-deployment/worker-deployments/kubernetes-controller)
