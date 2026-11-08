"""Seed the course Nautobot with the 4 lab devices and their intent.

Safe to run more than once: every object is looked up first and only created if missing.

    uv run --env-file .env python lab/nautobot/seed.py
"""

import os

DEVICE_CONTENT_TYPE = "dcim.device"

# name: (location, role, target_version). nyc-acc-01 is deliberately "behind" its intent,
# so later days have drift to find.
DEVICES = {
    "bos-rtr-01": ("BOS", "router", "4.32.0F"),
    "bos-acc-01": ("BOS", "access", "4.32.0F"),
    "nyc-rtr-01": ("NYC", "router", "4.32.0F"),
    "nyc-acc-01": ("NYC", "access", "4.33.1F"),
}


def _get_or_create(endpoint, counts: dict[str, int], kind: str, lookup: dict, **extra):
    record = endpoint.get(**lookup)
    if record is None:
        record = endpoint.create(**lookup, **extra)
        counts[kind] += 1
    return record


def seed(api) -> dict[str, int]:
    """Create everything the course needs. Returns how many objects of each kind were created."""
    counts = dict.fromkeys(
        ["location_types", "locations", "manufacturers", "device_types", "platforms",
         "roles", "custom_fields", "devices"],
        0,
    )
    active = api.extras.statuses.get(name="Active")

    site = _get_or_create(
        api.dcim.location_types, counts, "location_types", {"name": "Site"},
        content_types=[DEVICE_CONTENT_TYPE],
    )
    locations = {
        name: _get_or_create(
            api.dcim.locations, counts, "locations", {"name": name},
            location_type=site.id, status=active.id,
        )
        for name in ("BOS", "NYC")
    }
    arista = _get_or_create(api.dcim.manufacturers, counts, "manufacturers", {"name": "Arista"})
    ceos = _get_or_create(
        api.dcim.device_types, counts, "device_types", {"model": "cEOSLab"},
        manufacturer=arista.id,
    )
    eos = _get_or_create(
        api.dcim.platforms, counts, "platforms", {"name": "eos"},
        network_driver="arista_eos", manufacturer=arista.id,
    )
    roles = {
        name: _get_or_create(
            api.extras.roles, counts, "roles", {"name": name}, content_types=[DEVICE_CONTENT_TYPE]
        )
        for name in ("router", "access")
    }
    # Nautobot can't filter custom fields by key, so look it up by label.
    _get_or_create(
        api.extras.custom_fields, counts, "custom_fields", {"label": "Target version"},
        key="target_version", type="text", content_types=[DEVICE_CONTENT_TYPE],
    )

    for name, (location, role, target_version) in DEVICES.items():
        _get_or_create(
            api.dcim.devices, counts, "devices", {"name": name},
            location=locations[location].id,
            role=roles[role].id,
            device_type=ceos.id,
            platform=eos.id,
            status=active.id,
            custom_fields={"target_version": target_version},
        )
    return counts


def main() -> None:
    import pynautobot

    url = os.environ.get("NAUTOBOT_URL", "http://localhost:8080")
    api = pynautobot.api(url, token=os.environ["NAUTOBOT_TOKEN"])
    counts = seed(api)
    created = {kind: n for kind, n in counts.items() if n}
    print(f"Seeded {url}: " + (", ".join(f"{n} {k}" for k, n in created.items()) or "nothing new"))


if __name__ == "__main__":
    main()
