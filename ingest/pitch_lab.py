"""Backfill runner for the Pitch Lab / Catcher Defense tables
(pitch_arsenal, catcher_framing, catcher_poptime) across past seasons.

The fetchers themselves live in refresh_data.py — they're the same ones the
nightly refresh runs for the current season; this script just replays them
for a season range so the year-over-year arsenal views have history:

    python ingest/pitch_lab.py 2021 2026

NOTE: after a schema change to any of these fetchers, run the OLDEST season
first — _store_season_table drops and recreates a table on column mismatch
(losing other seasons for that table), so the first season rebuilds the
table under the new schema and every later season appends cleanly.
"""
import sqlite3
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
from refresh_data import (  # noqa: E402
    DB_PATH,
    _store_season_table,
    fetch_catcher_framing,
    fetch_catcher_poptime,
    fetch_pitch_arsenal,
)


def update_season(season: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        for table, fetch in [
            ("pitch_arsenal", fetch_pitch_arsenal),
            ("catcher_framing", fetch_catcher_framing),
            ("catcher_poptime", fetch_catcher_poptime),
        ]:
            df = fetch(season)
            if df.empty:
                print(f"  {table} {season}: no data, skipped")
                continue
            _store_season_table(conn, table, df, season)
            conn.commit()
            print(f"  {table} {season}: {len(df)} rows")


if __name__ == "__main__":
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    end = int(sys.argv[2]) if len(sys.argv) > 2 else start
    for yr in range(start, end + 1):
        print(f"=== {yr} ===")
        update_season(yr)
        time.sleep(2)
    print("done")
