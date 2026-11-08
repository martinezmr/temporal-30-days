# Day 03 — Data models and failures

[← Day 02](../day-02-eapi-activity/README.md) · [Day 04 →](../day-04-determinism/README.md)

**Time:** 60–90 minutes · **Needs the cEOS lab?** Optional (`LAB_MODE=mock` works) · **Solution:** [`solutions/day-03/`](../../../solutions/day-03/)

## Why today matters

Yesterday's workflow retries *everything*. Put a wrong password in `.env` and it will dutifully
try to log in five times. Against a real network with AAA lockout, that's how an automation
account gets locked at 2 a.m. And if you'd set "retry forever", it would keep trying for weeks.

Today you teach the workflow the difference between "the device is down, try again" and "this
will never work, stop now". You also replace yesterday's loose `dict`s with typed models, so the
data your workflows pass around is checked and documented, and can grow without breaking
workflows that are already running.

## Concept

### What actually crosses the wire

When a workflow calls an activity, the arguments don't travel as Python objects. Temporal
serializes them into **payloads** (JSON by default), stores them in the event history, and the
worker running the activity deserializes them. The same happens to return values and workflow
inputs and results. Look back at Day 1's `hello-manny` in the UI: click
**WorkflowExecutionCompleted** and the result is `"Hello, Manny!"` with encoding `json/plain`.

Two consequences:

1. **Everything you pass must be serializable**, and both sides must agree how. The thing that
   does the converting is the **data converter**. Temporal's default handles basic types and
   dataclasses. We'll use the **Pydantic data converter**, so Pydantic models go in and come out
   as real model instances with their types checked.
2. **Payloads live in history for the life of the workflow.** A workflow started today with
   yesterday's input shape has to keep working after you deploy new code. That's why we use
   **one input model per workflow/activity** instead of positional arguments. Adding a field with
   a default (`serial: str | None = None`) to a model is safe; adding a fourth positional argument
   to a function that running workflows call with three is not.

### Retryable vs non-retryable failures

Temporal retries any exception an activity raises, unless you tell it not to. There are two ways:

- **At the source.** The activity raises
  `ApplicationError("auth failed", type="AuthError", non_retryable=True)`. That failure is never
  retried, whatever the caller's retry policy says. Use it when the *activity* knows retrying is
  pointless.
- **At the caller.** The workflow's `RetryPolicy(non_retryable_error_types=["AuthError"])` lists
  error *types* it won't retry. Use it when it's the *caller's* choice. For example, one workflow
  may give up on a timeout that another is happy to retry.

`type` is just a string label, and it matters: it's what `non_retryable_error_types` matches, and
it's what you'll see in the UI and catch in workflow code later.

How to sort network errors:

| Error | Retry? | Why |
| --- | --- | --- |
| Connection refused, timeout, DNS blip, device rebooting | Yes | Likely temporary |
| HTTP 5xx from an API | Yes | Usually temporary |
| Bad credentials (401/403) | **No** | Won't fix itself, and may lock the account |
| Unknown device name, invalid input | **No** | A bug or bad input; retrying can't help |
| Invalid CLI command | **No** | Same command, same error |

### Translate errors once, at the boundary

pyeapi raises `pyeapi.eapilib.ConnectionError` for both "can't connect" and "bad password". Only
the message differs. Netmiko and NAPALM raise their own, different exceptions. If every activity
had to know every library's quirks, the retry logic would be scattered everywhere.

So the device helpers translate library errors into **our own** three types, defined in
`devices/errors.py` on Day 1: `DeviceUnreachableError`, `DeviceAuthError` and
`UnknownDeviceError`. Activities only deal with those three, and decide which ones are worth a
retry. Mock mode raises the same three, which is why the mock switches behave like the real thing.

## Walkthrough

### 1. `models.py`: the shapes of your data

```python
# file: netops_temporal/models.py
from pydantic import BaseModel


class FactsRequest(BaseModel):
    """Input to GetFactsWorkflow and get_device_facts.

    One model instead of positional arguments, so a field can be added later without
    breaking workflows that are already running.
    """

    device: str


class DeviceFacts(BaseModel):
    device: str
    model: str
    version: str
```

### 2. `client.py`: one connection helper for everyone

```python
# file: netops_temporal/client.py
async def connect() -> Client:
    # The Pydantic converter turns models into JSON payloads and back. Worker and starters
    # must agree on it, or one side can't read what the other wrote.
    return await Client.connect(
        TEMPORAL_ADDRESS,
        namespace=TEMPORAL_NAMESPACE,
        data_converter=pydantic_data_converter,
    )
```

The worker and every starter now call `connect()` instead of `Client.connect(...)`:

```python
# file: netops_temporal/workers/main.py
    client = await connect()
```

If you forget to switch a starter, it may *seem* to work: Temporal's default converter has a
fallback for Pydantic models and only prints warnings (`If you're using Pydantic v2, use
temporalio.contrib.pydantic.pydantic_data_converter`). That fallback uses deprecated Pydantic APIs
and doesn't handle every type the way the Pydantic converter does, so the worker and starters can
quietly disagree about the data. One helper means there's only one place to get it right.

### 3. `devices/eapi.py`: translate pyeapi's errors

```python
# file: netops_temporal/devices/eapi.py
    try:
        return node.run_commands(commands)
    except pyeapi.eapilib.ConnectionError as err:
        # pyeapi raises the same ConnectionError for "can't connect" and "bad password";
        # only the message tells them apart. Translate both into our own error types.
        if err.message.startswith("Unauthorized"):
            raise DeviceAuthError(f"{device}: {err.message}") from err
        raise DeviceUnreachableError(f"{device}: {err.message}") from err
```

These are the real messages from the lab:
`Unauthorized. Unable to authenticate user: Bad username/password combination` for a wrong
password, and `Socket error during eAPI connection: [Errno 61] Connection refused` for a device
you can't reach through a stopped tunnel (a stopped device on a routed lab gives a timeout
message instead; both become `DeviceUnreachableError`). `from err` keeps the original pyeapi exception attached, so the full story still
shows up in logs.

### 4. `activities/facts.py`: decide what's worth retrying

```python
# file: netops_temporal/activities/facts.py
@activity.defn
def get_device_facts(req: FactsRequest) -> DeviceFacts:
    activity.logger.info("Getting facts from %s", req.device)
    try:
        [version] = run_show(req.device, ["show version"])
    except DeviceAuthError as err:
        # Retrying with the same wrong password only locks the account: fail now.
        raise ApplicationError(
            f"auth failed for {req.device}", type="AuthError", non_retryable=True
        ) from err
    except UnknownDeviceError as err:
        raise ApplicationError(str(err), type="UnknownDevice", non_retryable=True) from err
    # DeviceUnreachableError is not caught: it fails this attempt and Temporal retries.
    return DeviceFacts(
        device=req.device,
        model=version["modelName"],
        # EOS reports e.g. "4.32.0F-36401836.4320F (engineering build)"; keep the release.
        version=version["version"].split("-")[0],
    )
```

The input and output are now models. `ApplicationError` is from `temporalio.exceptions`; it's
the exception type Temporal understands natively, with a `type` and a `non_retryable` flag. Any
other exception (like our `DeviceUnreachableError`) is wrapped in an `ApplicationError` for you,
with `type` set to the exception's class name, and is retryable.

### 5. `workflows/facts.py` and `starters/facts.py`: typed end to end

```python
# file: netops_temporal/workflows/facts.py
with workflow.unsafe.imports_passed_through():
    from netops_temporal.activities.facts import get_device_facts
    from netops_temporal.models import DeviceFacts, FactsRequest


@workflow.defn
class GetFactsWorkflow:
    @workflow.run
    async def run(self, req: FactsRequest) -> DeviceFacts:
        return await workflow.execute_activity(
            get_device_facts,
            req,
```

The model module is imported with `imports_passed_through()` too: Pydantic is a large library and
doesn't need to be re-imported inside the workflow sandbox. The retry policy is unchanged from
Day 2. Auth errors simply don't use it.

```python
# file: netops_temporal/starters/facts.py
            client.execute_workflow(
                GetFactsWorkflow.run,
                FactsRequest(device=device),
```

## Run it

Restart the worker (it has new code), then:

```bash
uv run --env-file .env python -m netops_temporal.starters.facts
```

Expected (models print as fields now):

```
bos-rtr-01: device='bos-rtr-01' model='cEOSLab' version='4.32.0F'
...
```

In the UI, open `facts-bos-rtr-01` and click **WorkflowExecutionStarted**: the input is the JSON
`{"device": "bos-rtr-01"}`. Click **ActivityTaskCompleted**: the result is the `DeviceFacts`
JSON. That's what the data converter produced, and what history stores forever.

## Break it

1. **Wrong password.** Set `DEVICE_PASSWORD=wrong` in `.env` (mock: `MOCK_AUTH_FAIL=1`), restart
   the worker, and run the starter for one device. It fails **immediately**. The failure chain in
   the UI reads `WorkflowExecutionFailed` ← `ActivityError` ← `ApplicationError` with type
   `AuthError` and **non-retryable: true**. Open **ActivityTaskStarted**: `attempt: 1`. One login
   attempt, not five. Put the password back.
2. **Device down.** Stop a device (mock: `MOCK_UNREACHABLE=bos-rtr-01`). It still retries 5 times,
   because `DeviceUnreachableError` is retryable. The failure type in the UI is
   `DeviceUnreachableError`.
3. **Typo in a device name.** Run `... starters.facts bos-rtr-1`. It fails at once with
   `UnknownDevice`, and the message lists the devices it does know.
4. **Grow a model under a running workflow.** Start a workflow that will retry for a while
   (device down, and raise `maximum_attempts` to 20 first). While it's retrying, add
   `serial: str | None = None` to `DeviceFacts`, restart the worker, and bring the device back.
   The workflow completes with the new field set to `None`. Old input, new code, no breakage.
   Now imagine you'd added a required positional argument instead. Revert when done.

## Check yourself

1. Which of your errors are retryable, and why?
2. What would happen to an automation account if auth errors retried forever?
3. When would you use `RetryPolicy(non_retryable_error_types=[...])` instead of
   `non_retryable=True` in the activity?
4. Why does every workflow and activity take a single model instead of several arguments?
5. Why do the device helpers raise our own exception types instead of letting pyeapi's escape?

<details>
<summary>Answers</summary>

1. `DeviceUnreachableError` is retryable: connection problems are often temporary. `AuthError` and
   `UnknownDevice` are not: same input, same result, every time.
2. With AAA lockout, repeated failed logins would lock the account, breaking every other job that
   uses it. Without lockout you'd hammer the TACACS/RADIUS servers and fill logs, forever.
3. When retrying is a judgment call that differs per caller. For example, one workflow wants a
   fast failure on `DeviceUnreachableError` while another is happy to wait.
4. Inputs are stored in history and replayed against newer code. A model can gain optional
   fields without breaking old payloads; a function signature can't gain required arguments.
5. So activities (and their retry decisions) don't depend on each library's quirks, and so mock
   mode can raise exactly the same errors as the real thing.

</details>

## Solution

[`solutions/day-03/`](../../../solutions/day-03/): new `models.py` and `client.py`; updated
`devices/eapi.py`, `activities/facts.py`, `workflows/facts.py`, the worker, and both starters.
`tests/test_facts.py` checks that auth errors run exactly one attempt and unreachable devices run
five.
