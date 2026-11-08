"""Save a workflow's event history as JSON, for replay tests.

    uv run --env-file .env python -m netops_temporal.tools.export_history facts-bos-rtr-01 \\
        tests/histories/get_facts.json

The same JSON as `temporal workflow show --workflow-id <id> -o json`.
"""

import asyncio
import sys
from pathlib import Path

from temporalio.client import Client

from netops_temporal.client import connect


async def export_history(client: Client, workflow_id: str, path: Path) -> None:
    history = await client.get_workflow_handle(workflow_id).fetch_history()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(history.to_json())


async def main(workflow_id: str, path: str) -> None:
    await export_history(await connect(), workflow_id, Path(path))
    print(f"wrote {path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python -m netops_temporal.tools.export_history <workflow_id> <out.json>")
    asyncio.run(main(sys.argv[1], sys.argv[2]))
