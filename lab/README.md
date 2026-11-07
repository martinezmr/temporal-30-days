# Lab

| File | Purpose |
| --- | --- |
| `start-temporal.sh` | Temporal dev server + UI in Podman (or Docker), persistent, with `default` and `compliance` namespaces |
| `ceos-clab.clab.yml` + `startup-configs/` | Your 4-node Arista cEOS topology (copied from `temporal-network-automation`) |

## Bring-up order

1. `./lab/start-temporal.sh` on your Mac → http://localhost:8233
2. In the OrbStack Ubuntu VM: `sudo containerlab deploy -t lab/ceos-clab.clab.yml`
3. Start your Nautobot pod.
4. Confirm eAPI from wherever your worker runs (see `docs/lab-setup.md`, step 4).

## Tear-down

```bash
sudo containerlab destroy -t lab/ceos-clab.clab.yml
podman stop temporal-dev   # data survives in the temporal-data volume
```

To wipe Temporal state completely: `podman rm -f temporal-dev && podman volume rm temporal-data`.
