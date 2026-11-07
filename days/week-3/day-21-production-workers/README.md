# Day 21 — Production-shaped workers

[← Day 20](../day-20-observability/README.md) · [Week 4 →](../../week-4/README.md)

## Goal

Workers you'd be comfortable running in OpenShift: split by job, gentle on devices, no secrets in history, packaged as a container.

## Learn

- Route work by task queue: workflows on `netops-orchestration`, device I/O on `netops-device-io`. Scale and limit them separately.
- Protect devices: `max_concurrent_activities` per worker, `max_task_queue_activities_per_second` across all workers on a queue.
- Payload codecs encrypt payloads before they reach the server.
- Docs: [Workers](https://docs.temporal.io/develop/python/workers) · [Payload encryption](https://docs.temporal.io/develop/python/data-handling/data-encryption)

## Build

1. Split `workers/main.py` into `workers/orchestration.py` (workflows) and `workers/device_io.py` (activities). Pass `task_queue=DEVICE_IO_TASK_QUEUE` on device activity calls.
2. Device worker: `max_concurrent_activities=4`, `max_task_queue_activities_per_second=2.0`.
3. Credentials only from env vars inside activities — never in workflow inputs (they'd be stored in history).
4. Graceful shutdown: handle SIGTERM → `await worker.shutdown()`; set `graceful_shutdown_timeout`.
5. `Containerfile`:

    ```dockerfile
    FROM python:3.13-slim
    COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
    WORKDIR /app
    COPY pyproject.toml uv.lock ./
    RUN uv sync --frozen --no-dev --no-install-project
    COPY src ./src
    RUN uv sync --frozen --no-dev
    ARG BUILD_ID=dev
    ENV BUILD_ID=$BUILD_ID PATH="/app/.venv/bin:$PATH"
    # OpenShift runs as a random UID in group 0
    RUN chgrp -R 0 /app && chmod -R g=u /app
    USER 1001
    ENTRYPOINT ["python", "-m"]
    CMD ["netops_temporal.workers.orchestration"]
    ```

6. Run it on the `clab` network so it reaches the devices:

    ```bash
    podman build -t netops-worker --build-arg BUILD_ID=$(git rev-parse --short HEAD) .
    podman run --rm --network clab --env-file .env netops-worker netops_temporal.workers.device_io
    ```

## Break it

`podman stop` the device worker mid-activity. It should finish or hand back the activity cleanly, and another worker picks it up.

## Done when

- [ ] Two containers (orchestration, device-io) run the whole system.
- [ ] `grep -r password` over a workflow's exported history finds nothing.
