# Lab setup

Do this once, before Day 1. It takes about 30–45 minutes, most of it waiting for images
to download.

The whole course runs on your laptop:

| Piece | What it's for | Needed from | How |
| --- | --- | --- | --- |
| Temporal dev server + UI | Runs your workflows. UI on `localhost:8233`, gRPC on `localhost:7233` | Day 1 | [`lab/start-temporal.sh`](../lab/start-temporal.sh) |
| 4 × Arista cEOS in containerlab | The **state** side: real devices to talk to | Day 2 (optional until Day 7) | [`lab/ceos-clab.clab.yml`](../lab/ceos-clab.clab.yml) |
| Nautobot | The **intent** side: what the network *should* look like | Day 7 | [`lab/nautobot/`](../lab/nautobot/) |
| Python 3.13 + `uv` | Your workers and starters | Day 1 | `uv sync` |

No lab yet? Every day works in **mock mode** (`LAB_MODE=mock`), which replays real device
output from files. See [Mock mode](#mock-mode) at the bottom.

## 0. Prerequisites

- [`uv`](https://docs.astral.sh/uv/) (it installs Python 3.13 for you)
- Podman (with `podman compose`) or Docker (with `docker compose`)
- The [Temporal CLI](https://docs.temporal.io/cli) (`brew install temporal`). Optional, but the lessons use it.
- For cEOS: a Linux host or VM with [containerlab](https://containerlab.dev) and the
  `ceos:4.32.0F` image imported (`docker import cEOS64-lab-4.32.0F.tar.xz ceos:4.32.0F`)

## 1. Python project

```bash
uv sync
cp .env.example .env
```

## 2. Temporal

```bash
./lab/start-temporal.sh            # or: ENGINE=docker ./lab/start-temporal.sh
open http://localhost:8233
```

The script runs the Temporal dev server in a container with `--db-filename`, so workflows
survive a container restart. Without it, every restart would wipe the long-running
workflows you build in Week 2. It also creates a second namespace, `compliance`, for the
Nexus days.

## 3. cEOS lab

On your Linux host or VM, from a copy of this repo:

```bash
sudo containerlab deploy -t lab/ceos-clab.clab.yml
```

Each node gets a fixed management IP on the `clab-mgmt` network, and the startup configs
enable eAPI over HTTPS and SSH with `admin` / `admin`:

| Device | Mgmt IP | Role | Site |
| --- | --- | --- | --- |
| bos-rtr-01 | 172.20.20.2 | router | BOS |
| bos-acc-01 | 172.20.20.3 | access | BOS |
| nyc-rtr-01 | 172.20.20.4 | router | NYC |
| nyc-acc-01 | 172.20.20.5 | access | NYC |

These IPs are already the default `DEVICE_HOSTS` in `.env.example`. If your worker can reach
them, you're done. On a Mac it usually can't, so read the next section.

Already running the lab from an older copy of the topology (on Docker's default `bridge`
network, with `172.17.0.x` IPs)? Either redeploy with this file
(`sudo containerlab deploy -t lab/ceos-clab.clab.yml --reconfigure`), or keep it and put the
current IPs in `DEVICE_HOSTS`. Find them with `docker inspect -f '{{.NetworkSettings.IPAddress}}' bos-rtr-01`.

## macOS networking

containerlab runs inside a Linux VM, so the management IPs are usually **not reachable from
macOS**. You can SSH to a jump host (often the VM itself) but can't ping the devices.
Check from the machine where your worker will run:

```bash
curl -sk -u admin:admin https://172.20.20.2/command-api \
  -d '{"jsonrpc":"2.0","method":"runCmds","params":{"version":1,"cmds":["show version"]},"id":1}'
```

If that hangs, pick one of these:

**A. SSH tunnels through your jump host (recommended).** No changes on the VM.

```bash
JUMP_HOST=containerlab lab/tunnels.sh     # any ssh target: alias, user@host, ...
```

It forwards each device's eAPI (443) and SSH (22) to local ports and prints a line like:

```
DEVICE_HOSTS=bos-rtr-01=127.0.0.1:8441:2201,bos-acc-01=127.0.0.1:8442:2202,...
```

Paste that into `.env` and keep the tunnel terminal open while you work. If your devices
still use the old `172.17.0.x` IPs, pass them in:
`DEVICE_IPS="bos-rtr-01=172.17.0.3,bos-acc-01=172.17.0.5,nyc-rtr-01=172.17.0.4,nyc-acc-01=172.17.0.2" JUMP_HOST=containerlab lab/tunnels.sh`.

**B. Route the lab subnet over SSH with [sshuttle](https://github.com/sshuttle/sshuttle).**
`brew install sshuttle`, then `sshuttle -r containerlab 172.20.20.0/24`. Needs `sudo` on your
Mac. Keep the default `DEVICE_HOSTS`.

**C. Run the worker on the VM.** Clone the repo there, run `uv sync`, and run the worker
there. Starters can still run on your Mac.

## 4. Nautobot

```bash
lab/nautobot/start.sh              # or: ENGINE=docker lab/nautobot/start.sh
uv run --env-file .env python lab/nautobot/seed.py
```

`start.sh` runs Nautobot, PostgreSQL and Redis with compose and waits until Nautobot is
healthy. The first start runs database migrations and takes a few minutes. UI:
http://localhost:8080 (`admin` / `admin`). The API token is preset, so `.env.example`
already has it.

`seed.py` creates two sites (`BOS`, `NYC`), the `router` and `access` roles, and the four
devices, each with a `target_version` custom field: the EOS version it *should* run.
`nyc-acc-01` is deliberately set to a newer version than it runs, so later days have drift
to find. Running it again changes nothing.

## 5. Check everything

```bash
uv run --env-file .env python -m netops_temporal.tools.check_lab
```

It checks Temporal, eAPI and SSH on every device, and the Nautobot API, and tells you which
one failed. A failed device check links back to [macOS networking](#macos-networking).

## Mock mode

Set `LAB_MODE=mock` in `.env` (or prefix a command: `LAB_MODE=mock uv run ...`). Device
and Nautobot calls then return real outputs captured from this lab, stored in
`src/netops_temporal/fixtures/`. Temporal itself is always real: you still run the dev server.

To practise failures without breaking anything, mock mode has switches:

| Variable | Effect |
| --- | --- |
| `MOCK_UNREACHABLE=bos-rtr-01,nyc-rtr-01` | Those devices act as if they're down |
| `MOCK_AUTH_FAIL=1` | Every device rejects the login |
| `MOCK_CLI_DELAY=3` | Each CLI command takes 3 seconds (Day 5) |

Workers read these when an activity runs, so change `.env` and restart the worker.

## Tear down

```bash
sudo containerlab destroy -t lab/ceos-clab.clab.yml               # on the VM
podman compose -f lab/nautobot/compose.yml down                    # keeps Nautobot data
podman stop temporal-dev                                           # keeps workflow history
```

Wipe everything: add `-v` to the compose `down`, and run
`podman rm -f temporal-dev && podman volume rm temporal-data`.
