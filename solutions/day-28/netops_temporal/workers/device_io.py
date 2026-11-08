"""Day 21: the device worker. Activities only, on the device-io task queue.

This is the worker that logs in to devices and Nautobot, so it's the one that holds credentials,
and the one to scale (more processes) or throttle. Every workflow sends its activities here.

    uv run --env-file .env python -m netops_temporal.workers.device_io
"""

import asyncio
import logging
import signal
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from temporalio.worker import Worker

from netops_temporal.client import connect
from netops_temporal.constants import DEVICE_IO_TASK_QUEUE
from netops_temporal.workers.main import ACTIVITIES, telemetry

SLOTS = 10


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await connect(**telemetry())
    with ThreadPoolExecutor(max_workers=SLOTS) as executor:
        worker = Worker(
            client,
            task_queue=DEVICE_IO_TASK_QUEUE,
            activities=ACTIVITIES,
            activity_executor=executor,
            # Per process: no more device sessions at once than threads to run them (Day 7).
            max_concurrent_activities=SLOTS,
            # Across ALL device-io workers: the server hands out at most 5 activities a second,
            # however many workers you start. Protects AAA and device CPUs from a burst.
            max_task_queue_activities_per_second=5.0,
            # On shutdown, stop taking new activities and give running ones 30 s to finish
            # (a show tech in progress, say) before they're cancelled.
            graceful_shutdown_timeout=timedelta(seconds=30),
        )
        # SIGTERM is what a container runtime (or systemd) sends to stop a process; Ctrl-C is
        # SIGINT. Either way: shut down gracefully instead of dying mid-session.
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.shutdown()))
        logging.info("Device-io worker polling %s", DEVICE_IO_TASK_QUEUE)
        try:
            await worker.run()
        finally:
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.remove_signal_handler(sig)
        logging.info("Device-io worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
