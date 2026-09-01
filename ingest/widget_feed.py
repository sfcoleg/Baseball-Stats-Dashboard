"""Widget feed — one compact JSON file (data/widget_feed.json) the native
Mac app and its desktop widgets read straight from the public GitHub repo
(raw.githubusercontent.com), so nothing has to run on the user's machine.

Everything here is the pre-game / standings / leaders picture as of the
nightly refresh; LIVE scores are fetched by the app itself from the MLB
and NHL APIs (one HTTP call on a timer), since a nightly file can't carry
them. Kept small on purpose: a widget renders ~5 rows, not 500.

Usage:
    python ingest/widget_feed.py     # writes data/widget_feed.json
Also called at the end of refresh_data.py's nightly run.
"""
import json
import sqlite3
from datetime import date, datetime, timezone
from _dates import pacific_today
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
STATS_DB = ROOT / "data" / "stats.db"
NHL_DB = ROOT / "data" / "nhl.db"
ELO_PATH = ROOT / "app" / "nhl" / "elo_model.json"
OUT_PATH = ROOT / "data" / "widget_feed.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}  # the NHL CDN rejects unfamiliar agents


def _rows(conn, sql, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _num(v, nd=3):
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


# --- MLB ------------------------------------------------------------------------

def mlb_section() -> dict:
    if not STATS_DB.exists():
        return {}
    with sqlite3.connect(STATS_DB) as conn:
        season = conn.execute("SELECT MAX(season) FROM batting").fetchone()[0]
        standings = _rows(conn, "SELECT league, division, team_abbr, team_name, wins, losses, pct, games_back, "
                                "streak, div_rank, run_diff FROM standings ORDER BY division, CAST(div_rank AS INT)")
        games = _rows(conn, "SELECT date, game_pk, game_time, status, venue, away_abbr, away_team, away_wins, "
                            "away_losses, away_pitcher_name, home_abbr, home_team, home_wins, home_losses, "
                            "home_pitcher_name FROM todays_games ORDER BY game_time")
        batters = _rows(conn, "SELECT mlbID, Name, Tm, HR, RBI, BA, OPS, SB FROM batting WHERE season = ? AND PA >= 50 "
                              "ORDER BY OPS DESC LIMIT 10", (season,))
        hr = _rows(conn, "SELECT mlbID, Name, Tm, HR FROM batting WHERE season = ? ORDER BY HR DESC LIMIT 10", (season,))
        pitchers = _rows(conn, "SELECT mlbID, Name, Tm, W, L, ERA, SO, WHIP FROM pitching WHERE season = ? AND IP >= 20 "
                               "ORDER BY ERA ASC LIMIT 10", (season,))
    for b in batters:
        b["BA"], b["OPS"] = _num(b["BA"]), _num(b["OPS"])
        b["mlbID"] = int(b["mlbID"])
    for h in hr:
        h["mlbID"] = int(h["mlbID"])
    for p in pitchers:
        p["ERA"], p["WHIP"] = _num(p["ERA"], 2), _num(p["WHIP"], 3)
        p["mlbID"] = int(p["mlbID"])
    for g in games:
        g["game_pk"] = int(g["game_pk"])
    return {
        "season": season,
        "standings": standings,
        "today": games,
        "leaders": {"ops": batters, "hr": hr, "era": pitchers},
    }


# --- NHL ------------------------------------------------------------------------

def _get(url):
    try:
        r = requests.get(url, timeout=15, headers=HEADERS)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def nhl_section() -> dict:
    out = {}
    # Standings (live API) — one row per team, trimmed to widget essentials.
    st = _get("https://api-web.nhle.com/v1/standings/now").get("standings", [])
    out["standings"] = [{
        "conference": r.get("conferenceName"), "division": r.get("divisionName"),
        "abbr": (r.get("teamAbbrev") or {}).get("default"), "name": (r.get("teamName") or {}).get("default"),
        "gp": r.get("gamesPlayed"), "w": r.get("wins"), "l": r.get("losses"), "otl": r.get("otLosses"),
        "pts": r.get("points"), "row": r.get("regulationPlusOtWins"), "gd": r.get("goalDifferential"),
        "streak": f"{r.get('streakCode', '')}{r.get('streakCount', '')}", "div_rank": r.get("divisionSequence"),
        "clinch": r.get("clinchIndicator"),
    } for r in st]

    # The next game week (the API's 'now' resolves to the next game day, so
    # this is never empty) — dates, teams, start times, game ids.
    week = _get("https://api-web.nhle.com/v1/schedule/now")
    elo = json.loads(ELO_PATH.read_text()) if ELO_PATH.exists() else {}
    ratings, home_adv = elo.get("ratings", {}), elo.get("home_advantage", 0)

    def p_home(h, a):
        if not ratings:
            return None
        return round(1 / (1 + 10 ** ((ratings.get(a, 1500) - (ratings.get(h, 1500) + home_adv)) / 400)), 3)

    games = []
    for day in week.get("gameWeek", []):
        for g in day.get("games", []):
            a, h = g["awayTeam"]["abbrev"], g["homeTeam"]["abbrev"]
            games.append({
                "date": day["date"], "id": g["id"], "type": g.get("gameType"), "state": g.get("gameState"),
                "start_utc": g.get("startTimeUTC"), "venue": (g.get("venue") or {}).get("default"),
                "away": a, "home": h, "away_score": g["awayTeam"].get("score"), "home_score": g["homeTeam"].get("score"),
                "p_home": p_home(h, a) if g.get("gameType") != 1 else None,
            })
    out["week"] = games
    out["elo"] = {k: round(v) for k, v in ratings.items()}

    if NHL_DB.exists():
        with sqlite3.connect(NHL_DB) as conn:
            season = conn.execute("SELECT MAX(season) FROM skaters").fetchone()[0]
            skaters = _rows(conn, "SELECT playerId, skaterFullName AS name, teamAbbrevs AS team, goals, assists, points "
                                  "FROM skaters WHERE season = ? ORDER BY points DESC LIMIT 10", (season,))
            goals = _rows(conn, "SELECT playerId, skaterFullName AS name, teamAbbrevs AS team, goals FROM skaters "
                                "WHERE season = ? ORDER BY goals DESC LIMIT 10", (season,))
            goalies = _rows(conn, "SELECT playerId, goalieFullName AS name, teamAbbrevs AS team, wins, savePct, "
                                  "goalsAgainstAverage AS gaa FROM goalies WHERE season = ? AND gamesPlayed >= 20 "
                                  "ORDER BY wins DESC LIMIT 10", (season,))
        for r in skaters + goals + goalies:
            r["team"] = (r["team"] or "").split(",")[-1].strip()
        for g in goalies:
            g["savePct"], g["gaa"] = _num(g["savePct"], 1), _num(g["gaa"], 2)
        out["season"] = season
        out["leaders"] = {"points": skaters, "goals": goals, "wins": goalies}
    return out


def build() -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # Pacific, not UTC date.today() — this runs on a UTC-clocked CI
        # runner, which rolls to the next calendar day while it's still
        # afternoon/evening in Pacific time (see refresh_data.py's
        # _pacific_today()).
        "date": pacific_today().isoformat(),
        "mlb": mlb_section(),
        "nhl": nhl_section(),
    }


def write() -> Path:
    feed = build()
    OUT_PATH.write_text(json.dumps(feed, separators=(",", ":"), ensure_ascii=False))
    return OUT_PATH


if __name__ == "__main__":
    path = write()
    print(f"wrote {path} ({path.stat().st_size // 1024} KB)")
