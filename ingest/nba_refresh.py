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


def fetch_player_stats(season: str) -> pd.DataFrame:
    """Season-long player stats, confirmed directly against live 2025-26
    data before writing this: 582 players, PTS/REB/AST/etc. as SEASON
    TOTALS (Dončić's 2143 points, not 33.5) — per-game rates are computed
    here rather than assumed, since a raw total is not what a leaderboard
    should sort or display by."""
    from nba_api.stats.endpoints import leaguedashplayerstats
    df = leaguedashplayerstats.LeagueDashPlayerStats(season=season).get_data_frames()[0]
    if df.empty:
        return df
    per_game = ["PTS", "REB", "AST", "STL", "BLK", "TOV", "MIN"]
    for col in per_game:
        if col in df.columns:
            df[f"{col}_PG"] = df[col] / df["GP"].replace(0, pd.NA)
    df["season"] = season
    return df


def fetch_roster(team_id: int, season: str) -> pd.DataFrame:
    """One team's roster, confirmed directly against Boston's real 2025-26
    roster before writing this: PLAYER/NUM/POSITION/HEIGHT/WEIGHT/AGE/EXP
    all come back as expected, no assumed columns."""
    from nba_api.stats.endpoints import commonteamroster
    df = commonteamroster.CommonTeamRoster(team_id=team_id, season=season).get_data_frames()[0]
    if df.empty:
        return df
    return df[["TeamID", "PLAYER", "PLAYER_ID", "NUM", "POSITION", "HEIGHT", "WEIGHT", "AGE", "EXP"]]


def fetch_all_rosters(teams: pd.DataFrame, season: str) -> pd.DataFrame:
    """Every team's roster for `season`, one call per team (nba_api has no
    league-wide roster endpoint) — 30 requests, spaced out the same way the
    other ingests here space out theirs, since this is the same
    stats.nba.com host as everything above."""
    frames = []
    for i, team_id in enumerate(teams["team_id"]):
        try:
            df = fetch_roster(int(team_id), season)
            if not df.empty:
                frames.append(df)
        except Exception as e:
            print(f"  roster fetch failed for team {team_id} ({e})", flush=True)
        if i < len(teams) - 1:
            time.sleep(0.6)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


SCOREBOARD_COLS = [
    "game_id", "game_status", "game_status_text", "game_et",
    "home_team_id", "home_abbr", "home_score", "home_wins", "home_losses",
    "away_team_id", "away_abbr", "away_score", "away_wins", "away_losses",
]


def fetch_scoreboard(date_str: str) -> pd.DataFrame:
    """Today's games with real scores. Genuinely empty outside the season
    (verified: the September offseason returns zero rows, not an error) —
    return an empty, correctly-shaped frame rather than letting that
    surprise a caller expecting a schedule.

    ScoreboardV3, not V2, per nba_api's own deprecation warning on V2: its
    line score data is known-broken for 2025-26 games between Oct 22 and
    Dec 25, 2025 (https://github.com/swar/nba_api/issues/596). V3 also
    nests home/away as named objects (homeTeam/awayTeam) with a direct
    `score` field, rather than V2's flat per-quarter columns that need
    summing and a fragile guess at which row is home vs away — read via get_dict()
    since get_data_frames() flattens that structure away. A `timeout` is
    passed explicitly: without one, this call has hung indefinitely on
    this host at least once with zero network activity, for reasons never
    pinned down — better to fail fast and treat it as no games than hang
    the whole daily refresh."""
    from nba_api.stats.endpoints import scoreboardv3
    try:
        sb = scoreboardv3.ScoreboardV3(game_date=date_str, timeout=20)
        games = sb.get_dict()["scoreboard"]["games"]
    except Exception as e:
        print(f"  scoreboard fetch failed ({e}) — treating as no games", flush=True)
        return pd.DataFrame(columns=SCOREBOARD_COLS)
    if not games:
        return pd.DataFrame(columns=SCOREBOARD_COLS)
    rows = []
    for g in games:
        home, away = g.get("homeTeam") or {}, g.get("awayTeam") or {}
        rows.append({
            "game_id": g.get("gameId"), "game_status": g.get("gameStatus"),
            "game_status_text": g.get("gameStatusText"), "game_et": g.get("gameEt"),
            "home_team_id": home.get("teamId"), "home_abbr": home.get("teamTricode"),
            "home_score": home.get("score"), "home_wins": home.get("wins"), "home_losses": home.get("losses"),
            "away_team_id": away.get("teamId"), "away_abbr": away.get("teamTricode"),
            "away_score": away.get("score"), "away_wins": away.get("wins"), "away_losses": away.get("losses"),
        })
    return pd.DataFrame(rows, columns=SCOREBOARD_COLS)


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
    time.sleep(1)

    # The new season exists but is empty until tip-off (verified: 2026-27
    # standings are real rows, all 0-0). A player-stats page needs actual
    # games played, so pull the CURRENT season and, when that comes back
    # empty, fall back one year — the same gap NFL's default_season()
    # already handles, applied here at ingest time instead of query time
    # since NBA has no history table yet to fall back within.
    player_stats = fetch_player_stats(season)
    stats_season = season
    if player_stats.empty:
        prior_start = int(season[:4]) - 1
        stats_season = f"{prior_start}-{str(prior_start + 1)[-2:]}"
        print(f"  {season} has no player games yet — falling back to {stats_season}", flush=True)
        time.sleep(1)
        player_stats = fetch_player_stats(stats_season)
    print(f"player stats ({stats_season}): {len(player_stats)} players", flush=True)

    # Rosters use the CURRENT season, not stats_season — a roster is "who
    # plays here now", and that's real even in the preseason. Confirmed
    # directly: Boston's 2026-27 roster already reflects a real trade
    # (Mitchell Robinson now on the team, Vučević gone) that hadn't
    # happened yet in the 2025-26 stats data. Team page joins this against
    # player_stats, so anyone new shows real bio info with stats blank
    # rather than last year's numbers under the wrong team.
    print(f"=== fetching rosters for {season} ===", flush=True)
    rosters = fetch_all_rosters(teams, season)
    rosters["season"] = season if not rosters.empty else None
    print(f"rosters: {len(rosters)} players across {rosters['TeamID'].nunique() if not rosters.empty else 0} teams",
          flush=True)

    with sqlite3.connect(DB_PATH) as conn:
        _store(conn, "teams", teams)
        if not standings.empty:
            _store(conn, "standings", standings)
        _store(conn, "todays_games", games)
        if not player_stats.empty:
            _store(conn, "player_stats", player_stats)
        if not rosters.empty:
            _store(conn, "roster", rosters)
        conn.commit()
    print(f"wrote {DB_PATH}", flush=True)
    print("DONE", flush=True)
