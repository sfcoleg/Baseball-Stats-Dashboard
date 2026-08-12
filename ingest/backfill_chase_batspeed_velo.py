"""One-time surgical backfill for four new stat pairs added to the ingest
pipeline: batting.chase_pctile/chase_pct, batting.bat_speed_pctile/
bat_speed, pitching.fastball_velo_pctile/fastball_velo, and
pitching.induced_chase_pctile/induced_chase_pct. Adds columns if missing,
fetches per season, UPDATEs existing rows by (mlbID, season), touching no
other column and no other row — same surgical approach as
backfill_contact_pct.py, avoiding refresh_data.py's fetch_batting()/
fetch_pitching()/_store_season_table path, which drops and rebuilds a
whole table on any schema change.

All four are percentile-rank + raw-rate pairs from the same two Baseball
Savant bulk endpoints already used for contact_pctile/contact_pct:
statcast_batter_percentile_ranks / statcast_pitcher_percentile_ranks for
the _pctile columns, and the "custom leaderboard" builder
(fetch_savant_custom_leaderboard) for the raw ones. Both endpoints only
go back to 2015 (Statcast's own data start), so 2008-2014 seasons are
correctly left NULL, same as every other Statcast-only column already is
for those years.

Run once after adding these columns to fetch_batting()/fetch_pitching();
future daily/backfill runs pick them up automatically as part of the
normal pipeline.
"""
import sqlite3
import time
from pathlib import Path

from pybaseball import statcast_batter_percentile_ranks, statcast_pitcher_percentile_ranks

from refresh_data import fetch_savant_custom_leaderboard

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "stats.db"
FIRST_STATCAST_SEASON = 2015


def _ensure_columns(conn, table, columns):
    existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    for col in columns:
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} REAL")
            conn.commit()
            print(f"Added {table}.{col} column.")


def _update_from(conn, table, df, value_col, target_col, season, transform=None):
    if df is None or df.empty or value_col not in df.columns:
        print(f"  {season}: {target_col} — no data, skipping")
        return
    clean = df.dropna(subset=[value_col, "player_id"])
    rows = [
        (transform(row[value_col]) if transform else float(row[value_col]), int(row["player_id"]), season)
        for _, row in clean.iterrows()
    ]
    conn.executemany(f"UPDATE {table} SET {target_col} = ? WHERE mlbID = ? AND season = ?", rows)
    conn.commit()
    print(f"  {season}: {target_col} — {len(rows)} rows matched")


def main():
    conn = sqlite3.connect(DB_PATH)
    _ensure_columns(conn, "batting", ["chase_pctile", "chase_pct", "bat_speed_pctile", "bat_speed"])
    _ensure_columns(conn, "pitching", ["fastball_velo_pctile", "fastball_velo", "induced_chase_pctile", "induced_chase_pct"])

    seasons = [r[0] for r in conn.execute(
        "SELECT DISTINCT season FROM batting WHERE season >= ? ORDER BY season", (FIRST_STATCAST_SEASON,)
    )]
    print(f"Backfilling for seasons: {seasons}")

    for season in seasons:
        print(f"--- {season} ---")

        print(f"Fetching {season} batter percentile ranks...")
        try:
            b_pctile = statcast_batter_percentile_ranks(season)
        except Exception as e:
            print(f"  batter percentile fetch failed: {e}")
            b_pctile = None
        _update_from(conn, "batting", b_pctile, "chase_percent", "chase_pctile", season)
        _update_from(conn, "batting", b_pctile, "bat_speed", "bat_speed_pctile", season)

        print(f"Fetching {season} batter raw chase/bat-speed rates...")
        try:
            b_raw = fetch_savant_custom_leaderboard(season, "batter", ["oz_swing_percent", "avg_swing_speed"])
        except Exception as e:
            print(f"  batter raw fetch failed: {e}")
            b_raw = None
        _update_from(conn, "batting", b_raw, "oz_swing_percent", "chase_pct", season)
        _update_from(conn, "batting", b_raw, "avg_swing_speed", "bat_speed", season)

        print(f"Fetching {season} pitcher percentile ranks...")
        try:
            p_pctile = statcast_pitcher_percentile_ranks(season)
        except Exception as e:
            print(f"  pitcher percentile fetch failed: {e}")
            p_pctile = None
        _update_from(conn, "pitching", p_pctile, "fb_velocity", "fastball_velo_pctile", season)
        _update_from(conn, "pitching", p_pctile, "chase_percent", "induced_chase_pctile", season)

        print(f"Fetching {season} pitcher raw velocity/chase rates...")
        try:
            p_raw = fetch_savant_custom_leaderboard(season, "pitcher", ["fastball_avg_speed", "oz_swing_percent"])
        except Exception as e:
            print(f"  pitcher raw fetch failed: {e}")
            p_raw = None
        _update_from(conn, "pitching", p_raw, "fastball_avg_speed", "fastball_velo", season)
        _update_from(conn, "pitching", p_raw, "oz_swing_percent", "induced_chase_pct", season)

        time.sleep(1)  # be polite to Baseball Savant between seasons

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
