# Using GitHub Codespaces

**Short answer: a handy second lab for the Temporal-only parts, in mock mode.**

The `.devcontainer/` in this repo gives you a Codespace with Python, `uv`, the Temporal CLI, and
a Temporal dev server that starts automatically (UI forwarded on port 8233, namespaces `default`
and `compliance` already created). It sets `LAB_MODE=mock`, so every device and Nautobot call
replays outputs recorded from the course lab.

## Where it helps

- Studying away from your lab. Every day runs in mock mode, and Days 1, 4 and 6 don't need
  devices at all.
- Pure-Temporal topics where devices don't matter: determinism, testing, signals, queries,
  updates, timers, Continue-As-New, child workflows, schedules, versioning, Nexus.
- Practising failures with the mock switches (`MOCK_UNREACHABLE`, `MOCK_AUTH_FAIL`,
  `MOCK_CLI_DELAY`; see [lab setup → Mock mode](lab-setup.md#mock-mode)).
- Running the solution tests in a clean Linux box: `scripts/test-solutions.sh`.

## Where it doesn't

- **Your cEOS lab and Nautobot run locally.** A Codespace can't reach them, which is why it uses
  mock mode.
- **cEOS images can't be pulled from a public registry** (Arista requires an account), so running
  containerlab in a Codespace isn't worth it for this course.
- Codespaces stop after inactivity. The dev server's database lives in the workspace
  (`.temporal/temporal.db`), so state survives a stop/start but not a rebuild.

## Start one

1. Push this repo to GitHub.
2. **Code → Codespaces → Create codespace on main**.
3. Wait for `post-create.sh` to finish, then open the **Ports** tab and click port 8233.
4. `uv run --env-file .env python -m netops_temporal.workers.main` in one terminal, a starter in
   another.
