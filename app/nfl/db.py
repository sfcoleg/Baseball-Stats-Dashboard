"""NFL data layer — readers over data/nfl.db (built by ingest/nfl_refresh.py).

Mirrors app/nhl/db.py in shape: cache on the database's mtime so a refresh
invalidates everything at once, and return plain DataFrames the pages can
style with the shared helpers in app/style.py."""
import sqlite3
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

NFL_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "nfl.db"

GAME_TYPE_LABELS = {
    "REG": "Regular season", "WC": "Wild Card", "DIV": "Divisional",
    "CON": "Conference Championship", "SB": "Super Bowl",
}


def nfl_db_mtime() -> float:
    return NFL_DB_PATH.stat().st_mtime if NFL_DB_PATH.exists() else 0.0


def today_pacific() -> date:
    """Same single source of truth for "what day is it" as the other sports —
    see db.today_pacific for why Pacific rather than the server's UTC."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).date()


def season_label(season: int) -> str:
    """An NFL season spans two calendar years and is named for the first."""
    return f"{season}-{str(season + 1)[-2:]}"


def _read(query: str, params: tuple = ()) -> pd.DataFrame:
    if not NFL_DB_PATH.exists():
        return pd.DataFrame()
    try:
        with sqlite3.connect(NFL_DB_PATH) as conn:
            return pd.read_sql(query, conn, params=params)
    except (sqlite3.Error, pd.errors.DatabaseError):
        return pd.DataFrame()


@st.cache_data(show_spinner=False, max_entries=2)
def seasons(db_mtime_val: float) -> list[int]:
    """Newest first, so a season picker defaults to the current one."""
    df = _read("SELECT DISTINCT season FROM games ORDER BY season DESC")
    return df["season"].astype(int).tolist() if not df.empty else []


@st.cache_data(show_spinner=False, max_entries=2)
def default_season(db_mtime_val: float) -> int | None:
    """The season a picker should open on: the newest one with a played game.

    The NFL schedule is published in May, so from spring until September the
    newest season exists but is entirely unplayed — opening there shows an
    empty page on every tab. This falls forward to the last season with
    results, and switches to the new one as soon as it kicks off."""
    played = _read(
        "SELECT MAX(season) FROM games WHERE home_score IS NOT NULL"
    )
    if not played.empty and pd.notna(played.iloc[0, 0]):
        return int(played.iloc[0, 0])
    latest = _read("SELECT MAX(season) FROM games")
    if not latest.empty and pd.notna(latest.iloc[0, 0]):
        return int(latest.iloc[0, 0])
    return None


def season_index(season_list: list[int], db_mtime_val: float) -> int:
    """Index of default_season within `season_list`, for selectbox(index=)."""
    target = default_season(db_mtime_val)
    return season_list.index(target) if target in season_list else 0


@st.cache_data(show_spinner=False, max_entries=8)
def load_standings(season: int, db_mtime_val: float) -> pd.DataFrame:
    """Regular-season records for one season, already ordered the way a
    standings table reads: best first."""
    df = _read("SELECT * FROM standings WHERE season = ?", (int(season),))
    if df.empty:
        return df
    return df.sort_values(["win_pct", "point_diff"], ascending=False).reset_index(drop=True)


@st.cache_data(show_spinner=False, max_entries=8)
def load_games(season: int, db_mtime_val: float) -> pd.DataFrame:
    df = _read("SELECT * FROM games WHERE season = ? ORDER BY week, gameday, gametime", (int(season),))
    if df.empty:
        return df
    df["played"] = df["home_score"].notna() & df["away_score"].notna()
    return df


@st.cache_data(show_spinner=False, max_entries=8)
def load_team_weeks(season: int, db_mtime_val: float) -> pd.DataFrame:
    """Per-team, per-week totals including EPA — empty for a season whose
    stats file nflverse has not published yet (the upcoming one, all
    summer)."""
    return _read("SELECT * FROM team_week_stats WHERE season = ?", (int(season),))


def current_week(games: pd.DataFrame) -> int | None:
    """The week the season is actually on: the earliest week with an unplayed
    game, or the last week once everything has been played. Derived from
    results rather than from the calendar, so a postponed game keeps the site
    on the right week."""
    if games.empty:
        return None
    pending = games[~games["played"]]
    if not pending.empty:
        return int(pending["week"].min())
    return int(games["week"].max())


def team_schedule(games: pd.DataFrame, abbr: str) -> pd.DataFrame:
    """One team's season, with the view flipped to that team: who they played,
    whether it was home, and the result from their side."""
    own = games[(games["home_team"] == abbr) | (games["away_team"] == abbr)].copy()
    if own.empty:
        return own
    at_home = own["home_team"] == abbr
    own["is_home"] = at_home
    own["opponent"] = own["away_team"].where(at_home, own["home_team"])
    own["points_for"] = own["home_score"].where(at_home, own["away_score"])
    own["points_against"] = own["away_score"].where(at_home, own["home_score"])
    own["result"] = pd.NA
    decided = own["played"]
    own.loc[decided & (own["points_for"] > own["points_against"]), "result"] = "W"
    own.loc[decided & (own["points_for"] < own["points_against"]), "result"] = "L"
    own.loc[decided & (own["points_for"] == own["points_against"]), "result"] = "T"
    return own


def record_string(row) -> str:
    """"12-5" or "12-4-1" — ties are only shown when there are any, which is
    how the NFL writes it."""
    ties = int(row.get("ties") or 0)
    base = f"{int(row['wins'])}-{int(row['losses'])}"
    return f"{base}-{ties}" if ties else base
