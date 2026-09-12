"""NBA data layer — readers over data/nba.db (built by ingest/nba_refresh.py).

Mirrors app/nfl/db.py and app/nhl/db.py in shape: cache on the database's
mtime so a refresh invalidates everything at once, return plain
DataFrames, and the pages style them with the shared helpers in
app/style.py. Skeleton scope — teams, standings, today's games — matching
where NFL/NHL started rather than their current full build."""
import sqlite3
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

NBA_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "nba.db"


def nba_db_mtime() -> float:
    return NBA_DB_PATH.stat().st_mtime if NBA_DB_PATH.exists() else 0.0


def today_pacific() -> date:
    """Same single source of truth as the other sports — see db.today_pacific."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).date()


def current_season_label() -> str:
    """'2025-26' style label for the season currently in progress or about
    to start. NBA seasons turn over in the fall; August counts as the new
    season for labeling purposes even before tip-off, matching the
    ingest's own current_season()."""
    today = today_pacific()
    start_year = today.year if today.month >= 8 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _read(query: str, params: tuple = ()) -> pd.DataFrame:
    if not NBA_DB_PATH.exists():
        return pd.DataFrame()
    try:
        with sqlite3.connect(NBA_DB_PATH) as conn:
            return pd.read_sql(query, conn, params=params)
    except (sqlite3.Error, pd.errors.DatabaseError):
        return pd.DataFrame()


@st.cache_data(show_spinner=False, max_entries=2)
def load_teams(db_mtime_val: float) -> pd.DataFrame:
    return _read("SELECT * FROM teams")


@st.cache_data(show_spinner=False, max_entries=4)
def load_standings(db_mtime_val: float) -> pd.DataFrame:
    """Whatever season is in the table — there is only ever one, since the
    ingest replaces it wholesale each run rather than keying by season."""
    df = _read("SELECT * FROM standings")
    if df.empty:
        return df
    return df.sort_values(["Conference", "PlayoffRank"])


@st.cache_data(show_spinner=False, max_entries=2)
def standings_are_preseason(db_mtime_val: float) -> bool:
    """True when the loaded standings are the season's real, current state
    but everyone is 0-0 — the offseason/preseason case, confirmed directly
    against the live API rather than assumed: on 2026-09-06 (before the
    2026-27 season's tip-off) every one of the 30 real standings rows came
    back WINS=0, LOSSES=0. Not missing data, just nothing played yet — the
    page should say that plainly instead of showing an all-zero table with
    no explanation."""
    df = load_standings(db_mtime_val)
    if df.empty or "WINS" not in df.columns:
        return False
    return bool((df["WINS"] == 0).all() and (df["LOSSES"] == 0).all())


@st.cache_data(show_spinner=False, max_entries=2)
def load_todays_games(db_mtime_val: float) -> pd.DataFrame:
    return _read("SELECT * FROM todays_games")


MIN_GAMES = 20  # rough qualifying floor for a per-game leaderboard


@st.cache_data(show_spinner=False, max_entries=4)
def load_player_stats(db_mtime_val: float) -> pd.DataFrame:
    """Whatever season is in the table — ingest already resolved which one
    that is (current if it has games, else the prior completed season), so
    this is a straight read, no fallback logic duplicated here."""
    return _read("SELECT * FROM player_stats")


@st.cache_data(show_spinner=False, max_entries=2)
def player_stats_season(db_mtime_val: float) -> str | None:
    df = load_player_stats(db_mtime_val)
    if df.empty or "season" not in df.columns:
        return None
    return str(df["season"].iloc[0])


def qualified_players(df: pd.DataFrame, min_games: int = MIN_GAMES) -> pd.DataFrame:
    if df.empty or "GP" not in df.columns:
        return df
    return df[df["GP"] >= min_games]


@st.cache_data(show_spinner=False, max_entries=2)
def load_roster(team_id: int, db_mtime_val: float) -> pd.DataFrame:
    return _read("SELECT * FROM roster WHERE TeamID = ?", (int(team_id),))


def team_abbr_map(db_mtime_val: float) -> dict[int, str]:
    teams = load_teams(db_mtime_val)
    if teams.empty:
        return {}
    return dict(zip(teams["team_id"], teams["abbreviation"]))


def search_players(query: str, db_mtime_val: float) -> pd.DataFrame:
    """Name search over the ingested player_stats table — one row per
    player, same shape as nfl.db.search_players, so sidebar.py's search
    pattern drops in unchanged."""
    if not query.strip():
        return pd.DataFrame()
    return _read(
        "SELECT PLAYER_ID, PLAYER_NAME, TEAM_ABBREVIATION FROM player_stats "
        "WHERE PLAYER_NAME LIKE ? COLLATE NOCASE ORDER BY PLAYER_NAME",
        (f"%{query.strip()}%",),
    )


@st.cache_data(show_spinner=False, max_entries=32)
def load_player_season(player_id: int, db_mtime_val: float) -> dict | None:
    df = _read("SELECT * FROM player_stats WHERE PLAYER_ID = ?", (int(player_id),))
    return df.iloc[0].to_dict() if not df.empty else None


@st.cache_data(show_spinner=False, max_entries=32)
def load_player_bio(player_id: int, db_mtime_val: float) -> dict | None:
    """Roster row for whichever team currently has this player — rosters
    are keyed by TeamID, not PLAYER_ID alone, but a player is only ever on
    one team's current roster at a time so a plain match is unambiguous."""
    df = _read("SELECT * FROM roster WHERE PLAYER_ID = ?", (int(player_id),))
    return df.iloc[0].to_dict() if not df.empty else None


@st.cache_data(show_spinner=False, ttl=1800, max_entries=64)
def load_player_gamelog(player_id: int, season: str) -> pd.DataFrame:
    """Recent games for one player, fetched live from stats.nba.com rather
    than ingested daily for every player — game logs are only ever looked
    at for the handful of players someone actually opens. 30-minute TTL:
    long enough that browsing around doesn't refire it, short enough that
    last night's game shows up without a manual refresh."""
    try:
        from nba_api.stats.endpoints import playergamelog
        df = playergamelog.PlayerGameLog(player_id=int(player_id), season=season).get_data_frames()[0]
    except Exception:
        return pd.DataFrame()
    return df
