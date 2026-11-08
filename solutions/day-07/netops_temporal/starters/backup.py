"""Back up devices and print a report.

    uv run --env-file .env python -m netops_temporal.starters.backup              # all devices
    uv run --env-file .env python -m netops_temporal.starters.backup bos-rtr-01   # just one
"""

import asyncio
import sys

from netops_temporal.client import connect
from netops_temporal.constants import ORCHESTRATION_TASK_QUEUE
from netops_temporal.models import BackupRequest
from netops_temporal.workflows.backup import ConfigBackupWorkflow


async def main(devices: list[str]) -> None:
    client = await connect()
    request = BackupRequest(devices=devices) if devices else BackupRequest()
    report = await client.execute_workflow(
        ConfigBackupWorkflow.run,
        request,
        id="config-backup",
        task_queue=ORCHESTRATION_TASK_QUEUE,
    )
    print(f"Backup started {report.started_at:%Y-%m-%d %H:%M:%S} UTC: "
          f"{len(report.succeeded)} ok, {len(report.failed)} failed")
    for r in report.results:
        target = r.intent.target_version if r.intent else "-"
        detail = r.backup_path if r.ok else r.error
        print(f"  {'OK  ' if r.ok else 'FAIL'}  {r.device:<11} target {target:<8} {detail}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
