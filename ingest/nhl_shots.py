"""NHL shot-location ingest — every shot attempt (goal/shot-on-goal/missed/
blocked) from a season's regular-season play-by-play, into data/nhl.db's
`shots` table. Backs the Shot Maps page.

Enumerates a season's games by walking api-web.nhle.com/v1/schedule/<date>
week-by-week (each call returns 7 days and a `nextStartDate` to jump to the
next week), then pulls /v1/gamecenter/<id>/play-by-play for each completed
game. x/y coordinates are normalized so every shot plots as if attacking
the RIGHT-hand goal, regardless of period or home/away — see
_normalize_side().

Usage:
    python ingest/nhl_shots.py 2025          # one season (start year)
    python ingest/nhl_shots.py 2021 2025     # backfill a range
"""
import sqlite3
import sys
import time
from datetime import date, timedelta
from _dates import pacific_today
from pathlib import Path

import pandas as pd
import requests

NHL_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "nhl.db"
HEADERS = {"User-Agent": "Mozilla/5.0"}

SHOT_EVENTS = {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}


def _with_retries(fn, label, attempts=3):
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                print(f"  {label} failed after {attempts} attempts ({e!r}), skipping", flush=True)
                return None
            time.sleep(3 * (i + 1))


def season_game_ids(start_year: int) -> list[int]:
    """Every regular-season game id (gameType 2) played between this
    season's Oct 1 and the following Jul 1, walking week by week."""
    ids, seen_dates = [], set()
    cursor = f"{start_year}-10-01"
    stop = f"{start_year + 1}-07-01"
    while cursor < stop:
        def _get():
            resp = requests.get(f"https://api-web.nhle.com/v1/schedule/{cursor}", timeout=20, headers=HEADERS)
            resp.raise_for_status()
            return resp.json()

        payload = _with_retries(_get, f"schedule {cursor}")
        if not payload:
            break
        for day in payload.get("gameWeek", []):
            if day["date"] in seen_dates:
                continue
            seen_dates.add(day["date"])
            for g in day.get("games", []):
                if g.get("gameType") == 2 and g.get("gameState") in ("OFF", "FINAL"):
                    ids.append(g["id"])
        nxt = payload.get("nextStartDate")
        if not nxt or nxt <= cursor:
            break
        cursor = nxt
    return sorted(set(ids))


def _normalize_side(x, y, home_defending_side, is_home):
    """Flip coordinates so every shot plots as attacking the right-hand
    goal (positive x), regardless of period or which team took it — so a
    player's shot map isn't split across both ends of the rink."""
    if x is None or y is None:
        return None, None
    # homeTeamDefendingSide is the side the HOME team defends this period.
    # The shooting team is attacking the OTHER side.
    attacking_right = (home_defending_side == "left") if is_home else (home_defending_side == "right")
    return (x, y) if attacking_right else (-x, -y)


def fetch_game_shots(game_id: int) -> list[dict]:
    def _get():
        resp = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play", timeout=20, headers=HEADERS)
        resp.raise_for_status()
        return resp.json()

    data = _with_retries(_get, f"play-by-play {game_id}")
    if not data:
        return []
    home_id = data.get("homeTeam", {}).get("id")
    rows = []
    for p in data.get("plays", []):
        kind = p.get("typeDescKey")
        if kind not in SHOT_EVENTS:
            continue
        d = p.get("details") or {}
        team_id = d.get("eventOwnerTeamId")
        is_home = team_id == home_id
        side = (p.get("homeTeamDefendingSide") or "left")
        x, y = _normalize_side(d.get("xCoord"), d.get("yCoord"), side, is_home)
        shooter = d.get("scoringPlayerId") or d.get("shootingPlayerId") or d.get("blockingPlayerId")
        rows.append({
            "gamePk": game_id, "eventId": p.get("eventId"), "period": (p.get("periodDescriptor") or {}).get("number"),
            "timeInPeriod": p.get("timeInPeriod"), "result": kind, "x": x, "y": y, "zoneCode": d.get("zoneCode"),
            "shotType": d.get("shotType"), "teamId": team_id, "shooterId": shooter,
            "goalieId": d.get("goalieInNetId"), "situationCode": p.get("situationCode"),
        })
    return rows


def build_season(start_year: int) -> pd.DataFrame:
    game_ids = season_game_ids(start_year)
    print(f"  {len(game_ids)} games found for {start_year}-{start_year + 1}", flush=True)
    all_rows = []
    for i, gid in enumerate(game_ids):
        all_rows.extend(fetch_game_shots(gid))
        if (i + 1) % 50 == 0:
            print(f"  ...{i + 1}/{len(game_ids)} games processed, {len(all_rows)} shots so far", flush=True)
    df = pd.DataFrame(all_rows)
    if not df.empty:
        df["season"] = start_year
    return df


def store_season(df: pd.DataFrame, start_year: int) -> None:
    NHL_DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            existing = {r[1] for r in conn.execute("PRAGMA table_info(shots)")}
            if existing and not df.empty and existing != set(df.columns):
                conn.execute("DROP TABLE shots")
            else:
                conn.execute("DELETE FROM shots WHERE season = ?", (start_year,))
        except sqlite3.OperationalError:
            pass
        if not df.empty:
            df.to_sql("shots", conn, if_exists="append", index=False)
        conn.commit()


def latest_season_start_year() -> int:
    today = pacific_today()
    return today.year if today.month >= 10 else today.year - 1


def update_latest() -> None:
    yr = latest_season_start_year()
    print(f"=== NHL shots {yr}-{yr + 1} ===")
    store_season(build_season(yr), yr)


def recent_game_ids(days: int) -> list[int]:
    """Regular-season game ids finished in the last `days` days."""
    ids, cursor = [], (pacific_today() - timedelta(days=days)).isoformat()
    stop = (pacific_today() + timedelta(days=1)).isoformat()
    seen = set()
    while cursor < stop:
        payload = _with_retries(
            lambda: requests.get(f"https://api-web.nhle.com/v1/schedule/{cursor}", timeout=20,
                                 headers=HEADERS).json(),
            f"schedule {cursor}")
        if not payload:
            break
        for day in payload.get("gameWeek", []):
            if day["date"] in seen or day["date"] >= stop:
                continue
            seen.add(day["date"])
            for g in day.get("games", []):
                if g.get("gameType") == 2 and g.get("gameState") in ("OFF", "FINAL"):
                    ids.append(g["id"])
        nxt = payload.get("nextStartDate")
        if not nxt or nxt <= cursor:
            break
        cursor = nxt
    return sorted(set(ids))


def update_recent(days: int = 4) -> int:
    """Re-pull just the last few days of games and upsert them.

    The nightly refresh can't afford update_latest(), which re-fetches every
    game of the season (~1,300 requests). A few days of overlap is enough to
    catch last night's games plus anything the NHL corrected after the fact,
    at a handful of requests.
    """
    yr = latest_season_start_year()
    game_ids = recent_game_ids(days)
    if not game_ids:
        print(f"  no finished games in the last {days} days")
        return 0
    rows = []
    for gid in game_ids:
        rows.extend(fetch_game_shots(gid))
    if not rows:
        return 0
    df = pd.DataFrame(rows)
    df["season"] = yr
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            existing = {r[1] for r in conn.execute("PRAGMA table_info(shots)")}
        except sqlite3.OperationalError:
            existing = set()
        if existing and existing != set(df.columns):
            print("  shots table schema differs — run a full backfill instead")
            return 0
        placeholders = ",".join("?" * len(game_ids))
        conn.execute(f"DELETE FROM shots WHERE gamePk IN ({placeholders})", game_ids)
        df.to_sql("shots", conn, if_exists="append", index=False)
        conn.commit()
    print(f"  {len(game_ids)} recent games, {len(df)} shots upserted")
    return len(df)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        start = int(sys.argv[1])
        end = int(sys.argv[2]) if len(sys.argv) > 2 else start
        for yr in range(start, end + 1):
            print(f"=== NHL shots {yr}-{yr + 1} ===")
            df = build_season(yr)
            store_season(df, yr)
            print(f"  stored {len(df)} shots")
    else:
        update_latest()
    print("done")
