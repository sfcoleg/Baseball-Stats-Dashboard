"""Umpire scorecard pipeline — grades every called ball/strike against the
rulebook zone and stores one summary row per game in the `ump_games`
table, powering the Umpires page's daily scorecards, season leaderboard,
and per-ump trends.

Data route (deliberately NOT one live-feed fetch per game, which for a
multi-season backfill would mean ~7,000 multi-MB downloads):
  - Umpire identity + game metadata: the schedule API with
    hydrate=officials,team,linescore — verified it returns the home-plate
    umpire for 100% of historical Final games, a month of games per call.
  - Called pitches: Baseball Savant bulk pulls via pybaseball.statcast,
    one call per month-chunk, every pitch league-wide with plate location
    and the batter's own measured zone bounds.

Judgment (mirrored EXACTLY in app/db.py's live-scorecard path — the two
must stay in sync, same constants, same signed-distance math):
  - Rulebook zone, ball-radius allowance: a called strike is correct if
    ANY part of the ball crossed the zone — |plate_x| <= 17/2 inches +
    ball radius, and plate_z within [sz_bot - r, sz_top + r], using THAT
    batter's measured zone (so a knee-high pitch is judged against
    Altuve's zone when Altuve bats and Judge's when Judge bats).
  - Signed distance (inches): negative = inside the strike region,
    positive = outside; magnitude = distance to the region's boundary.
    Correct call <=> sign agrees with the call.
  - Difficulty buckets by signed distance, for the leaderboard's
    "accuracy vs expected" adjustment (league average accuracy per bucket
    x each ump's own bucket mix): (-inf,-3], (-3,-1], (-1,0], (0,1],
    (1,3], (3,inf).
  - Only human judgment calls count: called_strike / ball / blocked_ball.
    Automatic balls/strikes (pitch-clock violations), pitchouts, HBP and
    swings are excluded.

Known honest limitations, surfaced on the page rather than hidden:
pitch tracking itself carries ~0.5in measurement error (borderline
"misses" are approximate — "clear misses" use a 1in buffer), and under
2026's ABS challenge rules an overturned call may be recorded post-
correction, slightly flattering measured accuracy this season.

Run as a script to backfill: venv/bin/python ingest/ump_scorecards.py
2024 2025 2026. The nightly ingest calls update_day() for yesterday.
"""
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "stats.db"

BALL_RADIUS_FT = 0.1208          # 2.9in diameter baseball
HALF_PLATE_FT = 17 / 2 / 12      # rulebook plate half-width
ZONE_HALF_X = HALF_PLATE_FT + BALL_RADIUS_FT
CLEAR_MISS_IN = 1.0
BUCKET_EDGES_IN = (-3.0, -1.0, 0.0, 1.0, 3.0)   # signed inches -> 6 buckets

CALLED_DESCRIPTIONS = {"called_strike", "ball", "blocked_ball"}

UMP_GAMES_COLUMNS = (
    "date", "season", "game_pk", "ump_id", "ump_name",
    "away_abbr", "home_abbr", "away_score", "home_score",
    "called", "correct", "wrong_strikes", "wrong_balls", "clear_misses",
    "favor_home", "worst_desc", "worst_miss_in",
    "b0_n", "b1_n", "b2_n", "b3_n", "b4_n", "b5_n",
    "b0_c", "b1_c", "b2_c", "b3_c", "b4_c", "b5_c",
)


def signed_distance_in(px: float, pz: float, sz_top: float, sz_bot: float) -> float:
    """Signed distance (inches) from the ball-radius-expanded strike
    region: negative inside (depth to the nearest boundary), positive
    outside (euclidean distance to the region)."""
    lo_z, hi_z = sz_bot - BALL_RADIUS_FT, sz_top + BALL_RADIUS_FT
    dx = abs(px) - ZONE_HALF_X          # >0 means outside horizontally
    dz = max(lo_z - pz, pz - hi_z)      # >0 means outside vertically
    if dx <= 0 and dz <= 0:
        return 12.0 * max(dx, dz)       # inside: negative, nearest edge
    return 12.0 * ((max(dx, 0.0) ** 2 + max(dz, 0.0) ** 2) ** 0.5)


def bucket_index(d_in: float) -> int:
    for i, edge in enumerate(BUCKET_EDGES_IN):
        if d_in <= edge:
            return i
    return len(BUCKET_EDGES_IN)


def fetch_officials(start: str, end: str) -> dict:
    """{game_pk: metadata dict} for Final regular-season games in a date
    range, from one schedule call with officials/team/linescore hydrated."""
    resp = requests.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={
            "sportId": 1, "gameType": "R", "startDate": start, "endDate": end,
            "hydrate": "officials,team,linescore",
        },
        timeout=120,
    )
    resp.raise_for_status()
    games = {}
    for d in resp.json().get("dates", []):
        for g in d.get("games", []):
            if g.get("status", {}).get("detailedState") != "Final":
                continue
            hp = next(
                (o for o in (g.get("officials") or []) if o.get("officialType") == "Home Plate"),
                None,
            )
            if not hp or not hp.get("official"):
                continue
            games[g["gamePk"]] = {
                "date": g.get("officialDate") or d.get("date"),
                "ump_id": hp["official"]["id"],
                "ump_name": hp["official"].get("fullName", "Unknown"),
                "away_abbr": g["teams"]["away"]["team"].get("abbreviation"),
                "home_abbr": g["teams"]["home"]["team"].get("abbreviation"),
                "away_score": g["teams"]["away"].get("score"),
                "home_score": g["teams"]["home"].get("score"),
            }
    return games


def grade_called_pitches(pitches: pd.DataFrame) -> dict:
    """Aggregate one game's called pitches (Savant columns) into one
    ump_games stat dict. `pitches` must already be filtered to one
    game_pk and to CALLED_DESCRIPTIONS, with plate/zone fields present."""
    called = correct = wrong_strikes = wrong_balls = clear = favor_home = 0
    bucket_n = [0] * 6
    bucket_c = [0] * 6
    worst_d = 0.0
    worst_desc = None
    for _, p in pitches.iterrows():
        d = signed_distance_in(p["plate_x"], p["plate_z"], p["sz_top"], p["sz_bot"])
        is_strike_call = p["description"] == "called_strike"
        ok = (d <= 0) == is_strike_call
        called += 1
        b = bucket_index(d)
        bucket_n[b] += 1
        if ok:
            correct += 1
            bucket_c[b] += 1
            continue
        away_batting = p["inning_topbot"] == "Top"
        if is_strike_call:
            wrong_strikes += 1
            favor_home += 1 if away_batting else -1
        else:
            wrong_balls += 1
            favor_home += -1 if away_batting else 1
        miss_by = abs(d) if is_strike_call else abs(d)
        if abs(d) > CLEAR_MISS_IN:
            clear += 1
        if abs(d) > worst_d:
            worst_d = abs(d)
            side = "Top" if away_batting else "Bottom"
            if is_strike_call:
                worst_desc = (
                    f'Called strike {d:.1f}" outside the zone '
                    f'({side} {int(p["inning"])}, count {int(p["balls"])}-{int(p["strikes"])})'
                )
            else:
                worst_desc = (
                    f'Called ball {abs(d):.1f}" inside the zone '
                    f'({side} {int(p["inning"])}, count {int(p["balls"])}-{int(p["strikes"])})'
                )
    return {
        "called": called, "correct": correct,
        "wrong_strikes": wrong_strikes, "wrong_balls": wrong_balls,
        "clear_misses": clear, "favor_home": favor_home,
        "worst_desc": worst_desc, "worst_miss_in": round(worst_d, 2),
        **{f"b{i}_n": bucket_n[i] for i in range(6)},
        **{f"b{i}_c": bucket_c[i] for i in range(6)},
    }


def _ensure_table(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ump_games ("
        "date TEXT, season INTEGER, game_pk INTEGER, ump_id INTEGER, ump_name TEXT, "
        "away_abbr TEXT, home_abbr TEXT, away_score INTEGER, home_score INTEGER, "
        "called INTEGER, correct INTEGER, wrong_strikes INTEGER, wrong_balls INTEGER, "
        "clear_misses INTEGER, favor_home INTEGER, worst_desc TEXT, worst_miss_in REAL, "
        "b0_n INTEGER, b1_n INTEGER, b2_n INTEGER, b3_n INTEGER, b4_n INTEGER, b5_n INTEGER, "
        "b0_c INTEGER, b1_c INTEGER, b2_c INTEGER, b3_c INTEGER, b4_c INTEGER, b5_c INTEGER)"
    )


def _with_retries(fn, label: str, attempts: int = 3):
    """A multi-season backfill makes dozens of large downloads — one
    transient mid-download hiccup (confirmed: a ChunkedEncodingError from
    Savant killed a run mid-season) shouldn't cost the whole hour. Retries
    with backoff; re-raises only after the last attempt."""
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            if i == attempts - 1:
                raise
            wait = 10 * (i + 1)
            print(f"  {label}: attempt {i + 1} failed ({type(e).__name__}), retrying in {wait}s...")
            time.sleep(wait)


def _process_range(start: str, end: str, season: int) -> list[dict]:
    """Fetch officials + Savant pitches for a date range and grade every
    game that has both. Returns ump_games row dicts."""
    from pybaseball import statcast

    meta = _with_retries(lambda: fetch_officials(start, end), f"officials {start}")
    if not meta:
        return []
    raw = _with_retries(lambda: statcast(start_dt=start, end_dt=end, verbose=False), f"statcast {start}")
    if raw is None or raw.empty:
        return []
    calls = raw[raw["description"].isin(CALLED_DESCRIPTIONS)].dropna(
        subset=["plate_x", "plate_z", "sz_top", "sz_bot", "game_pk"]
    )[["game_pk", "description", "plate_x", "plate_z", "sz_top", "sz_bot",
       "inning_topbot", "inning", "balls", "strikes"]]

    rows = []
    for game_pk, group in calls.groupby("game_pk"):
        info = meta.get(int(game_pk))
        if not info or len(group) < 20:  # a real game has 100+ called pitches
            continue
        stats = grade_called_pitches(group)
        rows.append({
            "date": info["date"], "season": season, "game_pk": int(game_pk),
            "ump_id": info["ump_id"], "ump_name": info["ump_name"],
            "away_abbr": info["away_abbr"], "home_abbr": info["home_abbr"],
            "away_score": info["away_score"], "home_score": info["home_score"],
            **stats,
        })
    return rows


def _insert(conn, rows: list[dict]):
    if not rows:
        return
    placeholders = ", ".join("?" * len(UMP_GAMES_COLUMNS))
    conn.executemany(
        f"INSERT INTO ump_games ({', '.join(UMP_GAMES_COLUMNS)}) VALUES ({placeholders})",
        [tuple(r[c] for c in UMP_GAMES_COLUMNS) for r in rows],
    )
    conn.commit()


def update_day(day: str):
    """Nightly-ingest entry point: (re)grade one date's games. Deletes that
    date's rows first so reruns are idempotent."""
    season = int(day[:4])
    rows = _process_range(day, day, season)
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_table(conn)
        conn.execute("DELETE FROM ump_games WHERE date = ?", (day,))
        _insert(conn, rows)
    print(f"ump_games: {day} -> {len(rows)} games")


def backfill_season(season: int):
    """Month-chunked full-season backfill (memory-bounded: one month of
    league-wide Savant pitches at a time, subset immediately)."""
    today = date.today()
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_table(conn)
        conn.execute("DELETE FROM ump_games WHERE season = ?", (season,))
        conn.commit()
        total = 0
        for month in range(3, 12):
            start = date(season, month, 1)
            end = date(season, month + 1, 1) - timedelta(days=1) if month < 11 else date(season, 11, 30)
            if start > today:
                break
            if end > today:
                end = today
            rows = _process_range(start.isoformat(), end.isoformat(), season)
            _insert(conn, rows)
            total += len(rows)
            print(f"  {season}-{month:02d}: {len(rows)} games (season total {total})")
            time.sleep(1)
    print(f"ump_games: season {season} -> {total} games")


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(f"Backfilling {arg}...")
        backfill_season(int(arg))
