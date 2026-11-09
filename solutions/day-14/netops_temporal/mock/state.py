"""Config pushed to mock devices (Day 14 onward), kept in OUTPUT_DIR/mock-state.json.

A file, not a dict in memory, so the mock lab remembers a push across worker restarts, just
like a real device would. Each push is kept separately so `rollback` can undo the last one.
"""

import json
import os
from pathlib import Path


def _path() -> Path:
    # Read OUTPUT_DIR on every call (not at import), so tests can point it somewhere else.
    return Path(os.environ.get("OUTPUT_DIR") or "output") / "mock-state.json"


def _load() -> dict[str, list[list[str]]]:
    path = _path()
    return json.loads(path.read_text()) if path.exists() else {}


def _save(data: dict[str, list[list[str]]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def applied_lines(device: str) -> list[str]:
    return [line for push in _load().get(device, []) for line in push]


def apply_lines(device: str, lines: list[str]) -> None:
    data = _load()
    data.setdefault(device, []).append(list(lines))
    _save(data)


def rollback(device: str) -> None:
    data = _load()
    if data.get(device):
        data[device].pop()
    _save(data)


def reset() -> None:
    _save({})
