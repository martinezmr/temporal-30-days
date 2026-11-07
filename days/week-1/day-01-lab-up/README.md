# Day 01 — Lab up, repo tour

[← Week 1](../README.md) · [Day 02 →](../day-02-eapi-activity/README.md)

## Goal

Temporal server, UI, worker and client all running, and you can read an event history from the CLI.

## Learn

- The split: **Workflow** (deterministic decisions) · **Activity** (any I/O) · **Worker** (your process that runs both) · **Task Queue** (how the server hands work to workers).
- The server stores the **event history**; your worker holds no durable state. Kill it any time.
- Docs: [Workflow basics](https://docs.temporal.io/develop/python/workflows/basics) · [Run a worker](https://docs.temporal.io/develop/python/workers/run-worker-process)

## Build

1. `./lab/start-temporal.sh` and open http://localhost:8233.
2. `cp .env.example .env` and `uv sync`.
3. Terminal 1: `uv run --env-file .env python -m netops_temporal.workers.main`
4. Terminal 2: `uv run --env-file .env python -m netops_temporal.starters.hello Manny`
5. Read `src/netops_temporal/` top to bottom. Note the two task queue names in `constants.py`.

## CLI to learn today

```bash
temporal workflow list
temporal workflow describe --workflow-id hello-manny
temporal workflow show --workflow-id hello-manny          # the event history
temporal workflow show --workflow-id hello-manny -o json  # what replay tests use (Day 6)
```

No CLI on your Mac? `podman exec -it temporal-dev temporal workflow list --address localhost:7233`.

## Break it

- Stop the worker. Start a workflow. Watch it sit in **Running** with a pending workflow task.
- Start the worker again and watch it complete. Nothing was lost.
- `podman restart temporal-dev`, then refresh the UI: your history is still there (that's `--db-filename`).

## Done when

- [ ] You can name each event in `HelloWorkflow`'s history and say who produced it (client, server, worker).
- [ ] `uv run pytest` passes.
