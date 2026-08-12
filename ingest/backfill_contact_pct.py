"""One-time surgical backfill for the new `contact_pctile` column on the
`batting` table — adds the column if missing, then fetches Statcast
percentile-rank data per season and UPDATEs existing rows by (mlbID,
season), touching no other column and no other row. Deliberately NOT
routed through refresh_data.py's fetch_batting()/_store_season_table
path — that path drops and rebuilds the whole table on any schema change,
which would mean re-fetching every other bulk stat for all 19 stored
seasons just to add one column.

statcast_batter_percentile_ranks returns PERCENTILE RANKS (0-100 vs. that
season's league), not raw rates — confirmed directly by cross-checking
against K%: Arraez (elite contact) came back with whiff_percent=100, a
high-K hitter came back near 0. Savant's own convention inverts "bad-
when-high" stats so 100 always means "best in the league" — so the raw
whiff_percent column already IS a contact percentile, no inversion
needed. Statcast data (and this endpoint) only goes back to 2015, so
2008-2014 seasons are left with a NULL contact_pctile, same as any other
Statcast-only column already is for those years.

Run once after adding contact_pctile to fetch_batting(); future daily/
backfill runs pick it up automatically as part of the normal pipeline.
"""
import sqlite3
import time
from pathlib import Path

from pybaseball import statcast_batter_percentile_ranks

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "stats.db"
FIRST_STATCAST_SEASON = 2015


def main():
    conn = sqlite3.connect(DB_PATH)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(batting)")}
    if "contact_pct" in cols:
        conn.execute("ALTER TABLE batting DROP COLUMN contact_pct")
        conn.commit()
        print("Dropped incorrectly-inverted contact_pct column.")
    if "contact_pctile" not in cols:
        conn.execute("ALTER TABLE batting ADD COLUMN contact_pctile REAL")
        conn.commit()
        print("Added contact_pctile column.")

    seasons = [r[0] for r in conn.execute(
        "SELECT DISTINCT season FROM batting WHERE season >= ? ORDER BY season", (FIRST_STATCAST_SEASON,)
    )]
    print(f"Backfilling contact_pctile for seasons: {seasons}")

    for season in seasons:
        print(f"Fetching {season} Statcast contact rate...")
        try:
            df = statcast_batter_percentile_ranks(season)
        except Exception as e:
            print(f"  {season}: fetch failed ({e}), skipping")
            continue
        if df.empty:
            print(f"  {season}: no data, skipping")
            continue
        rows = [
            (float(row["whiff_percent"]), int(row["player_id"]), season)
            for _, row in df.dropna(subset=["whiff_percent", "player_id"]).iterrows()
        ]
        conn.executemany(
            "UPDATE batting SET contact_pctile = ? WHERE mlbID = ? AND season = ?", rows
        )
        conn.commit()
        updated = conn.execute(
            "SELECT COUNT(*) FROM batting WHERE season = ? AND contact_pctile IS NOT NULL", (season,)
        ).fetchone()[0]
        print(f"  {season}: {len(rows)} rows matched, {updated} total rows now have contact_pctile")
        time.sleep(1)  # be polite to Baseball Savant between season requests

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
