"""NHL data layer — readers over data/nhl.db (built by ingest/nhl_refresh.py)
plus live reads straight from the NHL's public api-web.nhle.com (standings,
scores, rosters, player bios) that are never worth nightly-ingesting since
they're small, change in-season, and the API already serves them fast.
Deliberately separate from the MLB db module: different database file,
different tables, independent refresh."""
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

NHL_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "nhl.db"
ELO_MODEL_PATH = Path(__file__).resolve().parent / "elo_model.json"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def nhl_db_mtime() -> float:
    return NHL_DB_PATH.stat().st_mtime if NHL_DB_PATH.exists() else 0.0


def today_pacific() -> date:
    """Same Pacific-anchored 'what day is it' as the MLB side (db.py) — see
    that module's docstring for why (Streamlit Cloud runs in UTC, which
    rolls over to "tomorrow" while it's still evening on the US west
    coast)."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).date()


def percentile_rank(series: pd.Series, value, lower_is_better: bool = False) -> int | None:
    """Percentile of `value` within `series` (0-100). Same as the MLB side's
    db.percentile_rank() — duplicated rather than cross-imported to keep
    the two sport modules independent."""
    clean = series.dropna()
    if value is None or pd.isna(value) or len(clean) == 0:
        return None
    pct = (clean >= value).mean() * 100 if lower_is_better else (clean <= value).mean() * 100
    return int(round(pct))


@st.cache_data(show_spinner=False, max_entries=2)
def skater_seasons(db_mtime_val: float) -> list[int]:
    """Season start years available, newest first (2025 = 2025-26)."""
    if not NHL_DB_PATH.exists():
        return []
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            rows = conn.execute("SELECT DISTINCT season FROM skaters ORDER BY season DESC").fetchall()
        except sqlite3.OperationalError:
            return []
    return [r[0] for r in rows]


@st.cache_data(show_spinner=False, max_entries=4)
def load_skaters(season: int, db_mtime_val: float) -> pd.DataFrame:
    if not NHL_DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            return pd.read_sql("SELECT * FROM skaters WHERE season = ?", conn, params=(season,))
        except pd.errors.DatabaseError:
            return pd.DataFrame()


@st.cache_data(show_spinner=False, max_entries=2)
def goalie_seasons(db_mtime_val: float) -> list[int]:
    if not NHL_DB_PATH.exists():
        return []
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            rows = conn.execute("SELECT DISTINCT season FROM goalies ORDER BY season DESC").fetchall()
        except sqlite3.OperationalError:
            return []
    return [r[0] for r in rows]


@st.cache_data(show_spinner=False, max_entries=4)
def load_goalies(season: int, db_mtime_val: float) -> pd.DataFrame:
    if not NHL_DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            return pd.read_sql("SELECT * FROM goalies WHERE season = ?", conn, params=(season,))
        except pd.errors.DatabaseError:
            return pd.DataFrame()


@st.cache_data(show_spinner=False, max_entries=8)
def load_skater_career(player_id: int, db_mtime_val: float) -> pd.DataFrame:
    """Every season we have on file for one skater, oldest first — for the
    player profile's season-by-season table (our own ingested columns, so
    it has xG/CF%/etc. that the NHL's own player-landing endpoint lacks)."""
    if not NHL_DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            return pd.read_sql(
                "SELECT * FROM skaters WHERE playerId = ? ORDER BY season", conn, params=(int(player_id),)
            )
        except pd.errors.DatabaseError:
            return pd.DataFrame()


@st.cache_data(show_spinner=False, max_entries=8)
def load_goalie_career(player_id: int, db_mtime_val: float) -> pd.DataFrame:
    if not NHL_DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            return pd.read_sql(
                "SELECT * FROM goalies WHERE playerId = ? ORDER BY season", conn, params=(int(player_id),)
            )
        except pd.errors.DatabaseError:
            return pd.DataFrame()


def season_label(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"


@st.cache_data(show_spinner=False, max_entries=2)
def shot_seasons(db_mtime_val: float) -> list[int]:
    if not NHL_DB_PATH.exists():
        return []
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            rows = conn.execute("SELECT DISTINCT season FROM shots ORDER BY season DESC").fetchall()
        except sqlite3.OperationalError:
            return []
    return [r[0] for r in rows]


@st.cache_data(show_spinner=False, max_entries=4)
def load_shots(season: int, db_mtime_val: float) -> pd.DataFrame:
    """Every shot attempt (goal/shot-on-goal/missed/blocked) for a season —
    see ingest/nhl_shots.py. Can be a large-ish table (~100k+ rows/season);
    callers filter down to one player or team."""
    if not NHL_DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            return pd.read_sql("SELECT * FROM shots WHERE season = ?", conn, params=(season,))
        except pd.errors.DatabaseError:
            return pd.DataFrame()


# ---------------------------------------------------------------------------
# Daily per-game log (ingest/nhl_daily_log.py) — powers Home's daily
# Milestones and the Headliners day/week/month trending cards. Unlike the
# season tables above, this is genuinely time-aware: it knows WHEN a goal
# was scored, which season totals alone can't answer.
# ---------------------------------------------------------------------------

GOAL_MILESTONE_THRESHOLDS = [20, 30, 40, 50, 60]
POINT_MILESTONE_THRESHOLDS = [50, 75, 100, 125, 150]
RECENT_MIN_GAMES = {"week": 3, "month": 8}


def _read_daily_log(table: str, where: str, params: tuple) -> pd.DataFrame:
    if not NHL_DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            return pd.read_sql(f"SELECT * FROM {table} WHERE {where}", conn, params=params)
        except pd.errors.DatabaseError:
            return pd.DataFrame()


def load_daily_skater_log(date_str: str) -> pd.DataFrame:
    return _read_daily_log("daily_skater_log", "date = ?", (date_str,))


def load_daily_goalie_log(date_str: str) -> pd.DataFrame:
    return _read_daily_log("daily_goalie_log", "date = ?", (date_str,))


def _window_skater_log(days: int, end_date: date) -> pd.DataFrame:
    start = (end_date - timedelta(days=days - 1)).isoformat()
    df = _read_daily_log("daily_skater_log", "date >= ? AND date <= ?", (start, end_date.isoformat()))
    if df.empty:
        return df
    agg = df.groupby("playerId").agg(
        goals=("goals", "sum"), assists=("assists", "sum"), points=("points", "sum"), games=("gamePk", "nunique"),
    ).reset_index()
    agg["Tm"] = agg["playerId"].map(df.sort_values("date").groupby("playerId")["Tm"].last())
    return agg


def _window_goalie_log(days: int, end_date: date) -> pd.DataFrame:
    start = (end_date - timedelta(days=days - 1)).isoformat()
    df = _read_daily_log("daily_goalie_log", "date >= ? AND date <= ?", (start, end_date.isoformat()))
    if df.empty:
        return df
    agg = df.groupby("playerId").agg(
        goalsAgainst=("goalsAgainst", "sum"), shotsAgainst=("shotsAgainst", "sum"),
        shutouts=("shutout", "sum"), games=("gamePk", "nunique"),
    ).reset_index()
    agg["savePct"] = (1 - agg["goalsAgainst"] / agg["shotsAgainst"].replace(0, pd.NA)) * 100
    agg["Tm"] = agg["playerId"].map(df.sort_values("date").groupby("playerId")["Tm"].last())
    return agg


def top_recent_skater(period: str, season: int, db_mtime_val: float, as_of: date | None = None):
    """Best skater performance for 'day'/'week'/'month', ending at `as_of`
    (default: yesterday Pacific) — a pd.Series with name/Tm/playerId/stat
    line, or None if nothing qualifies (e.g. offseason)."""
    end = as_of or (today_pacific() - timedelta(days=1))
    if period == "day":
        df = load_daily_skater_log(end.isoformat())
    else:
        df = _window_skater_log(7 if period == "week" else 30, end)
        min_games = RECENT_MIN_GAMES.get(period, 1)
        df = df[df["games"] >= min_games] if not df.empty else df
    if df.empty:
        return None
    names = load_skaters(season, db_mtime_val)[["playerId", "skaterFullName"]]
    df = df.merge(names, on="playerId", how="left")
    return df.sort_values(["points", "goals"], ascending=False).iloc[0]


def top_recent_goalie(period: str, season: int, db_mtime_val: float, as_of: date | None = None):
    """Best goalie performance for 'day'/'week'/'month' — ranked by saves
    for a single day (workload matters when everyone's SV% clusters near
    1.000 on a light night), by SV% (min shots faced) for week/month."""
    end = as_of or (today_pacific() - timedelta(days=1))
    if period == "day":
        df = load_daily_goalie_log(end.isoformat())
        if df.empty:
            return None
        df = df[df["shotsAgainst"] >= 5]
        if df.empty:
            return None
        df = df.assign(saves=df["shotsAgainst"] - df["goalsAgainst"])
        rank_cols = ["saves"]
    else:
        df = _window_goalie_log(7 if period == "week" else 30, end)
        if df.empty:
            return None
        min_shots = 30 if period == "week" else 100
        df = df[df["shotsAgainst"] >= min_shots]
        if df.empty:
            return None
        rank_cols = ["savePct"]
    names = load_goalies(season, db_mtime_val)[["playerId", "goalieFullName"]]
    df = df.merge(names, on="playerId", how="left")
    return df.sort_values(rank_cols, ascending=False).iloc[0]


def get_daily_milestones(date_str: str, season: int, db_mtime_val: float) -> list[dict]:
    """Hat tricks, shutouts, and season goal/point milestones crossed on
    `date_str` — the NHL analog of the MLB side's db.get_milestones()."""
    milestones = []
    day_skaters = load_daily_skater_log(date_str)
    if not day_skaters.empty:
        season_skaters = load_skaters(season, db_mtime_val)[["playerId", "skaterFullName", "goals", "points"]]
        merged = day_skaters.merge(season_skaters, on="playerId", how="left", suffixes=("", "_season"))
        for _, row in merged.iterrows():
            if row["goals"] >= 3:
                milestones.append({
                    "playerId": row["playerId"], "name": row["skaterFullName"], "Tm": row["Tm"],
                    "category": "Hat Trick", "text": f"{int(row['goals'])}-goal game",
                })
            if pd.notna(row.get("goals_season")):
                before = row["goals_season"] - row["goals"]
                for t in GOAL_MILESTONE_THRESHOLDS:
                    if before < t <= row["goals_season"]:
                        milestones.append({
                            "playerId": row["playerId"], "name": row["skaterFullName"], "Tm": row["Tm"],
                            "category": "Goal Milestone", "text": f"Reached {t} goals this season",
                        })
            if pd.notna(row.get("points_season")):
                before = row["points_season"] - row["points"]
                for t in POINT_MILESTONE_THRESHOLDS:
                    if before < t <= row["points_season"]:
                        milestones.append({
                            "playerId": row["playerId"], "name": row["skaterFullName"], "Tm": row["Tm"],
                            "category": "Point Milestone", "text": f"Reached {t} points this season",
                        })

    day_goalies = load_daily_goalie_log(date_str)
    if not day_goalies.empty:
        season_goalies = load_goalies(season, db_mtime_val)[["playerId", "goalieFullName"]]
        merged = day_goalies.merge(season_goalies, on="playerId", how="left")
        for _, row in merged[merged["shutout"] == 1].iterrows():
            milestones.append({
                "playerId": row["playerId"], "name": row["goalieFullName"], "Tm": row["Tm"],
                "category": "Shutout", "text": f"Shutout ({int(row['shotsAgainst'])} saves)",
            })

    _priority = {"Hat Trick": 0, "Shutout": 1, "Point Milestone": 2, "Goal Milestone": 3}
    milestones.sort(key=lambda m: _priority.get(m["category"], 99))
    return milestones


@st.cache_data(show_spinner=False, max_entries=2)
def load_geo_places(db_mtime_val: float) -> pd.DataFrame:
    """Geocoded birthplaces (ingest/nhl_geocode.py): city/region/country ->
    lat/lon. Rows with NULL lat are places Nominatim couldn't match."""
    if not NHL_DB_PATH.exists():
        return pd.DataFrame(columns=["city", "region", "country", "lat", "lon"])
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            return pd.read_sql("SELECT city, region, country, lat, lon FROM geo_places", conn)
        except pd.errors.DatabaseError:
            return pd.DataFrame(columns=["city", "region", "country", "lat", "lon"])


@st.cache_data(show_spinner=False, max_entries=4)
def load_birthplaces(season: int, db_mtime_val: float) -> pd.DataFrame:
    """One row per player (skaters + goalies) for a season, with birthplace
    and its geocoded lat/lon — the Birthplace Map's data. Players whose
    birthplace couldn't be geocoded come back with NaN lat/lon so the page
    can count them honestly rather than silently dropping them."""
    skaters = load_skaters(season, db_mtime_val)
    goalies = load_goalies(season, db_mtime_val)
    cols = ["playerId", "teamAbbrevs", "positionCode", "gamesPlayed", "birthCity",
            "birthStateProvinceCode", "birthCountryCode", "nationalityCode"]
    frames = []
    if not skaters.empty and "birthCity" in skaters.columns:
        s = skaters[cols + ["skaterFullName", "points"]].rename(columns={"skaterFullName": "name"})
        s["role"] = "Skater"
        frames.append(s)
    if not goalies.empty and "birthCity" in goalies.columns:
        g = goalies[[c for c in cols if c != "positionCode"] + ["goalieFullName", "wins"]].rename(
            columns={"goalieFullName": "name"})
        g["positionCode"] = "G"
        g["role"] = "Goalie"
        frames.append(g)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    for c in ("birthCity", "birthStateProvinceCode", "birthCountryCode"):
        df[c] = df[c].fillna("").astype(str).str.strip()
    geo = load_geo_places(db_mtime_val).rename(
        columns={"city": "birthCity", "region": "birthStateProvinceCode", "country": "birthCountryCode"})
    for c in ("birthCity", "birthStateProvinceCode", "birthCountryCode"):
        geo[c] = geo[c].fillna("").astype(str)
    return df.merge(geo, on=["birthCity", "birthStateProvinceCode", "birthCountryCode"], how="left")


def search_players(query: str, season: int, db_mtime_val: float) -> pd.DataFrame:
    """Skaters and goalies whose name contains `query` (case-insensitive),
    for the Compare page's player pickers. Returns
    playerId/Name/Tm/role/positionCode — role is 'Skater' or 'Goalie'."""
    if not NHL_DB_PATH.exists() or not query.strip():
        return pd.DataFrame()
    like = f"%{query.strip()}%"
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            skaters = pd.read_sql(
                "SELECT playerId, skaterFullName AS Name, teamAbbrevs AS Tm, positionCode "
                "FROM skaters WHERE season = ? AND skaterFullName LIKE ? COLLATE NOCASE",
                conn, params=(season, like),
            )
            skaters["role"] = "Skater"
        except pd.errors.DatabaseError:
            skaters = pd.DataFrame()
        try:
            goalies = pd.read_sql(
                "SELECT playerId, goalieFullName AS Name, teamAbbrevs AS Tm FROM goalies "
                "WHERE season = ? AND goalieFullName LIKE ? COLLATE NOCASE",
                conn, params=(season, like),
            )
            goalies["role"] = "Goalie"
            goalies["positionCode"] = "G"
        except pd.errors.DatabaseError:
            goalies = pd.DataFrame()
    return pd.concat([skaters, goalies], ignore_index=True)


def search_players_all_seasons(query: str, db_mtime_val: float) -> pd.DataFrame:
    """Search skaters and goalies by name across every cached season (not
    just the current one) — used by the persistent sidebar search, so a
    player who's since retired or changed teams is still findable. One row
    per player: their most recent season and that season's team."""
    if not NHL_DB_PATH.exists() or not query.strip():
        return pd.DataFrame(columns=["playerId", "Name", "Tm", "role", "season"])
    like = f"%{query.strip()}%"
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            skaters = pd.read_sql(
                "SELECT playerId, skaterFullName AS Name, teamAbbrevs AS Tm, season FROM skaters "
                "WHERE skaterFullName LIKE ? COLLATE NOCASE",
                conn, params=(like,),
            )
            skaters["role"] = "Skater"
        except pd.errors.DatabaseError:
            skaters = pd.DataFrame()
        try:
            goalies = pd.read_sql(
                "SELECT playerId, goalieFullName AS Name, teamAbbrevs AS Tm, season FROM goalies "
                "WHERE goalieFullName LIKE ? COLLATE NOCASE",
                conn, params=(like,),
            )
            goalies["role"] = "Goalie"
        except pd.errors.DatabaseError:
            goalies = pd.DataFrame()
    combined = pd.concat([skaters, goalies], ignore_index=True)
    if combined.empty:
        return pd.DataFrame(columns=["playerId", "Name", "Tm", "role", "season"])
    # A skater/goalie has at most one row per season per table — keep the
    # most recent season's row per player (their current team of record).
    picked = combined.sort_values("season", ascending=False).drop_duplicates(subset="playerId", keep="first")
    return picked.sort_values("Name").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Live reads (api-web.nhle.com) — standings, scores/schedule, rosters, bios.
# Never stored in nhl.db: small payloads, already fast, and change in-season
# in ways nightly ingest would just make stale.
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=300, max_entries=4)
def load_standings(date_str: str = "now") -> pd.DataFrame:
    """League standings as of `date_str` ('now' for current/most-recent).
    One row per team with points, record splits, streak, and clinch status."""
    try:
        resp = requests.get(f"https://api-web.nhle.com/v1/standings/{date_str}", timeout=15, headers=_HEADERS)
        resp.raise_for_status()
        rows = resp.json().get("standings", [])
    except Exception:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in ("teamName", "teamCommonName", "placeName", "teamAbbrev"):
        if col in df.columns:
            df[col] = df[col].map(lambda v: v.get("default") if isinstance(v, dict) else v)
    return df


@st.cache_data(show_spinner=False, ttl=20, max_entries=8)
def load_schedule_for_date(date_str: str) -> list[dict]:
    """Every game on `date_str` (YYYY-MM-DD), with live score/state if in
    progress or final. Short TTL so a page left open during live games
    keeps moving."""
    try:
        resp = requests.get(f"https://api-web.nhle.com/v1/schedule/{date_str}", timeout=15, headers=_HEADERS)
        resp.raise_for_status()
        weeks = resp.json().get("gameWeek", [])
    except Exception:
        return []
    for day in weeks:
        if day.get("date") == date_str:
            return day.get("games", [])
    return []


@st.cache_data(show_spinner=False, ttl=300, max_entries=8)
def load_schedule_week(start: str = "now") -> dict:
    """One schedule 'week' as the NHL serves it: {'days': [{date, games}],
    'next': date, 'prev': date}. `start` is YYYY-MM-DD or 'now' (which the
    API resolves to the week containing the next game day — in the
    offseason that's opening week, so the page is never empty)."""
    try:
        resp = requests.get(f"https://api-web.nhle.com/v1/schedule/{start}", timeout=15, headers=_HEADERS)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return {"days": [], "next": None, "prev": None}
    return {
        "days": [{"date": d["date"], "games": d.get("games", [])} for d in payload.get("gameWeek", [])],
        "next": payload.get("nextStartDate"), "prev": payload.get("previousStartDate"),
    }


@st.cache_data(show_spinner=False, ttl=3600, max_entries=32)
def load_roster(team_abbr: str) -> dict:
    """Current roster for `team_abbr`: {'forwards': [...], 'defensemen': [...], 'goalies': [...]}."""
    try:
        resp = requests.get(
            f"https://api-web.nhle.com/v1/roster/{team_abbr}/current", timeout=15, headers=_HEADERS
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


@st.cache_data(show_spinner=False, ttl=3600, max_entries=64)
def load_player_landing(player_id: int) -> dict:
    """The NHL's own player-profile payload: headshot, bio, draft info,
    career/season totals (all leagues), awards, last-5-games log."""
    try:
        resp = requests.get(
            f"https://api-web.nhle.com/v1/player/{int(player_id)}/landing", timeout=15, headers=_HEADERS
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


# --- Per-game (Game Center) -----------------------------------------------
# Short TTLs so a live game keeps moving; finished games just re-fetch
# every 20s while someone is on the page, which is cheap.

def _get_json(url: str):
    try:
        resp = requests.get(url, timeout=15, headers=_HEADERS)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


@st.cache_data(show_spinner=False, ttl=20, max_entries=16)
def load_game_landing(game_id: int) -> dict:
    """Scoring summary (every goal with scorer/assists/strength/clip),
    penalties, three stars, live clock/period."""
    return _get_json(f"https://api-web.nhle.com/v1/gamecenter/{int(game_id)}/landing")


@st.cache_data(show_spinner=False, ttl=20, max_entries=16)
def load_game_boxscore(game_id: int) -> dict:
    """Per-player lines for both teams (forwards/defense/goalies)."""
    return _get_json(f"https://api-web.nhle.com/v1/gamecenter/{int(game_id)}/boxscore")


@st.cache_data(show_spinner=False, ttl=20, max_entries=16)
def load_game_shots(game_id: int) -> pd.DataFrame:
    """Every shot attempt in one game from play-by-play, coordinates
    normalized so each TEAM attacks its own end consistently: the home
    team always shoots toward +x, the away team toward -x (a game map wants
    the two teams on opposite ends, unlike the season shot map which folds
    everyone onto one end)."""
    data = _get_json(f"https://api-web.nhle.com/v1/gamecenter/{int(game_id)}/play-by-play")
    if not data:
        return pd.DataFrame()
    home_id = (data.get("homeTeam") or {}).get("id")
    names = {r["playerId"]: f"{r['firstName']['default']} {r['lastName']['default']}" for r in data.get("rosterSpots", [])}
    rows = []
    for p in data.get("plays", []):
        kind = p.get("typeDescKey")
        if kind not in ("goal", "shot-on-goal", "missed-shot", "blocked-shot"):
            continue
        d = p.get("details") or {}
        x, y = d.get("xCoord"), d.get("yCoord")
        if x is None or y is None:
            continue
        is_home = d.get("eventOwnerTeamId") == home_id
        side = p.get("homeTeamDefendingSide") or "left"
        # Home attacks the side it is NOT defending. Flip so home always -> +x.
        home_attacks_right = side == "left"
        if not home_attacks_right:
            x, y = -x, -y
        shooter = d.get("scoringPlayerId") or d.get("shootingPlayerId")
        rows.append({
            "period": (p.get("periodDescriptor") or {}).get("number"), "time": p.get("timeInPeriod"),
            "result": kind, "x": x, "y": y, "is_home": is_home, "shotType": d.get("shotType"),
            "shooter": names.get(shooter, ""), "shooterId": shooter,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Game-odds model (Elo, fit offline by ingest/nhl_elo.py -> elo_model.json).
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=3600, max_entries=1)
def load_elo_model() -> dict | None:
    if not ELO_MODEL_PATH.exists():
        return None
    return json.loads(ELO_MODEL_PATH.read_text())


def game_win_prob(home_abbr: str, away_abbr: str) -> float | None:
    """Pregame P(home team wins), from the fitted Elo model — None if the
    model hasn't been trained yet (see ingest/nhl_elo.py)."""
    model = load_elo_model()
    if not model:
        return None
    ratings = model["ratings"]
    elo_home = ratings.get(home_abbr, 1500.0)
    elo_away = ratings.get(away_abbr, 1500.0)
    return 1.0 / (1.0 + 10 ** ((elo_away - (elo_home + model["home_advantage"])) / 400))


# Display labels for the raw API column names.
STAT_LABELS = {
    "skaterFullName": "Name", "teamAbbrevs": "Tm", "positionCode": "Pos", "shootsCatches": "Shoots", "gamesPlayed": "GP",
    "goals": "G", "assists": "A", "points": "P", "pointsPerGame": "PPG", "plusMinus": "+/-",
    "penaltyMinutes": "PIM", "ppGoals": "PP G", "ppPoints": "PP P", "shGoals": "SH G", "shPoints": "SH P",
    "gameWinningGoals": "GWG", "otGoals": "OTG", "shots": "S", "shootingPct": "S%",
    "timeOnIcePerGame": "TOI/GP", "faceoffWinPct": "FO%",
    "ixG": "xG", "ixG_5v5": "xG 5v5", "ixG_high_danger": "HD xG", "high_danger_shots": "HD Shots",
    "xGF_pct_5v5": "xGF% 5v5", "xGF_pct_all": "xGF%", "office_xGF_pct": "Off-ice xGF%",
    "onice_xGF": "On-ice xGF", "onice_xGA": "On-ice xGA",
    "satPercentage": "CF%", "satRelative": "CF% Rel", "usatPercentage": "FF%", "usatRelative": "FF% Rel",
    "shootingPct5v5": "S% 5v5", "skaterSavePct5v5": "On-ice SV%", "skaterShootingPlusSavePct5v5": "PDO",
    "zoneStartPct5v5": "OZ Start%", "goalsPer605v5": "G/60", "assistsPer605v5": "A/60",
    "pointsPer605v5": "P/60", "primaryAssistsPer605v5": "A1/60", "secondaryAssistsPer605v5": "A2/60",
    "hits": "Hits", "blockedShots": "Blocks", "takeaways": "TK", "giveaways": "GV",
    "penaltiesDrawn": "Pen Drawn", "netPenaltiesPer60": "Net Pen/60",
    "ppAssists": "PPA", "ppShots": "PP Shots", "ppShootingPct": "PP S%", "ppGoalsPer60": "PPG/60",
    "ppPointsPer60": "PPP/60", "ppTimeOnIcePerGame": "PP TOI/GP", "ppTimeOnIcePctPerGame": "PP Share%",
    "shAssists": "SHA", "shPointsPer60": "SHP/60", "shTimeOnIcePerGame": "PK TOI/GP",
    "shTimeOnIcePctPerGame": "PK Share%", "ppGoalsAgainstPer60": "PPGA/60 (on PK)",
    "goalsWrist": "Wrist G", "goalsSnap": "Snap G", "goalsSlap": "Slap G", "goalsBackhand": "Backhand G",
    "goalsTipIn": "Tip G", "goalsDeflected": "Deflect G", "goalsWrapAround": "Wrap G",
    "shootingPctWrist": "Wrist S%", "shootingPctSnap": "Snap S%", "shootingPctSlap": "Slap S%",
    "shootingPctBackhand": "Backhand S%", "shootingPctTipIn": "Tip S%",
    "shotsOnNetWrist": "Wrist SOG", "shotsOnNetSnap": "Snap SOG", "shotsOnNetSlap": "Slap SOG",
    # Goalies
    "goalieFullName": "Name", "gamesStarted": "GS", "wins": "W", "losses": "L", "otLosses": "OTL",
    "goalsAgainst": "GA", "goalsAgainstAverage": "GAA", "shotsAgainst": "SA", "saves": "SV",
    "savePct": "SV%", "shutouts": "SO", "completeGames": "CG", "completeGamePct": "CG%",
    "incompleteGames": "ICG", "qualityStart": "QS", "qualityStartsPct": "QS%",
    "regulationWins": "Reg. W", "regulationLosses": "Reg. L", "goalsFor": "Team GF",
    "goalsForAverage": "Team GF/GP", "shotsAgainstPer60": "SA/60", "xGA": "xGA",
    "xGA_high_danger": "HD xGA", "xGA_5v5": "xGA 5v5", "gsax": "GSAx", "gsax5v5": "GSAx 5v5",
}
