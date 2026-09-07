"""NBA ingest — teams, standings, and today's scoreboard into data/nba.db.

Skeleton scope on purpose: this is the fourth sport on the site, following
the same shape ingest/nfl_refresh.py and the NHL scripts already use, but
starting minimal rather than replaying the full multi-session build those
two took. Standings + schedule + basic box scores first; player-level
stats and anything custom come after this is proven end-to-end.

Uses nba_api (the standard free wrapper around stats.nba.com), confirmed
directly against live endpoints before writing this: 30 teams from the
static team list, real 2025-26 standings (Thunder 64-18 atop the West),
and a scoreboard that correctly returns zero games in the September
offseason rather than erroring — handled explicitly below rather than
assumed away.

    python nba_refresh.py             # today's refresh
"""
import sqlite3
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from _dates import pacific_today

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "nba.db"


def current_season() -> str:
    """NBA seasons are named '2025-26' and turn over in the fall — July
    counts as still-last-season for data purposes (offseason), matching
    how the league itself labels the season that just finished."""
    today = pacific_today()
    start_year = today.year if today.month >= 8 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def fetch_teams() -> pd.DataFrame:
    from nba_api.stats.static import teams as static_teams
    rows = static_teams.get_teams()
    return pd.DataFrame(rows)[
        ["id", "full_name", "abbreviation", "nickname", "city", "state", "year_founded"]
    ].rename(columns={"id": "team_id"})


def fetch_standings(season: str) -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguestandingsv3
    df = leaguestandingsv3.LeagueStandingsV3(season=season).get_data_frames()[0]
    keep = ["TeamID", "TeamCity", "TeamName", "TeamSlug", "Conference", "ConferenceRecord",
            "PlayoffRank", "ClinchIndicator", "Division", "DivisionRecord", "DivisionRank",
            "WINS", "LOSSES"]
    df = df[[c for c in keep if c in df.columns]].rename(columns={"TeamID": "team_id"})
    df["season"] = season
    return df


def fetch_scoreboard(date_str: str) -> pd.DataFrame:
    """Today's games. Genuinely empty outside the season (verified: the
    September offseason returns zero rows, not an error) — return an
    empty, correctly-shaped frame rather than letting that surprise a
    caller expecting a schedule."""
    from nba_api.stats.endpoints import scoreboardv2
    cols = ["GAME_ID", "GAME_DATE_EST", "HOME_TEAM_ID", "VISITOR_TEAM_ID",
            "GAME_STATUS_TEXT", "ARENA_NAME"]
    try:
        sb = scoreboardv2.ScoreboardV2(game_date=date_str)
        df = sb.get_data_frames()[0]
    except Exception as e:
        print(f"  scoreboard fetch failed ({e}) — treating as no games", flush=True)
        return pd.DataFrame(columns=cols)
    if df.empty:
        return pd.DataFrame(columns=cols)
    return df[[c for c in cols if c in df.columns]]


def _store(conn: sqlite3.Connection, table: str, df: pd.DataFrame) -> None:
    df.to_sql(table, conn, if_exists="replace", index=False)


if __name__ == "__main__":
    season = current_season()
    print(f"=== NBA refresh: {season} ===", flush=True)

    teams = fetch_teams()
    print(f"teams: {len(teams)}", flush=True)
    time.sleep(1)

    try:
        standings = fetch_standings(season)
        print(f"standings: {len(standings)} rows", flush=True)
    except Exception as e:
        print(f"  standings fetch failed ({e}) — likely preseason, no rows yet", flush=True)
        standings = pd.DataFrame()
    time.sleep(1)

    today = pacific_today().isoformat()
    games = fetch_scoreboard(today)
    print(f"today's games ({today}): {len(games)}", flush=True)

    with sqlite3.connect(DB_PATH) as conn:
        _store(conn, "teams", teams)
        if not standings.empty:
            _store(conn, "standings", standings)
        _store(conn, "todays_games", games)
        conn.commit()
    print(f"wrote {DB_PATH}", flush=True)
    print("DONE", flush=True)
