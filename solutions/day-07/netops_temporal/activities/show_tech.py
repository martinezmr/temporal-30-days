"""Day 5: a long-running activity that reports progress with heartbeats."""

from temporalio import activity
from temporalio.exceptions import ApplicationError, CancelledError

from netops_temporal.constants import OUTPUT_DIR, SHOW_TECH_COMMANDS
from netops_temporal.devices.errors import DeviceAuthError, UnknownDeviceError
from netops_temporal.devices.ssh import cli_session
from netops_temporal.models import ShowTechRequest, ShowTechResult


@activity.defn
def collect_show_tech(req: ShowTechRequest) -> ShowTechResult:
    # If an earlier attempt died part-way, its last heartbeat says how many commands it finished.
    details = activity.info().heartbeat_details
    start = details[0] if details else 0
    if start:
        activity.logger.info("Resuming %s show tech at command %d", req.device, start + 1)

    out_dir = OUTPUT_DIR / "show-tech" / req.device
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with cli_session(req.device) as send:
            for number, command in enumerate(SHOW_TECH_COMMANDS[start:], start=start + 1):
                (out_dir / f"{number:02d}.txt").write_text(send(command))
                # "I'm alive, and I've finished `number` commands." The server's reply to a
                # heartbeat is also how a cancel request arrives; the SDK then raises
                # CancelledError in this thread, wherever it happens to be.
                activity.heartbeat(number)
    except CancelledError:
        activity.logger.warning("%s show tech cancelled; partial output in %s", req.device, out_dir)
        raise
    except DeviceAuthError as err:
        raise ApplicationError(
            f"auth failed for {req.device}", type="AuthError", non_retryable=True
        ) from err
    except UnknownDeviceError as err:
        raise ApplicationError(str(err), type="UnknownDevice", non_retryable=True) from err

    return ShowTechResult(
        device=req.device,
        output_dir=str(out_dir),
        commands_collected=len(SHOW_TECH_COMMANDS),
        resumed_from=start,
    )
