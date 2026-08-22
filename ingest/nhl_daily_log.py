"""NHL daily per-game player log — one row per skater/goalie for each
game played on a given date, built from play-by-play. This is the NHL
analog of the MLB side's recent_batting/recent_pitching "day" rows: it's
what powers Home's daily Milestones (hat tricks, shutouts, season-goal/
point milestones crossed) and the Headliners trending cards (hot
yesterday/this week/this month) — none of which season-aggregate tables
alone can answer, since they don't know WHEN a stat was earned.

Unlike MLB's recent_* tables, week/month aren't pre-aggregated here —
daily_skater_log/daily_goalie_log just accumulate one row per player per
game, and nhl/db.py sums over the trailing window at read time. NHL's
nightly volume (a few hundred rows) makes that trivial; pre-aggregating
would just be extra ingest complexity for no real benefit at this scale.

Usage:
    python ingest/nhl_daily_log.py 2026-04-16   # backfill one date
    python ingest/nhl_daily_log.py              # yesterday (Pacific)
"""
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

NHL_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "nhl.db"
HEADERS = {"User-Agent": "Mozilla/5.0"}
MIN_SHOTS_FOR_SHUTOUT = 5  # guards against crediting a token mop-up appearance


def _with_retries(fn, label, attempts=3):
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                print(f"  {label} failed, skipping: {e!r}", flush=True)
                return None
            time.sleep(3 * (i + 1))


def games_on(date_str: str) -> list[dict]:
    """Every finished regular-season game on `date_str`."""
    def _get():
        resp = requests.get(f"https://api-web.nhle.com/v1/schedule/{date_str}", timeout=20, headers=HEADERS)
        resp.raise_for_status()
        return resp.json()

    payload = _with_retries(_get, f"schedule {date_str}")
    if not payload:
        return []
    for day in payload.get("gameWeek", []):
        if day["date"] == date_str:
            return [
                g for g in day.get("games", [])
                if g.get("gameType") == 2 and g.get("gameState") in ("OFF", "FINAL")
            ]
    return []


def _game_player_lines(pbp_data: dict) -> tuple[dict, dict]:
    """(skater_lines, goalie_lines) for one game — playerId -> stat dict."""
    data = pbp_data
    skaters: dict[int, dict] = {}
    goalies: dict[int, dict] = {}

    def _sk(pid):
        return skaters.setdefault(pid, {"goals": 0, "assists": 0})

    def _gl(pid):
        return goalies.setdefault(pid, {"goalsAgainst": 0, "shotsAgainst": 0})

    for p in data.get("plays", []):
        kind = p.get("typeDescKey")
        d = p.get("details") or {}
        if kind == "goal":
            scorer = d.get("scoringPlayerId")
            if scorer:
                _sk(scorer)["goals"] += 1
            for assist_key in ("assist1PlayerId", "assist2PlayerId"):
                aid = d.get(assist_key)
                if aid:
                    _sk(aid)["assists"] += 1
            goalie = d.get("goalieInNetId")
            if goalie:
                line = _gl(goalie)
                line["goalsAgainst"] += 1
                line["shotsAgainst"] += 1
        elif kind == "shot-on-goal":
            goalie = d.get("goalieInNetId")
            if goalie:
                _gl(goalie)["shotsAgainst"] += 1

    return skaters, goalies


def _roster_team_map(pbp_data: dict) -> dict:
    """playerId -> team abbrev, from the play-by-play's own roster list (so
    this needs no extra API call)."""
    data = pbp_data
    home_id, away_id = data.get("homeTeam", {}).get("id"), data.get("awayTeam", {}).get("id")
    home_abbr, away_abbr = data.get("homeTeam", {}).get("abbrev"), data.get("awayTeam", {}).get("abbrev")
    out = {}
    for r in data.get("rosterSpots", []):
        out[r["playerId"]] = home_abbr if r.get("teamId") == home_id else away_abbr
    return out


def build_day(date_str: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    games = games_on(date_str)
    season = int(date_str[:4]) if int(date_str[5:7]) >= 10 else int(date_str[:4]) - 1
    skater_rows, goalie_rows = [], []
    for g in games:
        def _get():
            resp = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{g['id']}/play-by-play", timeout=20, headers=HEADERS)
            resp.raise_for_status()
            return resp.json()

        pbp = _with_retries(_get, f"play-by-play {g['id']}")
        if not pbp:
            continue
        skaters, goalies = _game_player_lines(pbp)
        team_map = _roster_team_map(pbp)
        for pid, line in skaters.items():
            skater_rows.append({
                "season": season, "date": date_str, "gamePk": g["id"], "playerId": pid,
                "Tm": team_map.get(pid, ""), "goals": line["goals"], "assists": line["assists"],
                "points": line["goals"] + line["assists"],
            })
        for pid, line in goalies.items():
            shutout = line["goalsAgainst"] == 0 and line["shotsAgainst"] >= MIN_SHOTS_FOR_SHUTOUT
            goalie_rows.append({
                "season": season, "date": date_str, "gamePk": g["id"], "playerId": pid,
                "Tm": team_map.get(pid, ""), "goalsAgainst": line["goalsAgainst"],
                "shotsAgainst": line["shotsAgainst"], "shutout": int(shutout),
            })
    return pd.DataFrame(skater_rows), pd.DataFrame(goalie_rows)


def store_day(skater_df: pd.DataFrame, goalie_df: pd.DataFrame, date_str: str) -> None:
    NHL_DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(NHL_DB_PATH) as conn:
        for table, df in (("daily_skater_log", skater_df), ("daily_goalie_log", goalie_df)):
            try:
                existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
                if existing and not df.empty and existing != set(df.columns):
                    conn.execute(f"DROP TABLE {table}")
                else:
                    conn.execute(f"DELETE FROM {table} WHERE date = ?", (date_str,))
            except sqlite3.OperationalError:
                pass
            if not df.empty:
                df.to_sql(table, conn, if_exists="append", index=False)
        conn.commit()


def update_date(date_str: str) -> None:
    print(f"=== NHL daily log {date_str} ===", flush=True)
    skater_df, goalie_df = build_day(date_str)
    store_day(skater_df, goalie_df, date_str)
    print(f"  {len(skater_df)} skater lines, {len(goalie_df)} goalie lines", flush=True)


def update_yesterday() -> None:
    yesterday = (datetime.now(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=1)).isoformat()
    update_date(yesterday)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        update_date(sys.argv[1])
    else:
        update_yesterday()
    print("done")
