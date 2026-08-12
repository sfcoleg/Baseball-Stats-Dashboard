"""One-time surgical backfill for batting.xISO_pctile/xISO and
batting.xOBP_pctile/xOBP — same pattern as backfill_contact_pct.py and
backfill_chase_batspeed_velo.py: add columns if missing, fetch per
season, UPDATE existing rows by (mlbID, season), touching no other
column and no other row.

xiso/xobp (percentile) come from the same statcast_batter_percentile_
ranks call already used for contact_pctile/chase_pctile/bat_speed_pctile.
xISO/xOBP (raw) come from the same Savant "custom leaderboard" builder
already used for the raw contact/chase/bat-speed columns — confirmed the
selection names are lowercase "xiso"/"xobp" (not "est_iso"/"est_obp",
which return empty) against real values (Judge .409/.434, Arraez
.076/.324 for 2025).

Both endpoints only go back to 2015 (Statcast's own data start); 2008-
2014 seasons correctly left NULL, same as every other Statcast-only
column already is for those years.
"""
import sqlite3
import time
from pathlib import Path

from pybaseball import statcast_batter_percentile_ranks

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


def _update_from(conn, table, df, value_col, target_col, season):
    if df is None or df.empty or value_col not in df.columns:
        print(f"  {season}: {target_col} — no data, skipping")
        return
    clean = df.dropna(subset=[value_col, "player_id"])
    rows = [(float(row[value_col]), int(row["player_id"]), season) for _, row in clean.iterrows()]
    conn.executemany(f"UPDATE {table} SET {target_col} = ? WHERE mlbID = ? AND season = ?", rows)
    conn.commit()
    print(f"  {season}: {target_col} — {len(rows)} rows matched")


def main():
    conn = sqlite3.connect(DB_PATH)
    _ensure_columns(conn, "batting", ["xISO_pctile", "xISO", "xOBP_pctile", "xOBP"])

    seasons = [r[0] for r in conn.execute(
        "SELECT DISTINCT season FROM batting WHERE season >= ? ORDER BY season", (FIRST_STATCAST_SEASON,)
    )]
    print(f"Backfilling xISO/xOBP for seasons: {seasons}")

    for season in seasons:
        print(f"--- {season} ---")
        try:
            pctile = statcast_batter_percentile_ranks(season)
        except Exception as e:
            print(f"  percentile fetch failed: {e}")
            pctile = None
        _update_from(conn, "batting", pctile, "xiso", "xISO_pctile", season)
        _update_from(conn, "batting", pctile, "xobp", "xOBP_pctile", season)

        try:
            raw = fetch_savant_custom_leaderboard(season, "batter", ["xiso", "xobp"])
        except Exception as e:
            print(f"  raw fetch failed: {e}")
            raw = None
        _update_from(conn, "batting", raw, "xiso", "xISO", season)
        _update_from(conn, "batting", raw, "xobp", "xOBP", season)

        time.sleep(1)  # be polite to Baseball Savant between seasons

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
