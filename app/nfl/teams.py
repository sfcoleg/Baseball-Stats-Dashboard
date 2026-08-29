"""NFL team metadata, read from nfl.db's `teams` table rather than hardcoded.

The NHL module keeps its own dictionary because the NHL API returns team
identity per-request; nflverse ships a proper teams table with colours,
divisions and logo URLs, so copying it into Python would just be a second
copy to keep in sync. Cached for the process, since it changes about once a
decade."""
import sqlite3
from functools import lru_cache
from pathlib import Path

NFL_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "nfl.db"

# nflverse carries historical abbreviations alongside current ones (36 rows
# for 32 clubs). These are the retired ones — kept out of pickers so a user
# can't follow a team that no longer plays, but still resolvable for colours
# on an old season's game.
LEGACY_ABBRS = {"OAK", "SD", "STL", "LAR"}


@lru_cache(maxsize=1)
def _table() -> dict:
    """abbr -> dict of name/nickname/conference/division/colour/logo."""
    if not NFL_DB_PATH.exists():
        return {}
    try:
        with sqlite3.connect(NFL_DB_PATH) as conn:
            rows = conn.execute(
                "SELECT team_abbr, team_name, team_nick, team_conf, team_division, "
                "team_color, team_color2, team_logo_espn FROM teams"
            ).fetchall()
    except sqlite3.Error:
        return {}
    return {
        r[0]: {"name": r[1], "nick": r[2], "conf": r[3], "division": r[4],
               "color": r[5] or "#666666", "color2": r[6], "logo": r[7]}
        for r in rows
    }


def color_for_abbr(abbr: str) -> str:
    return _table().get(abbr, {}).get("color") or "#666666"


def conference_for_abbr(abbr: str) -> str:
    """"AFC" or "NFC" — used to badge the two participants in a Super Bowl,
    which is the one game where the conferences are the point."""
    return _table().get(abbr, {}).get("conf") or ""


def nickname_for_abbr(abbr: str) -> str:
    return _table().get(abbr, {}).get("nick") or abbr


def name_for_abbr(abbr: str) -> str:
    return _table().get(abbr, {}).get("name") or abbr


def logo_url(abbr: str) -> str:
    return _table().get(abbr, {}).get("logo") or ""


def division_for_abbr(abbr: str) -> str:
    return _table().get(abbr, {}).get("division") or ""


def all_teams() -> list[tuple[str, str]]:
    """(abbr, nickname) for the 32 current clubs, sorted — retired
    abbreviations excluded so they can't be picked."""
    return sorted(
        (abbr, info["nick"] or abbr)
        for abbr, info in _table().items()
        if abbr not in LEGACY_ABBRS
    )
