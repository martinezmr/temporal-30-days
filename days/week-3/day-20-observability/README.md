# Day 20 — Observability: "what happened to bos-acc-01?"

[← Day 19](../day-19-versioning/README.md) · [Day 21 →](../day-21-production-workers/README.md)

**Time:** 90 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-20/`](../../../solutions/day-20/)

## Why today matters

Monday morning, a ticket: "bos-acc-01 lost its NTP config over the weekend. Did the automation do
it?" With scripts, you grep logs on three servers and hope they weren't rotated. With what you've
built so far, every change is in some workflow's history, but which workflow? There are hundreds.

Today you make the automation answerable:

- **Search attributes**: tag workflows with the device and the outcome, so one query lists every
  workflow that touched `bos-acc-01`, or every remediation that rolled back.
- **Summaries and current details**: text the UI shows, so you can read what a workflow is for
  and what it's doing without opening its history.
- **Metrics**: the SDK's own Prometheus metrics, for dashboards and alerts.
- **Tracing**: OpenTelemetry spans that follow one cycle through the orchestrator, its children
  and their activities.

## Concept

### Search attributes: an index over workflows

Every workflow already has built-in fields you can query: `WorkflowType`, `ExecutionStatus`,
`StartTime`, and so on (`temporal workflow list --query 'WorkflowType="ConfigRemediationWorkflow"'`).
**Custom search attributes** add your own fields. Today, two keywords:

| Attribute | Set by | Values |
| --- | --- | --- |
| `Device` | The orchestrator, when it starts a child | `bos-acc-01`, ... |
| `ComplianceStatus` | The remediation, when it ends | `planned`, `fixed`, `rolled-back`, `failed`, `cancelled` |

Then:

```bash
temporal workflow list --query 'Device="bos-acc-01"'
temporal workflow list --query 'ComplianceStatus="rolled-back" AND StartTime > "2026-11-01T00:00:00Z"'
```

The same queries work in the UI's search box. A visibility query is the fastest way to answer
"what happened to device X": it lists the workflows, and each history has the details.

Search attributes have to be **registered** on the server before anything uses them. A workflow
that sets an unknown one fails its workflow task. `lab/start-temporal.sh` now registers both.

Search attributes are an index, not a database: keep them small, and never put secrets in them.
They're visible to anyone who can list workflows.

### Summaries, details and current details

Three bits of text the UI shows on a workflow's page:

- **Summary** (`static_summary`): one line, set when the workflow starts: "config remediation for
  bos-acc-01 (dry run)". It shows in the workflow list too.
- **Details** (`static_details`): longer text, also set at start. Here, the missing lines.
- **Current details** (`workflow.set_current_details(...)`): set by the workflow while it runs,
  and changed whenever it likes. Markdown, so the orchestrator shows a table of every device.

None of these are commands: setting them doesn't change replay, and doesn't need a patch.

### An upsert *is* a command

`workflow.upsert_search_attributes(...)` changes the workflow's search attributes while it runs,
and it's recorded in history as a command. So adding an upsert to an existing workflow is exactly
Day 19's situation: a remediation that started on Day 17 code has no upsert in its history. The
course found this out from `tests/histories/remediation_rollback.json`: the replay test failed with
`UpsertWorkflowSearchAttributesMachine does not handle HistoryEvent(... WorkflowExecutionCompleted)`.
The upsert is behind `workflow.patched()`.

### Metrics

The SDK can serve Prometheus metrics: workflows started and completed, activity latency, task
queue polling, slots in use, and more, all labelled by workflow and activity type. It's built into
the SDK; you just give it a port. Prometheus scrapes `http://localhost:9464/metrics`, and Grafana
draws dashboards from it. (Grafana is optional and not part of the course lab: `curl` is enough to
see the numbers.)

### Tracing

A trace is a tree of **spans**, one per piece of work, with timings. Temporal's
`TracingInterceptor` makes spans for starting and running workflows, signals, activities and
children, and carries the trace across the server in headers, so one trace follows the work from
the orchestrator into a child workflow and its activities, even on another worker.

By default it only makes workflow spans when the client that started the workflow traced the
start too. The orchestrator is started from the CLI, a starter or a schedule, so the course turns
on `always_create_workflow_spans`. Today's spans print to the console. In production you'd send
them to a collector (Jaeger, Tempo, ...) instead; the interceptor is the same.

## Walkthrough

### 1. `observability.py`

```python
# file: netops_temporal/observability.py
DEVICE_SA = SearchAttributeKey.for_keyword("Device")
# How a remediation ended: planned (dry run), fixed, rolled-back, failed or cancelled.
COMPLIANCE_SA = SearchAttributeKey.for_keyword("ComplianceStatus")


def runtime_with_metrics(port: int = 9464) -> Runtime:
    """A Temporal runtime that serves Prometheus metrics. Pass it to Client.connect(runtime=...)."""
    return Runtime(
        telemetry=TelemetryConfig(metrics=PrometheusConfig(bind_address=f"127.0.0.1:{port}"))
    )
```

`tracing_interceptor()` sets up OpenTelemetry with a console exporter and returns the
`TracingInterceptor`. (The course now depends on `temporalio[opentelemetry]` and
`opentelemetry-sdk`; `uv sync` installs them.)

### 2. `workflows/orchestrator.py`: tag and describe each child

```python
# file: netops_temporal/workflows/orchestrator.py
                            id=f"remediate-config-{drift.device}",
                            # Day 20: findable by device, and readable at a glance in the UI.
                            search_attributes=TypedSearchAttributes(
                                [SearchAttributePair(DEVICE_SA, drift.device)]
                            ),
                            static_summary=(
                                f"config remediation for {drift.device}"
                                + (" (dry run)" if dry_run else "")
                            ),
                            static_details="Missing lines:\n"
                            + "\n".join(f"- `{line}`" for line in drift.missing_lines),
```

A workflow starts with `TypedSearchAttributes([SearchAttributePair(key, value), ...])`. Changing
them later (step 3, below) takes updates instead: `key.value_set(value)`.

Upgrade children get `Device` and a summary too. After every cycle:

```python
# file: netops_temporal/workflows/orchestrator.py
            # Day 20: what the UI shows under "Current Details" for this workflow.
            workflow.set_current_details(self.details_table())
```

`details_table()` builds a markdown table of each device's status and last action.

### 3. `workflows/remediation.py`: record the outcome

The Day 17 saga moved, unchanged, into a `remediate` method, and `run` records how it ended:

```python
# file: netops_temporal/workflows/remediation.py
    @workflow.run
    async def run(self, req: RemediationRequest) -> RemediationResult:
        result = await self.remediate(req)
        # Day 20: record how it ended, so `ComplianceStatus="rolled-back"` finds it.
        if not result.ok:
            outcome = "rolled-back" if result.rolled_back else "failed"
        else:
            outcome = "planned" if req.dry_run else "fixed"
        self.set_outcome(outcome)
        return result

    def set_outcome(self, outcome: str) -> None:
        # The attribute must be registered on the server first (lab/start-temporal.sh does).
        # An upsert is a new command, so Day 19's rule applies: remediations that started on
        # Day 17 code have no upsert in their history, and must replay without one.
        if workflow.patched("remediation-outcome-search-attribute"):
            workflow.upsert_search_attributes([COMPLIANCE_SA.value_set(outcome)])
```

A cancelled remediation sets `cancelled` before re-raising.

### 4. `workers/main.py` and `client.py`

`connect()` takes an optional `runtime` and `interceptors`. The worker passes them when asked:

```python
# file: netops_temporal/workers/main.py
    # Day 20: METRICS_PORT=9464 serves Prometheus metrics; OTEL_CONSOLE=1 prints trace spans.
    port = os.environ.get("METRICS_PORT")
    runtime = runtime_with_metrics(int(port)) if port else None
    interceptors = [tracing_interceptor()] if os.environ.get("OTEL_CONSOLE") == "1" else []
    client = await connect(runtime=runtime, interceptors=interceptors)
```

### 5. Tests

`tests/conftest.py` registers both attributes on the time-skipping server and the dev server.
`tests/test_observability.py` checks that `Device="bos-acc-01"` and
`ComplianceStatus="planned"` find the child, the child's summary and details, the orchestrator's
current details (read through `__temporal_workflow_metadata`, the built-in query the UI uses), and
that a worker with the metrics runtime serves `temporal_workflow_completed` on `/metrics`.

## Run it

Register the attributes. Either re-run `./lab/start-temporal.sh` (your data is kept in its
volume), or add them to the running server:

```bash
temporal operator search-attribute create --name Device --type Keyword
temporal operator search-attribute create --name ComplianceStatus --type Keyword
```

Restart the worker with metrics, tracing, and one device whose pushes won't stick:

```bash
LAB_MODE=mock METRICS_PORT=9464 OTEL_CONSOLE=1 MOCK_VERIFY_FAIL=nyc-rtr-01 \
  uv run --env-file .env python -m netops_temporal.workers.main
```

Terminate any old `orchestrator` and `upgrade-nyc-acc-01`, then
`... starters.orchestrator start --apply`. After a few seconds:

```bash
temporal workflow list --query 'Device="nyc-rtr-01"'
temporal workflow list --query 'ComplianceStatus="rolled-back"'
```

Expected, for both:

```
   Status            WorkflowId                     Type               StartTime
  Completed  remediate-config-nyc-rtr-01  ConfigRemediationWorkflow  8 seconds ago
```

In the UI:

- The workflow list shows each child's summary.
- `orchestrator` → **Current Details** is the device table.
- `remediate-config-nyc-rtr-01` shows its summary, its missing lines as details, and
  `ComplianceStatus: rolled-back` among its search attributes.

## Break it

1. **Query an attribute that doesn't exist.** `temporal workflow list --query 'Site="bos"'`:
   `invalid query: invalid expression: column name 'Site' is not a valid search attribute`. A
   workflow that tried to *set* an unregistered attribute would fail its workflow task instead
   (the tests saw `search attribute ComplianceStatus is not defined` before the fixtures
   registered it).
2. **Read the metrics.** While the worker is busy, run
   `curl -s localhost:9464/metrics | grep temporal_activity_execution_latency_count`. One line per
   activity type and workflow type, with a count. Run `force-check` and curl again: the counts go
   up. Look for `temporal_worker_task_slots_available` too: Day 21 is about those slots.
3. **Follow one cycle's spans.** With `OTEL_CONSOLE=1`, run `force-check` and read the worker's
   output. You'll find `HandleSignal:force_check`, then `StartActivity:` and `RunActivity:` for
   each check, `StartChildWorkflow:ConfigRemediationWorkflow`, the child's `RunWorkflow:` and its
   activities. They all share one `trace_id`, and each span's `parent_id` points at the span that
   caused it.
4. **Forget the patch.** Remove the `if workflow.patched(...)` line (keep the upsert) and run
   `scripts/test-solutions.sh 20`: `test_replay_committed_histories[remediation_rollback]` fails.

## Check yourself

1. How do you list every workflow that touched `bos-acc-01` this week?
2. Why must a search attribute be registered before a workflow uses it?
3. What's the difference between `static_summary` and `set_current_details`?
4. Why does the `ComplianceStatus` upsert need a patch, when the child's `static_summary` doesn't?
5. What would you alert on, from the metrics, to know the workers are falling behind?

<details>
<summary>Answers</summary>

1. `temporal workflow list --query 'Device="bos-acc-01" AND StartTime > "<a week ago>"'` (or the
   same query in the UI).
2. The server indexes it with a type (keyword, int, datetime...). It rejects attributes it doesn't
   know, rather than guess the type: the workflow task fails.
3. The summary is set once, when the workflow starts. Current details are set by the workflow,
   as often as it likes, while it runs.
4. The upsert is a command, recorded in history, so old histories without it no longer match.
   The summary is metadata on the start command, and isn't compared during replay.
5. Task queue backlog and schedule-to-start latency (work waiting for a worker), and slots
   available reaching zero. Day 21 looks at this.

</details>

## Solution

[`solutions/day-20/`](../../../solutions/day-20/): new `observability.py`; search attributes,
summaries and current details in `workflows/orchestrator.py`; the patched outcome upsert in
`workflows/remediation.py`; metrics and tracing in `workers/main.py` and `client.py`;
`lab/start-temporal.sh` registers `Device` and `ComplianceStatus`. `tests/test_observability.py`
checks the search attributes, summary, current details and the metrics endpoint.
