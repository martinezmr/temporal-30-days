# Day 04 — Determinism and the sandbox

[← Day 03](../day-03-models-and-failures/README.md) · [Day 05 →](../day-05-heartbeats-and-threads/README.md)

## Goal

Understand replay well enough to never be surprised by a non-determinism error in CI/CD.

## Learn

- When a worker picks up a workflow, it **replays** the history through your code. The code must make the same decisions in the same order.
- Safe replacements: `workflow.now()`, `workflow.random()`, `workflow.uuid4()`, `workflow.logger`, `workflow.sleep()`.
- The Python sandbox re-imports modules per workflow and blocks many non-deterministic calls. `workflow.unsafe.imports_passed_through()` is for importing your activity/model modules without that cost.
- Docs: [Python sandbox](https://docs.temporal.io/develop/python/best-practices/python-sdk-sandbox)

## Build

Add a branch to `GetFactsWorkflow`:

```python
if workflow.now().hour < 6:
    workflow.logger.info("Inside quiet hours, collecting extended facts")
    # call an extra activity, e.g. get_inventory
```

## Break it (the important part)

1. Change `workflow.now()` to `datetime.now()`. Start the workflow. What does the sandbox do?
2. Undo that. Start a workflow that sleeps 60 s (`await workflow.sleep(60)`) between two activities.
3. While it sleeps, stop the worker, **swap the order of the two activities**, start the worker.
4. Read the non-determinism error in the UI and worker log. This is exactly what an unsafe deploy looks like.
5. Terminate it: `temporal workflow terminate --workflow-id ...`.

## Done when

- [ ] You can list three things that must never happen in workflow code.
- [ ] You've seen a non-determinism error and know it is fixed by versioning (Day 19), not by retrying.
