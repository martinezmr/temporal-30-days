# Lab setup

You already have almost everything. Keep running the Temporal dev server in a container,
give it a database file so long-running workflows survive restarts, and add a second
namespace for Nexus. Nothing else is needed until Day 20.

## What runs where

| Container / service | Needed from | Why | How |
| --- | --- | --- | --- |
| Temporal dev server + UI | Day 1 | Server, UI on `8233`, gRPC on `7233` | [`lab/start-temporal.sh`](../lab/start-temporal.sh) |
| containerlab, 4 × cEOS | Day 2 | The **state** side | [`lab/ceos-clab.clab.yml`](../lab/ceos-clab.clab.yml) in your OrbStack Ubuntu VM |
| Nautobot | Day 7 | The **intent** side | Your existing Nautobot pod (NetBox works too — pick one) |
| Prometheus + Grafana | Day 20 (optional) | Metrics | Two containers |
| LLM access | Day 25 | AI week | API key in `.env`, or a local Ollama container |
| OpenShift Local (CRC) or kind | Day 30 (optional) | Rehearse OCP | CRC wants ~4 cores and 10+ GB free RAM — tight on a MacBook Air |

## 1. Temporal dev server with persistence

```bash
./lab/start-temporal.sh
open http://localhost:8233
```

Without `--db-filename` the dev server is in-memory and every restart wipes your
week-long entity workflow, which defeats Week 2.

## 2. Python project

```bash
uv sync                 # installs temporalio, pydantic, niquests, pytest
cp .env.example .env    # fill in device and Nautobot credentials
uv run python -m netops_temporal.workers.main    # terminal 1
uv run python -m netops_temporal.starters.hello  # terminal 2
```

You should see `Hello, Temporal!` and a completed workflow in the UI.

## 3. Devices: enable eAPI

Each cEOS node needs:

```
management api http-commands
   no shutdown
username admin privilege 15 secret admin
```

## 4. The macOS networking gotcha

containerlab runs in your OrbStack Ubuntu VM, so the cEOS management IPs may not be
reachable from a worker running directly on macOS. Test on Day 2:

```bash
curl -sk -u admin:admin https://<mgmt-ip>/command-api \
  -d '{"jsonrpc":"2.0","method":"runCmds","params":{"version":1,"cmds":["show version"]},"id":1}'
```

If it fails, pick one:

- Run the worker inside the OrbStack VM (simplest).
- Run the worker as a container on the `clab` network (also rehearses Day 21).
- Use your existing jump host / port forwards and point `DEVICE_HOSTS` in `.env` at them.

## 5. Nautobot

Use your existing pod. Create the four devices (`bos-rtr-01`, `bos-acc-01`,
`nyc-rtr-01`, `nyc-acc-01`), a site per city, and a role per type. Days 7 and 14
read intent from config contexts or Golden Config.
