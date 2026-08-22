"""NHL data layer — readers over data/nhl.db (built by ingest/nhl_refresh.py).
Deliberately separate from the MLB db module: different database file,
different tables, independent refresh."""
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

NHL_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "nhl.db"


def nhl_db_mtime() -> float:
    return NHL_DB_PATH.stat().st_mtime if NHL_DB_PATH.exists() else 0.0


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


def season_label(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"


# Display labels for the raw API column names.
STAT_LABELS = {
    "skaterFullName": "Name", "teamAbbrevs": "Tm", "positionCode": "Pos", "gamesPlayed": "GP",
    "goals": "G", "assists": "A", "points": "P", "pointsPerGame": "PPG", "plusMinus": "+/-",
    "penaltyMinutes": "PIM", "ppGoals": "PP G", "ppPoints": "PP P", "shGoals": "SH G", "shPoints": "SH P",
    "gameWinningGoals": "GWG", "otGoals": "OTG", "shots": "S", "shootingPct": "S%",
    "timeOnIcePerGame": "TOI/GP", "faceoffWinPct": "FO%",
    "ixG": "ixG", "ixG_5v5": "ixG 5v5", "ixG_high_danger": "HD ixG", "high_danger_shots": "HD Shots",
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
}
