"""One definition of "what day is it" for every ingest script.

These jobs run on GitHub Actions, whose clock is UTC. UTC is far enough
ahead of Pacific that a plain `date.today()` rolls over to the next calendar
day while it is still afternoon or evening on the west coast — so a run
landing after ~5pm Pacific computes "yesterday" as a day whose games have
not finished, fetches an empty or partial day, and (worse) records that day
as done, so nothing ever retries it.

That is not hypothetical: it is exactly what left Play of the Day and the
recent-form headliners stale on 2026-08-30. The fix went into the MLB path
first and the other scripts kept their own `date.today()` calls, which is
the drift this module exists to stop — every ingest script imports the same
function, so there is nowhere for a second, wrong answer to live.

Mirrors app/db.py's today_pacific() on the app side. Pacific is also this
app's natural notion of a sports day: the nightly cron is scheduled in
Pacific-morning terms, and a game day only ends once the west-coast games do.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def pacific_today() -> date:
    """Today's date in Pacific time — the ingest side's single source of
    truth for the current day. Use this instead of `date.today()`."""
    return datetime.now(PACIFIC).date()
