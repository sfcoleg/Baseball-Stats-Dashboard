"""Ballparks ingest — every home run's landing data plus per-game final
scores by park, for the Ballparks tab (3D HR museum + our own park factors).

Two tables in stats.db, both small enough for the repo database:
  - hr_log: one row per HR (landing x/y in spray-chart feet, launch speed/
    angle, distance, batter, park = home team, which half-inning so the
    page can color home vs visiting homers). ~5-6k rows per season.
  - park_games: one row per game (park + final scores), the denominator
    for park factors.

Raw Savant pulls cache per ~2-week chunk in ingest/park_cache/ (gitignored,
resumable — same pattern as train_wp_model.py). Backfill:

    python ingest/ballparks.py 2021 2026

update_day(day) is the cheap nightly increment for the refresh job.
"""
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "stats.db"
CACHE_DIR = Path(__file__).resolve().parent / "park_cache"

# Same Savant landing-coordinate calibration app/db.py uses for spray charts.
HC_X0, HC_Y0, HC_SCALE = 125.42, 198.27, 2.495

RAW_COLS = [
    "game_pk", "game_date", "events", "inning_topbot", "hc_x", "hc_y",
    "launch_speed", "launch_angle", "hit_distance_sc", "batter", "des",
    "home_team", "away_team", "post_home_score", "post_away_score",
    # The pitch that was actually put in play — for Play of the Day's strike
    # zone plot (type/speed/location), not used by the park-factor side of
    # this module at all.
    "pitch_type", "release_speed", "plate_x", "plate_z", "sz_top", "sz_bot",
]

# hr_log columns added after the table already existed in production —
# ADD COLUMN (not DROP+recreate) so historical rows are kept, just NULL for
# these until they're re-backfilled. Matches the ALTER-not-DROP fix from the
# batter dWAR incident: a schema-mismatch DROP here would erase every HR
# logged before this column existed.
_HR_LOG_PITCH_COLS = ["pitch_type", "release_speed", "plate_x", "plate_z", "sz_top", "sz_bot"]


def _ensure_hr_log_pitch_columns(conn: sqlite3.Connection) -> None:
    try:
        existing = {r[1] for r in conn.execute("PRAGMA table_info(hr_log)")}
    except sqlite3.OperationalError:
        return  # table doesn't exist yet — to_sql will create it with every column
    if not existing:
        return
    for col in _HR_LOG_PITCH_COLS:
        if col not in existing:
            conn.execute(f"ALTER TABLE hr_log ADD COLUMN {col} REAL" if col != "pitch_type"
                         else "ALTER TABLE hr_log ADD COLUMN pitch_type TEXT")
    conn.commit()

SEASON_RANGES = {
    2021: ("2021-04-01", "2021-10-03"),
    2022: ("2022-04-07", "2022-10-05"),
    2023: ("2023-03-30", "2023-10-01"),
    2024: ("2024-03-20", "2024-09-30"),
    2025: ("2025-03-18", "2025-09-28"),
    2026: ("2026-03-25", None),
}


def _with_retries(fn, label, attempts=3):
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                raise
            wait = 15 * (i + 1)
            print(f"  {label} failed ({e!r}), retrying in {wait}s...", flush=True)
            time.sleep(wait)


def download_season(season: int) -> None:
    from pybaseball import statcast

    CACHE_DIR.mkdir(exist_ok=True)
    start_s, end_s = SEASON_RANGES[season]
    # Pacific, not UTC date.today() — see refresh_data.py's _pacific_today().
    from datetime import datetime as _dt
    end_s = end_s or (_dt.now(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=1)).isoformat()
    start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)

    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=13), end)
        out = CACHE_DIR / f"park_{season}_{chunk_start.isoformat()}.csv"
        if out.exists():
            chunk_start = chunk_end + timedelta(days=1)
            continue
        label = f"statcast {chunk_start} → {chunk_end}"
        raw = _with_retries(
            lambda s=chunk_start, e=chunk_end: statcast(
                start_dt=s.isoformat(), end_dt=e.isoformat(), verbose=False
            ),
            label,
        )
        if raw is not None and not raw.empty:
            keep = raw[[c for c in RAW_COLS if c in raw.columns]]
            # HR rows carry the landing data; every row feeds game finals —
            # cache the union compactly: all HR rows + per-game maxima.
            hr = keep[keep["events"] == "home_run"]
            finals = keep.groupby("game_pk").agg(
                game_date=("game_date", "first"), home_team=("home_team", "first"),
                away_team=("away_team", "first"), home_final=("post_home_score", "max"),
                away_final=("post_away_score", "max"),
            ).reset_index()
            finals.insert(0, "_kind", "game")
            hr = hr.copy()
            hr.insert(0, "_kind", "hr")
            pd.concat([hr, finals], ignore_index=True).to_csv(out, index=False)
            print(f"  {label}: {len(hr)} HR, {len(finals)} games", flush=True)
        else:
            out.write_text("")
        chunk_start = chunk_end + timedelta(days=1)
    print(f"{season}: download complete", flush=True)


def _frames_from_cache(season: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    chunks = sorted(CACHE_DIR.glob(f"park_{season}_*.csv"))
    if not chunks:
        raise FileNotFoundError(f"no cached chunks for {season} — run download first")
    df = pd.concat([pd.read_csv(c) for c in chunks if c.stat().st_size > 0], ignore_index=True)
    return _split_frames(df, season)


def _split_frames(df: pd.DataFrame, season: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    hr = df[df["_kind"] == "hr"].dropna(subset=["hc_x", "hc_y"]).copy()
    hr["x_ft"] = (hr["hc_x"] - HC_X0) * HC_SCALE
    hr["y_ft"] = (HC_Y0 - hr["hc_y"]) * HC_SCALE
    hr["season"] = season
    # A source day missing one of these (a cache chunk pulled before the
    # column existed, or an odd Statcast day) shouldn't KeyError the whole
    # split — just leave it null for that day rather than losing the HRs.
    for col in _HR_LOG_PITCH_COLS:
        if col not in hr.columns:
            hr[col] = pd.NA
    hr_log = hr[[
        "season", "game_date", "game_pk", "batter", "home_team", "away_team",
        "inning_topbot", "x_ft", "y_ft", "launch_speed", "launch_angle",
        "hit_distance_sc", "des",
        "pitch_type", "release_speed", "plate_x", "plate_z", "sz_top", "sz_bot",
    ]].reset_index(drop=True)

    games = df[df["_kind"] == "game"].drop_duplicates("game_pk").copy()
    games["season"] = season
    park_games = games[[
        "season", "game_date", "game_pk", "home_team", "away_team", "home_final", "away_final",
    ]].dropna(subset=["home_team", "home_final", "away_final"]).reset_index(drop=True)
    return hr_log, park_games


def _store(conn: sqlite3.Connection, table: str, df: pd.DataFrame, season: int) -> None:
    try:
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if existing and existing != set(df.columns):
            conn.execute(f"DROP TABLE {table}")
        else:
            conn.execute(f"DELETE FROM {table} WHERE season = ?", (season,))
    except sqlite3.OperationalError:
        pass
    df.to_sql(table, conn, if_exists="append", index=False)
    conn.commit()


def update_season(season: int) -> None:
    hr_log, park_games = _frames_from_cache(season)
    with sqlite3.connect(DB_PATH) as conn:
        _store(conn, "hr_log", hr_log, season)
        _store(conn, "park_games", park_games, season)
    print(f"  hr_log {season}: {len(hr_log)} rows · park_games {season}: {len(park_games)} rows")


def update_day(day: str) -> None:
    """Nightly increment: fetch one day, append its HRs and finals (no
    cache dependency, safe on the deployed refresh)."""
    from pybaseball import statcast

    raw = statcast(start_dt=day, end_dt=day, verbose=False)
    if raw is None or raw.empty:
        print(f"  ballparks {day}: no games")
        return
    keep = raw[[c for c in RAW_COLS if c in raw.columns]]
    hr = keep[keep["events"] == "home_run"].copy()
    hr.insert(0, "_kind", "hr")
    finals = keep.groupby("game_pk").agg(
        game_date=("game_date", "first"), home_team=("home_team", "first"),
        away_team=("away_team", "first"), home_final=("post_home_score", "max"),
        away_final=("post_away_score", "max"),
    ).reset_index()
    finals.insert(0, "_kind", "game")
    hr_log, park_games = _split_frames(pd.concat([hr, finals], ignore_index=True), int(day[:4]))
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_hr_log_pitch_columns(conn)
        for table, df, key in [("hr_log", hr_log, "game_pk"), ("park_games", park_games, "game_pk")]:
            if df.empty:
                continue
            try:
                pks = tuple(df["game_pk"].unique().tolist())
                conn.execute(
                    f"DELETE FROM {table} WHERE game_pk IN ({','.join('?' * len(pks))})", pks
                )
            except sqlite3.OperationalError:
                pass
            df.to_sql(table, conn, if_exists="append", index=False)
        conn.commit()
    print(f"  ballparks {day}: {len(hr_log)} HR, {len(park_games)} games folded in")


if __name__ == "__main__":
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    end = int(sys.argv[2]) if len(sys.argv) > 2 else start
    for yr in range(start, end + 1):
        print(f"=== {yr} ===")
        download_season(yr)
        update_season(yr)
    print("done")
