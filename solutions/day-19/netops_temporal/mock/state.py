"""Config pushed to mock devices (Day 14 onward), kept in OUTPUT_DIR/mock-state.json.

A file, not a dict in memory, so the mock lab remembers a push across worker restarts, just
like a real device would. Each push is kept separately so `rollback` can undo the last one.

Day 17: activities run in a thread pool, so two remediations can push at the same moment. Every
read-change-write holds a lock, and the file is replaced in one step, never half-written.
"""

import json
import os
import threading
from pathlib import Path

_lock = threading.RLock()


def _path() -> Path:
    # Read OUTPUT_DIR on every call (not at import), so tests can point it somewhere else.
    return Path(os.environ.get("OUTPUT_DIR") or "output") / "mock-state.json"


def _load() -> dict[str, list[list[str]]]:
    path = _path()
    with _lock:
        return json.loads(path.read_text()) if path.exists() else {}


def _save(data: dict[str, list[list[str]]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)  # atomic: a reader sees the old file or the new one, never half of one


def applied_lines(device: str) -> list[str]:
    return [line for push in _load().get(device, []) for line in push]


def apply_lines(device: str, lines: list[str]) -> None:
    with _lock:
        data = _load()
        data.setdefault(device, []).append(list(lines))
        _save(data)


def rollback(device: str) -> None:
    with _lock:
        data = _load()
        if data.get(device):
            data[device].pop()
        _save(data)


def reset() -> None:
    with _lock:
        _save({})
