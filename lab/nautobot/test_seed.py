"""Tests for seed.py against an in-memory stand-in for the pynautobot API."""

import importlib.util
import itertools
from pathlib import Path
from types import SimpleNamespace

_spec = importlib.util.spec_from_file_location("seed", Path(__file__).with_name("seed.py"))
seed_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_module)

_ids = itertools.count(1)


class FakeEndpoint:
    def __init__(self, preload=(), unfilterable=()):
        self.records = [SimpleNamespace(id=next(_ids), **r) for r in preload]
        self.created = 0
        self.unfilterable = set(unfilterable)

    def get(self, **filters):
        bad = self.unfilterable & filters.keys()
        assert not bad, f"Nautobot rejects filter(s) {bad}: Unknown filter field"
        matches = [
            r for r in self.records if all(getattr(r, k, None) == v for k, v in filters.items())
        ]
        assert len(matches) <= 1, f"ambiguous get({filters})"
        return matches[0] if matches else None

    def create(self, **fields):
        record = SimpleNamespace(id=next(_ids), **fields)
        self.records.append(record)
        self.created += 1
        return record


def fake_api():
    return SimpleNamespace(
        dcim=SimpleNamespace(
            location_types=FakeEndpoint(),
            locations=FakeEndpoint(),
            manufacturers=FakeEndpoint(),
            device_types=FakeEndpoint(),
            platforms=FakeEndpoint(),
            devices=FakeEndpoint(),
        ),
        extras=SimpleNamespace(
            roles=FakeEndpoint(),
            statuses=FakeEndpoint(preload=[{"name": "Active"}]),
            custom_fields=FakeEndpoint(unfilterable={"key"}),  # as in Nautobot 3.2
        ),
    )


def test_seed_creates_four_devices_with_target_version():
    api = fake_api()
    seed_module.seed(api)

    devices = {d.name: d for d in api.dcim.devices.records}
    assert sorted(devices) == ["bos-acc-01", "bos-rtr-01", "nyc-acc-01", "nyc-rtr-01"]

    locations = {loc.id: loc.name for loc in api.dcim.locations.records}
    roles = {r.id: r.name for r in api.extras.roles.records}
    assert locations[devices["bos-rtr-01"].location] == "BOS"
    assert locations[devices["nyc-acc-01"].location] == "NYC"
    assert roles[devices["bos-rtr-01"].role] == "router"
    assert roles[devices["bos-acc-01"].role] == "access"

    versions = {name: d.custom_fields["target_version"] for name, d in devices.items()}
    assert versions == {
        "bos-rtr-01": "4.32.0F",
        "bos-acc-01": "4.32.0F",
        "nyc-rtr-01": "4.32.0F",
        "nyc-acc-01": "4.33.1F",
    }
    [field] = api.extras.custom_fields.records
    assert field.key == "target_version"


def test_seed_is_idempotent():
    api = fake_api()
    first = seed_module.seed(api)
    second = seed_module.seed(api)

    assert first["devices"] == 4
    assert all(count == 0 for count in second.values())
    assert len(api.dcim.devices.records) == 4
