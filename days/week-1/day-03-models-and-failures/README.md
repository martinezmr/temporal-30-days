# Day 03 — Data models and failures

[← Day 02](../day-02-eapi-activity/README.md) · [Day 04 →](../day-04-determinism/README.md)

## Goal

Typed inputs and outputs everywhere, and errors that retry only when retrying can help.

## Learn

- **Single input object:** one pydantic model per workflow/activity input, so you can add fields later without breaking running workflows.
- The Pydantic data converter: `from temporalio.contrib.pydantic import pydantic_data_converter`, set on `Client.connect(..., data_converter=pydantic_data_converter)` for both worker and starter.
- `ApplicationError(msg, non_retryable=True)` stops retries. Or list error type names in `RetryPolicy(non_retryable_error_types=[...])`.
- Docs: [Payload conversion](https://docs.temporal.io/develop/python/data-handling/data-conversion) · [Error handling](https://docs.temporal.io/develop/python/best-practices/error-handling)

## Build

1. `models.py`:

    ```python
    class DeviceFacts(BaseModel):
        device: str
        model: str
        version: str

    class DeviceIntent(BaseModel):
        device: str
        role: str
        site: str
        target_version: str
        config_lines: list[str] = []

    class DeviceState(BaseModel):
        device: str
        version: str
        running_config: str

    class DriftReport(BaseModel):
        device: str
        config_diff: list[str] = []
        version_drift: bool = False

        @property
        def drifted(self) -> bool:
            return bool(self.config_diff) or self.version_drift
    ```

2. Switch `get_device_facts` to return `DeviceFacts`.
3. In the eAPI client, map HTTP 401/403 to `ApplicationError("auth failed", type="AuthError", non_retryable=True)`. Leave timeouts and 5xx retryable.

## Break it

- Put a wrong password in `.env`. The workflow should fail after **one** attempt with `AuthError`.
- Stop a node instead. It should still retry.
- Add a new optional field to `DeviceFacts` while a workflow is mid-retry. Nothing breaks.

## Done when

- [ ] No `dict` crosses a workflow/activity boundary anymore.
- [ ] You can say which of your errors are retryable and why.
