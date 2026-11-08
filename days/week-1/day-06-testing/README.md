# Day 06 — Testing Temporal code

[← Day 05](../day-05-heartbeats-and-threads/README.md) · [Day 07 →](../day-07-parallel-backup/README.md)

**Time:** 60–90 minutes · **Needs the cEOS lab?** No · **Solution:** [`solutions/day-06/`](../../../solutions/day-06/)

## Why today matters

Your workflows now retry for 30 seconds, wait on heartbeats, and will soon sleep until maintenance
windows days away. Testing that by hand ("stop a container, wait, watch the UI") doesn't scale,
and it won't run in CI. Worse, Day 4 showed that an innocent-looking edit can strand running
workflows, and you'd only find out in production.

Every solution so far has shipped with tests. Today you learn how they work, organize them, and
add the one that protects you on every deploy: the **replay test**.

## Concept

### Three layers

| Layer | What runs | Tool | Catches |
| --- | --- | --- | --- |
| **1. Activity unit tests** | One activity function, no server | `ActivityEnvironment` | Parsing bugs, error mapping, heartbeat/resume logic |
| **2. Workflow tests** | Real workflows on a real (local, in-process) Temporal test server, with real or stubbed activities | `WorkflowEnvironment.start_time_skipping()` | Wrong retry/timeout settings, wrong error handling, wrong orchestration logic |
| **3. Replay tests** | Today's workflow code against histories recorded from earlier runs; no server, no activities | `Replayer` | Non-deterministic changes that would break running workflows |

### Time skipping

`WorkflowEnvironment.start_time_skipping()` downloads and starts a small Temporal test server
(the first run takes a few seconds). Whenever every workflow is just *waiting* (for a retry
backoff, a timer, a deadline), it jumps the clock forward. Day 2's retry policy waits 2 + 4 + 8 +
16 = 30 s; in a time-skipping test, five failing attempts finish in milliseconds. In Week 2, a
workflow that sleeps until Saturday's maintenance window is tested the same way.

### Mock lab vs stubbed activities

Two ways to keep devices out of workflow tests:

- **Mock lab** (`LAB_MODE=mock`): the *real* activities run, and the device helpers return
  recorded outputs. Good for testing activity + workflow together, including the failure switches
  (`MOCK_UNREACHABLE`, `MOCK_AUTH_FAIL`).
- **Stubbed activity**: register a test function with the **same activity name**
  (`@activity.defn(name="get_device_facts")`). The workflow can't tell the difference, because
  workflows call activities by name. Good for testing workflow logic in isolation, or for forcing
  exact results ("what does the workflow do with version 9.99.9F?").

### Replay tests are your deploy safety net

A replay test takes a history saved from a real run and replays it against the current workflow
code, exactly as a worker would after a deploy. If the code now makes different decisions, the
test fails with a nondeterminism error, **before** you ship. The workflow is:

1. Run a workflow (ideally against the real lab).
2. Export its history to `tests/histories/<name>.json`.
3. Commit it. From then on, every `pytest` run replays it.

When you *intend* to change a workflow's behavior, the old histories tell you which running
workflows would break, and Day 19's versioning tools let you change it safely.

## Walkthrough

### 1. `workers/main.py`: one list, used by the worker and the tests

```python
# file: netops_temporal/workers/main.py
# One list of everything this worker runs. Tests and replay import these too, so a test
# worker can never drift from the real one.
WORKFLOWS = [HelloWorkflow, GetFactsWorkflow, ShowTechWorkflow]
ACTIVITIES = [say_hello, get_device_facts, collect_show_tech]
```

The `Worker(...)` call now uses `workflows=WORKFLOWS, activities=ACTIVITIES`. From here on,
registering something new means adding it to these lists.

### 2. `tests/conftest.py`: shared fixtures

pytest loads `conftest.py` automatically and makes its fixtures available to every test file.

```python
# file: tests/conftest.py
@pytest.fixture(autouse=True)
def mock_lab(monkeypatch, tmp_path):
    """Every test runs against the mock lab, with outputs in a throwaway directory."""
    monkeypatch.setenv("LAB_MODE", "mock")
    for name in ("MOCK_UNREACHABLE", "MOCK_AUTH_FAIL", "MOCK_CLI_DELAY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(show_tech, "OUTPUT_DIR", tmp_path)
    return tmp_path


@pytest.fixture
async def workflow_env():
    """A local Temporal test server that skips ahead whenever workflows are only waiting."""
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        yield env


@pytest.fixture
async def worker(workflow_env):
    """A worker on TASK_QUEUE with the same workflows and activities as the real one."""
    with ThreadPoolExecutor(max_workers=10) as executor:
        async with Worker(
            workflow_env.client,
            task_queue=TASK_QUEUE,
            workflows=WORKFLOWS,
            activities=ACTIVITIES,
            activity_executor=executor,
        ) as running:
            yield running
```

- `autouse=True` means every test gets the mock lab without asking. A test that wants a failure
  just sets the switch: `monkeypatch.setenv("MOCK_UNREACHABLE", "bos-rtr-01")`. `monkeypatch`
  undoes it after the test.
- The test server uses the **same Pydantic data converter** as `client.connect()`.
- `async with Worker(...)` runs the worker for the duration of the test, then shuts it down.

### 3. Layer 1: activity unit tests

```python
# file: tests/test_facts.py
# Layer 1: activity unit tests. No server, no worker: just call the activity.
def test_get_device_facts_mock():
    facts = ActivityEnvironment().run(get_device_facts, FactsRequest(device="bos-rtr-01"))
    assert facts == DeviceFacts(device="bos-rtr-01", model="cEOSLab", version="4.32.0F")
```

`ActivityEnvironment` gives the activity a fake `activity.info()`, captures heartbeats, and can
simulate cancellation. Day 5's tests use all three:

```python
# file: tests/test_show_tech.py
def test_resumes_from_heartbeat_details(cli_calls):
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, heartbeat_details=[4])
```

That's "pretend a previous attempt got through 4 commands". The test then checks that only
commands 5–10 were sent.

### 4. Layer 2: workflow tests, with real or stubbed activities

With the mock lab and the shared `worker` fixture:

```python
# file: tests/test_facts.py
async def test_auth_failure_is_not_retried(workflow_env, worker, monkeypatch):
    monkeypatch.setenv("MOCK_AUTH_FAIL", "1")
    result, history = await run_facts_workflow(workflow_env, worker, "bos-rtr-01")
    assert root_cause(result).type == "AuthError"
    assert root_cause(result).non_retryable
    assert attempts(history) == 1
```

The test asserts on the **history** (`handle.fetch_history()`), the same events you read in the
UI: exactly one `ActivityTaskStarted`, attempt 1.

With a stubbed activity instead of the real one:

```python
# file: tests/test_testing_layers.py
@activity.defn(name="get_device_facts")
def stub_get_device_facts(req: FactsRequest) -> DeviceFacts:
    return DeviceFacts(device=req.device, model="stub", version="9.99.9F")
```

That test builds its own worker registering `stub_get_device_facts`, so no device code runs at all.

Time skipping, proven:

```python
# file: tests/test_testing_layers.py
async def test_retry_backoff_uses_time_skipping(workflow_env, worker, monkeypatch):
    """Five attempts with 2+4+8+16 s of backoff, finished in well under 30 s of real time."""
    monkeypatch.setenv("MOCK_UNREACHABLE", "bos-rtr-01")
    started = time.monotonic()
    with pytest.raises(WorkflowFailureError):
...
    assert time.monotonic() - started < 5
```

### 5. Layer 3: replay tests

First, a tool to save histories, `tools/export_history.py`:

```python
# file: netops_temporal/tools/export_history.py
async def export_history(client: Client, workflow_id: str, path: Path) -> None:
    history = await client.get_workflow_handle(workflow_id).fetch_history()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(history.to_json())
```

The histories in the solution were exported from live runs against the course lab:

```bash
uv run --env-file .env python -m netops_temporal.tools.export_history facts-bos-rtr-01 tests/histories/get_facts.json
uv run --env-file .env python -m netops_temporal.tools.export_history show-tech-bos-rtr-01 tests/histories/show_tech.json
```

`temporal workflow show --workflow-id facts-bos-rtr-01 -o json > tests/histories/get_facts.json`
produces the same file. Then the test replays every file in the folder:

```python
# file: tests/test_testing_layers.py
@pytest.mark.parametrize("path", history_files(), ids=lambda p: p.stem)
async def test_replay_committed_histories(path):
    history = WorkflowHistory.from_json(path.stem, path.read_text())
    await Replayer(workflows=WORKFLOWS, data_converter=pydantic_data_converter).replay_workflow(
        history
    )
```

Adding a history file adds a test case; there's nothing else to change.

## Run it

```bash
uv run pytest -q                         # your tests
scripts/test-solutions.sh 06             # the solution's 41 tests, about 2 seconds
```

Export a history of your own (worker running, after a facts run):

```bash
uv run --env-file .env python -m netops_temporal.tools.export_history facts-nyc-acc-01 tests/histories/facts_nyc.json
uv run pytest -q -k replay
```

## Break it

1. **A careless edit.** In `GetFactsWorkflow.run`, add `await workflow.sleep(1)` as the first
   line (a harmless-looking pause). Run `uv run pytest -q -k replay`. The replay tests fail with a
   nondeterminism error: the new code starts a timer where history recorded scheduling
   `get_device_facts`. Running workflows would break the same way. Revert.
2. **Same edit, different test.** With the sleep still in, run the other tests
   (`-k "not replay"`). Everything passes except `test_collected_at_uses_workflow_time`, and only
   by luck: it notices the timestamp moved by a second. None of them knows that running
   workflows would break. Only replay tests catch this class of bug, which is why they go in CI
   (Day 30).
3. **Stub drift.** Rename the stub's `name=` to `"get_device_fact"` (missing *s*) and run its test.
   It hangs until pytest's or the workflow's timeout, because the workflow calls an activity no
   worker has. Same symptom as Day 1's unregistered activity.

## Check yourself

1. Which test layer catches a non-deterministic code change?
2. Why is time skipping essential for testing a retry policy, and later, maintenance windows?
3. When would you stub an activity instead of using the mock lab?
4. How does a stubbed activity replace the real one, given the workflow imports the real function?
5. What should you do after an *intentional* change makes an old history fail to replay?

<details>
<summary>Answers</summary>

1. Layer 3, replay tests. Layer 2 tests run new code from a fresh start, so they never compare
   against an old history.
2. Real waits make tests slow (30 s of backoff per test, or days for a window). Time skipping
   jumps the clock whenever workflows are only waiting.
3. When you want to test workflow logic alone, force exact results, or avoid device code
   entirely, for example a version the lab doesn't run.
4. Workflows schedule activities **by name**. The worker in the test registers a different
   function under the same name, so that's what runs.
5. Decide whether workflows of the old shape might still be running. If so, make the change with
   versioning (Day 19). Once none can be running, replace the old history with a new one.

</details>

## Solution

[`solutions/day-06/`](../../../solutions/day-06/): `WORKFLOWS`/`ACTIVITIES` in
`workers/main.py`, `tools/export_history.py`, `tests/conftest.py`, `tests/histories/` (two real
histories), `tests/test_testing_layers.py`, and the earlier test files moved onto the shared
fixtures.
