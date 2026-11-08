"""Day 11: maintenance-window arithmetic, as a pure function so workflows and tests can share it."""

from datetime import datetime, timedelta

from netops_temporal.models import MaintenanceWindow


def next_window_start(now: datetime, window: MaintenanceWindow) -> datetime:
    """When the change may run: `now` if a window is open, else the next window's start.

    Pure: the same inputs always give the same answer. That's what makes it safe to call
    inside a workflow (with workflow.now(), never datetime.now()).
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware (use workflow.now())")
    today_start = now.replace(hour=window.start_hour_utc, minute=0, second=0, microsecond=0)
    length = timedelta(hours=window.duration_hours)
    # Yesterday's window can still be open after midnight (e.g. 22:00-02:00).
    for start in (today_start - timedelta(days=1), today_start):
        if start <= now < start + length:
            return now
    return today_start if now < today_start else today_start + timedelta(days=1)
