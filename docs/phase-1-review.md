# Phase 1 review notes

Phase 1 rebuilt the shared pieces and Week 1 (Days 1–7). Days 8–30 are still the old outlines.
Before Phase 2 starts, please judge the things listed under **What to judge**.

## What changed

| Area | Before | Now |
| --- | --- | --- |
| Lessons, Days 1–7 | ~50-line outlines; snippets used undefined helpers | Full lessons: Why → Concept → Walkthrough → Run it → Break it → Check yourself (with answers) |
| Solutions | None | `solutions/day-01` … `day-07`, each complete and runnable, 22–49 tests each |
| Lesson ↔ code | Could drift | `scripts/check_lessons.py` fails CI if any `# file:` snippet isn't in that day's solution |
| Device libraries | niquests (Day 2), surprise pyeapi (Day 5) | pyeapi (Day 2) → Netmiko (Day 5) → NAPALM + pynautobot (Day 7), each introduced on purpose |
| `DEVICE_HOSTS` | One string nobody parsed | Parsed in `constants.py`; supports `name=host[:eapi_port[:ssh_port]]` for jump-host tunnels |
| Lab | cEOS on Docker's default bridge (dynamic IPs), Nautobot assumed | Static mgmt IPs; eAPI + SSH as admin/admin; `lab/tunnels.sh` for jump hosts; containerized Nautobot 3.2.8 + idempotent seed |
| No-lab mode | Mentioned, not built | `LAB_MODE=mock` with real captured outputs and failure switches (`MOCK_UNREACHABLE`, `MOCK_AUTH_FAIL`, `MOCK_CLI_DELAY`) |
| Lab check | — | `python -m netops_temporal.tools.check_lab` |
| OCP | Days 21 and 30 targeted OpenShift | Course is local-only; those two outlines carry a "not yet rewritten" note |

## Verified against your real lab

Everything below ran against your 4 cEOS nodes through `lab/tunnels.sh` (jump host `containerlab`)
and a fresh course Nautobot:

- `check_lab`: all green (Temporal, eAPI + SSH on all 4 devices, Nautobot).
- Day 2: facts from all 4 devices.
- Day 3: wrong password → `AuthError` after exactly 1 attempt.
- Day 5: Netmiko show tech; kill-the-worker resume; cancellation.
- Day 6: the replay test histories are exports of those live runs.
- Day 7: parallel backup with Nautobot intent; one device unreachable → partial report; wrong
  password → 1 attempt.
- Nautobot seed run twice (second run created nothing).

Live runs found and fixed three real issues: Nautobot 3.2 can't filter custom fields by `key`;
`show logging last 50` isn't valid EOS (now `show logging 50`); and NAPALM's EOS driver connects
lazily, so bad passwords were being retried.

## Not verified live

- The **new cEOS startup configs and static-IP topology**. Your running lab wasn't redeployed.
  It still uses the old `172.17.0.x` IPs, which `lab/tunnels.sh` accepts via `DEVICE_IPS`. To
  adopt the new topology: `sudo containerlab deploy -t lab/ceos-clab.clab.yml --reconfigure` on
  the VM, then re-run `check_lab`.
- `lab/start-temporal.sh` and `lab/nautobot/start.sh` with **Docker** (only Podman was used).
- GitHub Actions CI (the same steps pass locally).

## What to judge

1. **Depth and tone.** Read Day 2 and Day 5 end to end. Is the Concept section the right length?
   Too much hand-holding, or not enough?
2. **Solution layout.** Is `solutions/day-NN/` (full snapshot per day) + `scripts/solution.sh` easy
   to use? Would your teammates rather have git tags or branches per day?
3. **Mock mode.** Do the switches cover the failures you want people to practise?
4. **Lab bring-up.** Follow [docs/lab-setup.md](lab-setup.md) as a teammate would. Anything
   missing for your team's laptops?
5. **Break it sections.** Are these the failures your team actually worries about?
