# Using GitHub Codespaces

**Short answer: useful as a second lab, not a replacement for your Mac.**

The `.devcontainer/` in this repo gives you a Codespace with Python, `uv`, the Temporal
CLI, and a Temporal dev server that starts automatically (UI forwarded on port 8233,
namespaces `default` and `compliance` already created).

## Where it helps

- Studying away from your Mac — any day marked ☁️ in the main README.
- Pure-Temporal topics where devices don't matter: determinism, testing, signals,
  queries, updates, timers, Continue-As-New, child workflows, schedules, versioning, Nexus.
- AI week, with an API key stored as a Codespaces secret (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`).
- Trying a pipeline change in CI-like Linux before pushing.

## Where it doesn't

- **Your cEOS lab and Nautobot live on your Mac.** A Codespace can't reach them.
  Use the mock device activities (`DEVICE_MODE=mock` in `.env`) instead.
- **cEOS images can't be pulled from a public registry** (Arista requires an account).
  You *could* push `ceos:4.32.0F` to a private GHCR repo and run containerlab in a
  4-core / 16 GB Codespace, but it costs core-hours and isn't worth it for this course.
- Codespaces stop after inactivity; the dev server's SQLite file lives in the workspace
  (`.temporal/temporal.db`), so state survives a stop/start but not a rebuild.

## Start one

1. Push this repo to GitHub.
2. **Code → Codespaces → Create codespace on main**.
3. Wait for `post-create.sh` to finish, then open the **Ports** tab and click port 8233.
4. `uv run python -m netops_temporal.workers.main` in one terminal, the starter in another.

## The mock-device pattern

From Day 2, write each device activity against a small interface and pick the
implementation from `DEVICE_MODE`:

```python
# activities/devices.py
if settings.device_mode == "mock":
    from .eapi_mock import run_commands
else:
    from .eapi import run_commands
```

The mock returns canned `show version` / `show running-config` output from
`tests/fixtures/`. It is also what your unit tests use, so it is not wasted work.
