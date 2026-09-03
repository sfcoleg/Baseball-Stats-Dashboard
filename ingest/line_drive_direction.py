"""Pull/straight/oppo split for line drives specifically — Statcast's own
batted-ball leaderboard (see fetch_batted_ball_profile in refresh_data.py)
only crosses direction with ground vs. AIR, where "air" bundles fly balls,
line drives, and popups together. There is no line-drive-only cross
available from that endpoint at all; this computes one directly from raw
pitch-level Statcast data instead.

Spray angle from hc_x/hc_y, then bucketed into pull/straight/oppo relative
to batter handedness, using the same landing-coordinate calibration
app/db.py and ballparks.py already use (HC_X0/HC_Y0) and the empirical
0.75 correction factor publicly documented for converting Statcast's raw
hc_x/hc_y arctan into real-world spray-angle degrees.

Before this is trusted for line drives, validate() reclassifies EVERY
batted ball (not just line drives) and checks the resulting pull/straight/
oppo rates against Savant's own pull_rate/straight_rate/oppo_rate for the
same season (which are known-correct, being the site's existing working
values) — if this file's angle formula doesn't reproduce Savant's real
numbers for ordinary batted balls, it has no business being trusted for
line drives either. Run `python line_drive_direction.py` to fetch,
validate, and print a report; nothing is stored unless validation passes.
"""
import math
import sys
import time
import warnings
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from refresh_data import CURRENT_SEASON, DB_PATH, _store_season_table, fetch_batted_ball_profile
from ballparks import HC_X0, HC_Y0, SEASON_RANGES
from _dates import pacific_today

SPRAY_ANGLE_CORRECTION = 0.75  # see module docstring


def _spray_angle_deg(hc_x, hc_y):
    """Positive = hit toward the 1B/right-field side, negative = 3B/left-
    field side, in the umpire's-eye view Statcast's hc_x/hc_y use."""
    return (180 / 3.141592653589793) * pd.Series(
        [math.atan((x - HC_X0) / (HC_Y0 - y)) if pd.notna(x) and pd.notna(y) and y < HC_Y0 else float("nan")
         for x, y in zip(hc_x, hc_y)]
    ) * SPRAY_ANGLE_CORRECTION


def _classify(angle, stand):
    """pull/straight/oppo, handedness-adjusted. A right-handed batter
    pulls to left field (negative angle here); a lefty pulls to right
    field (positive angle) — flip the sign for lefties before bucketing
    so "pull" always means the same physical direction relative to the
    batter regardless of which side of the plate he hits from."""
    adj = angle.where(stand.eq("R"), -angle)
    return pd.cut(adj, bins=[-999, -15, 15, 999], labels=["pull", "straight", "oppo"])


def fetch_season_batted_balls(season=CURRENT_SEASON) -> pd.DataFrame:
    """Every batted ball (not just home runs, not just line drives) for
    `season`, in 2-week chunks like ballparks.py's download_season — one
    column set: batter, stand, hc_x, hc_y, bb_type."""
    from pybaseball import statcast

    start_s, end_s = SEASON_RANGES.get(season, (f"{season}-03-20", None))
    end_s = end_s or (pacific_today() - timedelta(days=1)).isoformat()
    start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)

    frames = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=13), end)
        print(f"  statcast {chunk_start} .. {chunk_end}", flush=True)
        raw = statcast(start_dt=chunk_start.isoformat(), end_dt=chunk_end.isoformat(), verbose=False)
        if raw is not None and not raw.empty and "bb_type" in raw.columns:
            keep = raw.loc[raw["bb_type"].notna(), ["batter", "stand", "hc_x", "hc_y", "bb_type"]]
            keep = keep.dropna(subset=["hc_x", "hc_y", "stand"])
            if not keep.empty:
                frames.append(keep)
        chunk_start = chunk_end + timedelta(days=1)
        time.sleep(1)

    if not frames:
        return pd.DataFrame(columns=["batter", "stand", "hc_x", "hc_y", "bb_type"])
    return pd.concat(frames, ignore_index=True)


def classify_all(bb: pd.DataFrame) -> pd.DataFrame:
    bb = bb.copy()
    bb["angle"] = _spray_angle_deg(bb["hc_x"].tolist(), bb["hc_y"].tolist()).values
    bb["dir"] = _classify(bb["angle"], bb["stand"])
    return bb


def validate(season=CURRENT_SEASON, bb: pd.DataFrame = None):
    """Reclassify EVERY batted ball this season (any bb_type) and compare
    the resulting per-batter pull/straight/oppo rates against Savant's own
    pull_rate/straight_rate/oppo_rate for the same season — those are
    known-good (they're the working values already on the site). Prints
    the mean absolute error in percentage points; anything under a few
    points means the angle formula/thresholds are trustworthy enough to
    also apply to the line-drive-only subset."""
    if bb is None:
        bb = fetch_season_batted_balls(season)
    classified = classify_all(bb)
    mine = (
        classified.groupby("batter")["dir"]
        .value_counts(normalize=True)
        .unstack(fill_value=0)
        .rename(columns={"pull": "my_pull", "straight": "my_straight", "oppo": "my_oppo"})
        * 100
    )
    savant = fetch_batted_ball_profile(season)
    if savant.empty:
        print("no Savant ground truth available for this season — cannot validate")
        return None
    cmp = mine.merge(savant.rename(columns={"mlbID": "batter"}), on="batter", how="inner")
    cmp = cmp[cmp[["gb_rate"]].notna().all(axis=1)]  # only batters Savant actually has rates for
    for mine_col, savant_col in [("my_pull", "pull_rate"), ("my_straight", "straight_rate"), ("my_oppo", "oppo_rate")]:
        err = (cmp[mine_col] - cmp[savant_col] * 100).abs()
        print(f"{mine_col} vs {savant_col}: mean abs error {err.mean():.2f} pts, "
              f"median {err.median():.2f} pts, max {err.max():.2f} pts, n={len(cmp)}")
    return cmp


def compute_ld_rates(classified: pd.DataFrame) -> pd.DataFrame:
    """Per-batter pull_ld_rate/straight_ld_rate/oppo_ld_rate — line drives
    only, as a fraction of ALL that batter's batted balls (same convention
    Savant's own pull_air_rate etc. use: the three splits sum to ld_rate,
    not to 1)."""
    total = classified.groupby("batter").size().rename("total")
    ld = classified[classified["bb_type"] == "line_drive"]
    counts = ld.groupby(["batter", "dir"], observed=True).size().unstack(fill_value=0)
    for col in ("pull", "straight", "oppo"):
        if col not in counts.columns:
            counts[col] = 0
    rates = counts[["pull", "straight", "oppo"]].div(total, axis=0)
    rates.columns = ["pull_ld_rate", "straight_ld_rate", "oppo_ld_rate"]
    return rates.reset_index().rename(columns={"batter": "mlbID"})


_LD_COLS = ["pull_ld_rate", "straight_ld_rate", "oppo_ld_rate"]


def store(season, ld_rates: pd.DataFrame) -> None:
    """Merge pull_ld_rate/straight_ld_rate/oppo_ld_rate into the existing
    batted_ball row for `season`. Must carry every existing column, not
    just the 3 new ones — _store_season_table's ALTER-not-DROP path only
    fires when the incoming frame is a pure superset of what's already
    there; a frame with just the 3 new columns would look like existing
    columns are being REMOVED and take the destructive drop path instead.

    Once ANY season has ever stored these 3 columns, the whole table's
    schema carries them — so `existing` here already has them too (NULL,
    if this particular season hasn't been through store() yet). Merging a
    second copy in from `ld_rates` collided on those names and pandas
    silently suffixed them to _x/_y instead of erroring cleanly, which
    _store_season_table then read as "the real column got renamed" and
    rebuilt the ENTIRE table around the malformed _x/_y names — wiping
    every other season. Caught only because the DB was re-verified before
    the next git push, not because anything raised loudly. Drop the
    existing NULL placeholders before merging so this can't recur: the
    freshly computed values are always what should win."""
    import sqlite3
    with sqlite3.connect(DB_PATH) as conn:
        existing = pd.read_sql("SELECT * FROM batted_ball WHERE season = ?", conn, params=(season,))
        existing = existing.drop(columns=[c for c in _LD_COLS if c in existing.columns])
        merged = existing.merge(ld_rates, on="mlbID", how="left")
        assert not any(c.endswith(("_x", "_y")) for c in merged.columns), \
            f"unexpected column collision after merge: {list(merged.columns)}"
        _store_season_table(conn, "batted_ball", merged, season)
        conn.commit()
        stored = conn.execute(
            "SELECT COUNT(*) FROM batted_ball WHERE season = ? AND pull_ld_rate IS NOT NULL", (season,)
        ).fetchone()[0]
    print(f"  stored pull_ld_rate/straight_ld_rate/oppo_ld_rate for {stored} batters, season {season} "
          f"(computed for {len(ld_rates)})", flush=True)


if __name__ == "__main__":
    season = int(sys.argv[1]) if len(sys.argv) > 1 else CURRENT_SEASON
    print(f"=== fetching {season} raw batted-ball events ===", flush=True)
    bb = fetch_season_batted_balls(season)
    print(f"total batted balls: {len(bb)}", flush=True)
    classified = classify_all(bb)
    print(f"=== validating spray-angle classification against Savant's known-good rates ===", flush=True)
    validate(season, bb=bb)
    print(f"=== computing line-drive-only pull/straight/oppo and storing ===", flush=True)
    ld_rates = compute_ld_rates(classified)
    store(season, ld_rates)
    print("DONE", flush=True)
