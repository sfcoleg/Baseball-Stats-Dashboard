"""NBA team metadata. nba_api's static team list (id/name/abbreviation/
city/state/year_founded — confirmed directly, 30 rows) carries no colour
data, so colours are kept here as a small dictionary — the same choice
app/nhl/teams.py made and for the same reason: the upstream source simply
doesn't have it, so there is nothing to keep in sync with by reading it
from the API instead."""
import sqlite3
from functools import lru_cache
from pathlib import Path

NBA_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "nba.db"

# Primary brand colour per team, by abbreviation.
TEAM_COLORS = {
    "ATL": "#E03A3E", "BOS": "#007A33", "BKN": "#000000", "CHA": "#1D1160",
    "CHI": "#CE1141", "CLE": "#860038", "DAL": "#00538C", "DEN": "#0E2240",
    "DET": "#C8102E", "GSW": "#1D428A", "HOU": "#CE1141", "IND": "#002D62",
    "LAC": "#C8102E", "LAL": "#552583", "MEM": "#5D76A9", "MIA": "#98002E",
    "MIL": "#00471B", "MIN": "#0C2340", "NOP": "#0C2340", "NYK": "#006BB6",
    "OKC": "#007AC1", "ORL": "#0077C0", "PHI": "#006BB6", "PHX": "#1D1160",
    "POR": "#E03A3E", "SAC": "#5A2D81", "SAS": "#C4CED4", "TOR": "#CE1141",
    "UTA": "#002B5C", "WAS": "#002B5C",
}


@lru_cache(maxsize=1)
def _table() -> dict:
    if not NBA_DB_PATH.exists():
        return {}
    try:
        with sqlite3.connect(NBA_DB_PATH) as conn:
            rows = conn.execute(
                "SELECT team_id, full_name, abbreviation, nickname, city FROM teams"
            ).fetchall()
    except sqlite3.Error:
        return {}
    return {
        r[2]: {"team_id": r[0], "full_name": r[1], "nickname": r[3], "city": r[4]}
        for r in rows
    }


def color_for_abbr(abbr: str) -> str:
    return TEAM_COLORS.get(abbr, "#666666")


def name_for_abbr(abbr: str) -> str:
    return _table().get(abbr, {}).get("full_name") or abbr


def nickname_for_abbr(abbr: str) -> str:
    return _table().get(abbr, {}).get("nickname") or abbr


def all_teams() -> list[tuple[str, str]]:
    """(abbr, nickname) for the 30 clubs, sorted."""
    return sorted((abbr, info["nickname"] or abbr) for abbr, info in _table().items())
