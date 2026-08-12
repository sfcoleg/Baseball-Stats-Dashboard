"""One-time surgical backfill for the `contact_pctile` and `contact_pct`
columns on the `batting` table — adds the columns if missing, then
fetches Statcast contact data per season and UPDATEs existing rows by
(mlbID, season), touching no other column and no other row. Deliberately
NOT routed through refresh_data.py's fetch_batting()/_store_season_table
path — that path drops and rebuilds the whole table on any schema change,
which would mean re-fetching every other bulk stat for all 19 stored
seasons just to add two columns.

Two distinct signals, both real, both worth keeping:
  - contact_pctile: statcast_batter_percentile_ranks' whiff_percent column
    is a PERCENTILE RANK (0-100 vs. that season's league), not a raw rate
    — confirmed directly by cross-checking against K%: Arraez (elite
    contact) came back with whiff_percent=100, a high-K hitter came back
    near 0. Savant's own convention inverts "bad-when-high" stats so 100
    always means "best in the league" — so this column already IS a
    contact percentile, no inversion needed.
  - contact_pct: Savant's "custom leaderboard" builder endpoint returns
    the literal raw rate instead — confirmed against the same Arraez
    (2025: 5.3% whiff, i.e. ~94.7% contact — matches his real known
    skill, not a percentile).

Statcast data (and both these endpoints) only goes back to 2015, so
2008-2014 seasons are correctly left NULL, same as any other Statcast-
only column already is for those years.

Run once after adding both columns to fetch_batting(); future daily/
backfill runs pick them up automatically as part of the normal pipeline.
"""
import sqlite3
import time
from pathlib import Path

from pybaseball import statcast_batter_percentile_ranks

from refresh_data import fetch_savant_custom_leaderboard

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "stats.db"
FIRST_STATCAST_SEASON = 2015


def main():
    conn = sqlite3.connect(DB_PATH)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(batting)")}
    for col in ("contact_pctile", "contact_pct"):
        if col not in cols:
            conn.execute(f"ALTER TABLE batting ADD COLUMN {col} REAL")
            conn.commit()
            print(f"Added {col} column.")

    seasons = [r[0] for r in conn.execute(
        "SELECT DISTINCT season FROM batting WHERE season >= ? ORDER BY season", (FIRST_STATCAST_SEASON,)
    )]
    print(f"Backfilling contact_pctile/contact_pct for seasons: {seasons}")

    for season in seasons:
        print(f"Fetching {season} Statcast contact percentile...")
        try:
            pctile_df = statcast_batter_percentile_ranks(season)
        except Exception as e:
            print(f"  {season}: percentile fetch failed ({e}), skipping percentile")
            pctile_df = None

        print(f"Fetching {season} Statcast raw contact rate...")
        try:
            raw_df = fetch_savant_custom_leaderboard(season, "batter", ["whiff_percent"])
        except Exception as e:
            print(f"  {season}: raw-rate fetch failed ({e}), skipping raw rate")
            raw_df = None

        if pctile_df is not None and not pctile_df.empty:
            rows = [
                (float(row["whiff_percent"]), int(row["player_id"]), season)
                for _, row in pctile_df.dropna(subset=["whiff_percent", "player_id"]).iterrows()
            ]
            conn.executemany(
                "UPDATE batting SET contact_pctile = ? WHERE mlbID = ? AND season = ?", rows
            )
            conn.commit()
            print(f"  {season}: contact_pctile — {len(rows)} rows matched")

        if raw_df is not None and not raw_df.empty:
            rows = [
                (100 - float(row["whiff_percent"]), int(row["player_id"]), season)
                for _, row in raw_df.dropna(subset=["whiff_percent", "player_id"]).iterrows()
            ]
            conn.executemany(
                "UPDATE batting SET contact_pct = ? WHERE mlbID = ? AND season = ?", rows
            )
            conn.commit()
            print(f"  {season}: contact_pct — {len(rows)} rows matched")

        time.sleep(1)  # be polite to Baseball Savant between season requests

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
