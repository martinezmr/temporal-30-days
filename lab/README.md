# Lab

Full walkthrough: [docs/lab-setup.md](../docs/lab-setup.md).

| File | Purpose |
| --- | --- |
| `start-temporal.sh` | Temporal dev server + UI in Podman (or Docker), persistent, with `default` and `compliance` namespaces |
| `ceos-clab.clab.yml` + `startup-configs/` | 4-node Arista cEOS topology with static management IPs; eAPI (HTTPS) and SSH as `admin`/`admin` |
| `tunnels.sh` | SSH port forwards through a jump host when the cEOS management IPs aren't reachable from your laptop |
| `nautobot/compose.yml`, `nautobot/start.sh` | Nautobot + PostgreSQL + Redis on http://localhost:8080 |
| `nautobot/seed.py` | Creates the sites, roles and 4 devices with their `target_version` intent (safe to re-run) |
| `deploy.sh` | Day 30: make a worker build current, or ramp to it, in both namespaces |

## Bring-up order

1. `./lab/start-temporal.sh` → http://localhost:8233
2. On your Linux host/VM: `sudo containerlab deploy -t lab/ceos-clab.clab.yml`
3. Behind a jump host? `JUMP_HOST=<host> lab/tunnels.sh` and paste its `DEVICE_HOSTS` line into `.env`
4. `lab/nautobot/start.sh`, then `uv run --env-file .env python lab/nautobot/seed.py`
5. `uv run --env-file .env python -m netops_temporal.tools.check_lab`

## Tear-down

```bash
sudo containerlab destroy -t lab/ceos-clab.clab.yml
podman compose -f lab/nautobot/compose.yml down   # add -v to wipe Nautobot data
podman stop temporal-dev                          # data survives in the temporal-data volume
```

To wipe Temporal state completely: `podman rm -f temporal-dev && podman volume rm temporal-data`.
