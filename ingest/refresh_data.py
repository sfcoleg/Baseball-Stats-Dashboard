"""
Fetches current-season MLB stats from Baseball-Reference and Baseball Savant
(Statcast) via pybaseball, computes additional sabermetrics, and saves
everything into a local SQLite database (data/stats.db).

Note: we use Baseball-Reference (*_bref) rather than FanGraphs for base
batting/pitching stats, because FanGraphs currently blocks pybaseball's
requests (403 errors from their bot protection). Baseball-Reference and
Baseball Savant (Statcast) both work reliably.

Run this once a day to keep the dashboard up to date:
    ./venv/bin/python ingest/refresh_data.py
"""
import codecs
import io
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
from pybaseball import (
    batting_stats_bref,
    pitching_stats_bref,
    batting_stats_range,
    pitching_stats_range,
    statcast_batter_exitvelo_barrels,
    statcast_batter_expected_stats,
    statcast_pitcher_exitvelo_barrels,
    statcast_pitcher_expected_stats,
    statcast_outs_above_average,
    statcast_sprint_speed,
)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "stats.db"
CURRENT_SEASON = date.today().year

# app/teams.py's nickname->abbreviation lookup, reused here so standings
# rows get a team_abbr without duplicating the mapping.
sys.path.append(str(Path(__file__).resolve().parent.parent / "app"))
import teams as app_teams  # noqa: E402

# MLB Stats API division IDs -> readable names (not included as a plain
# string in the standings payload, only as a numeric id).
DIVISION_NAMES = {
    200: "AL West", 201: "AL East", 202: "AL Central",
    203: "NL West", 204: "NL East", 205: "NL Central",
}

# Minimum plate appearances / innings pitched required to qualify as a
# "headliner" for each recent-performance window (keeps tiny-sample noise
# out of the day window in particular).
RECENT_MIN_PA = {"day": 3, "week": 15, "month": 50}
RECENT_MIN_IP = {"day": 1, "week": 8, "month": 20}

# wOBA linear weights (~2023-2024 era constants); used only as a fallback
# where Statcast's actual wOBA isn't available for a player.
WOBA_WEIGHTS = dict(bb=0.696, hbp=0.726, single=0.883, double=1.244, triple=1.569, hr=2.004)

_MOJIBAKE_RE = re.compile(r"(?:\\x[0-9a-fA-F]{2})+")


def fix_mojibake_names(series):
    """Baseball-Reference's scraped tables sometimes render accented names
    (Acuña, Hernández, ...) as literal '\\xNN' escape text instead of the
    actual character. Decode those runs back to real UTF-8 text."""

    def fix_one(name):
        if not isinstance(name, str):
            return name
        name = name.replace("\\'", "'")
        if not _MOJIBAKE_RE.search(name):
            return name
        try:
            return codecs.decode(name, "unicode_escape").encode("latin1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return name

    return series.map(fix_one)


def add_batting_sabermetrics(df):
    singles = df["H"] - df["2B"] - df["3B"] - df["HR"]
    ab_bb_sf_hbp = df["AB"] + df["BB"] - df["IBB"] + df["SF"] + df["HBP"]

    df["ISO"] = df["SLG"] - df["BA"]
    babip_denom = (df["AB"] - df["SO"] - df["HR"] + df["SF"]).replace(0, float("nan"))
    df["BABIP"] = ((df["H"] - df["HR"]) / babip_denom).round(3)
    df["K_PCT"] = (df["SO"] / df["PA"] * 100).round(1)
    df["BB_PCT"] = (df["BB"] / df["PA"] * 100).round(1)
    woba_denom = ab_bb_sf_hbp.replace(0, float("nan"))
    df["wOBA_calc"] = (
        (
            WOBA_WEIGHTS["bb"] * (df["BB"] - df["IBB"])
            + WOBA_WEIGHTS["hbp"] * df["HBP"]
            + WOBA_WEIGHTS["single"] * singles
            + WOBA_WEIGHTS["double"] * df["2B"]
            + WOBA_WEIGHTS["triple"] * df["3B"]
            + WOBA_WEIGHTS["hr"] * df["HR"]
        )
        / woba_denom
    ).round(3)
    return df


def add_pitching_sabermetrics(df):
    fip_constant = 3.10
    df["K_9"] = (df["SO"] * 9 / df["IP"]).round(2)
    df["BB_9"] = (df["BB"] * 9 / df["IP"]).round(2)
    df["K_BB"] = (df["SO"] / df["BB"].replace(0, float("nan"))).round(2)
    df["FIP"] = (
        (13 * df["HR"] + 3 * (df["BB"] + df["HBP"]) - 2 * df["SO"]) / df["IP"] + fip_constant
    ).round(2)
    return df


def fetch_savant_leaderboard_csv(path, year):
    """Fetch a Baseball Savant leaderboard CSV directly — some leaderboards
    (e.g. baserunning run value) aren't wrapped by pybaseball, but follow
    the same csv=true convention as the ones that are."""
    url = f"https://baseballsavant.mlb.com/leaderboard/{path}?year={year}&csv=true"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.content.decode("utf-8")))


def fetch_batting(season=CURRENT_SEASON):
    print(f"Fetching {season} batting stats (Baseball-Reference)...")
    batting = batting_stats_bref(season)
    batting["Name"] = fix_mojibake_names(batting["Name"])
    batting = add_batting_sabermetrics(batting)

    print(f"Fetching {season} Statcast batted-ball data (batters)...")
    exitvelo = statcast_batter_exitvelo_barrels(season, minBBE=1)[
        ["player_id", "avg_hit_speed", "max_hit_speed", "ev95percent", "brl_percent"]
    ].rename(columns={
        "avg_hit_speed": "avg_exit_velo",
        "max_hit_speed": "max_exit_velo",
        "ev95percent": "hard_hit_pct",
        "brl_percent": "barrel_pct",
    })

    print(f"Fetching {season} Statcast expected stats (batters)...")
    expected = statcast_batter_expected_stats(season, minPA=1)[
        ["player_id", "woba", "est_woba", "est_ba", "est_slg"]
    ].rename(columns={
        "woba": "wOBA",
        "est_woba": "xwOBA",
        "est_ba": "xBA",
        "est_slg": "xSLG",
    })

    print(f"Fetching {season} Statcast sprint speed...")
    sprint = statcast_sprint_speed(season, min_opp=1)[
        ["player_id", "sprint_speed", "hp_to_1b"]
    ]

    # Unlike sprint_speed, Baseball Savant's baserunning-run-value leaderboard
    # ignores the year param entirely and always returns the CURRENT season
    # (verified: requesting year=2022 and year=2026 return identical rows,
    # both stamped start_year/end_year=2026) — there's no historical query
    # available through this endpoint. Only fetch it when actually backfilling
    # the current season; a historical season gets an all-NaN column instead
    # of silently-wrong current-season values.
    if season == CURRENT_SEASON:
        print(f"Fetching {season} Statcast baserunning run value...")
        baserunning_value = fetch_savant_leaderboard_csv("baserunning-run-value", season)[
            ["player_id", "runner_runs_tot"]
        ].rename(columns={"runner_runs_tot": "baserunning_runs"})
    else:
        baserunning_value = pd.DataFrame({"player_id": pd.Series(dtype="float64"), "baserunning_runs": pd.Series(dtype="float64")})

    batting["mlbID"] = pd.to_numeric(batting["mlbID"], errors="coerce")
    for stats_df in (exitvelo, expected, sprint, baserunning_value):
        batting = batting.merge(stats_df, left_on="mlbID", right_on="player_id", how="left")
        batting = batting.drop(columns="player_id")

    batting["season"] = season
    return batting


def fetch_pitching(season=CURRENT_SEASON):
    print(f"Fetching {season} pitching stats (Baseball-Reference)...")
    pitching = pitching_stats_bref(season)
    pitching["Name"] = fix_mojibake_names(pitching["Name"])
    # Baseball-Reference leaves W/L/SV blank instead of 0 when a pitcher has
    # no decisions/saves, which pandas reads in as NaN ("None" in the UI).
    pitching[["W", "L", "SV"]] = pitching[["W", "L", "SV"]].fillna(0).astype(int)
    # "GB/FB" has a slash, which is awkward as a bare column name elsewhere
    # (SQL, dict keys, URLs) — rename now rather than special-case it later.
    pitching = pitching.rename(columns={"GB/FB": "GB_FB"})
    pitching = add_pitching_sabermetrics(pitching)

    print(f"Fetching {season} Statcast batted-ball data (pitchers)...")
    exitvelo = statcast_pitcher_exitvelo_barrels(season, minBBE=1)[
        ["player_id", "avg_hit_speed", "ev95percent", "brl_percent"]
    ].rename(columns={
        "avg_hit_speed": "avg_exit_velo_against",
        "ev95percent": "hard_hit_pct_against",
        "brl_percent": "barrel_pct_against",
    })

    # xERA: Statcast's contact-quality-based expected ERA — the closest
    # equivalent this data source has to xFIP/SIERA. True xFIP needs a raw
    # fly-ball count and league HR/FB rate that neither Baseball-Reference
    # nor Statcast expose here (bref only gives a GB/FB *ratio*), so xERA is
    # used instead of trying to approximate xFIP from incomplete inputs.
    print(f"Fetching {season} Statcast expected stats (pitchers)...")
    expected = statcast_pitcher_expected_stats(season, minPA=1)[
        ["player_id", "xera"]
    ].rename(columns={"xera": "xERA"})

    pitching["mlbID"] = pd.to_numeric(pitching["mlbID"], errors="coerce")
    pitching = pitching.merge(exitvelo, left_on="mlbID", right_on="player_id", how="left")
    pitching = pitching.merge(expected, left_on="mlbID", right_on="player_id", how="left", suffixes=("", "_dup"))
    pitching = pitching.drop(columns=[c for c in pitching.columns if c.endswith("_dup") or c == "player_id"])

    pitching["season"] = season
    return pitching


def fetch_fielding(season=CURRENT_SEASON):
    print(f"Fetching {season} Statcast fielding (Outs Above Average)...")
    fielding = statcast_outs_above_average(season, "all")
    fielding = fielding.rename(columns={
        "last_name, first_name": "Name",
        "display_team_name": "Tm",
        "primary_pos_formatted": "Pos",
        "outs_above_average": "OAA",
        "fielding_runs_prevented": "FRP",
        "actual_success_rate_formatted": "success_rate",
    })
    fielding["season"] = season
    return fielding


def fetch_recent_batting():
    """Batting stats over the last day/week/month, for 'headliner' cards that
    highlight hot recent performances rather than just season-to-date bests.
    Uses Baseball-Reference's date-range endpoint (games completed through
    yesterday, since today's games are still in progress when this runs)."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    windows = {
        "day": (yesterday, yesterday),
        "week": (today - timedelta(days=7), yesterday),
        "month": (today - timedelta(days=30), yesterday),
    }

    frames = []
    for period, (start, end) in windows.items():
        print(f"Fetching recent batting stats ({period}: {start} to {end})...")
        try:
            df = batting_stats_range(start.isoformat(), end.isoformat())
        except Exception as e:
            print(f"  skipped ({e})")
            continue
        if df.empty:
            continue
        df["Name"] = fix_mojibake_names(df["Name"])
        df["period"] = period
        df["season"] = CURRENT_SEASON
        frames.append(df)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def fetch_recent_pitching():
    """Pitching stats over the last day/week/month, mirroring fetch_recent_batting.
    'day' includes Game Score (GSc), a well-known single-game dominance metric;
    week/month use ERA instead since Game Score isn't meaningful summed across starts."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    windows = {
        "day": (yesterday, yesterday),
        "week": (today - timedelta(days=7), yesterday),
        "month": (today - timedelta(days=30), yesterday),
    }

    frames = []
    for period, (start, end) in windows.items():
        print(f"Fetching recent pitching stats ({period}: {start} to {end})...")
        try:
            df = pitching_stats_range(start.isoformat(), end.isoformat())
        except Exception as e:
            print(f"  skipped ({e})")
            continue
        if df.empty:
            continue
        df["Name"] = fix_mojibake_names(df["Name"])
        df["period"] = period
        df["season"] = CURRENT_SEASON
        frames.append(df)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def fetch_todays_games():
    """Today's MLB schedule, team records, and probable starting pitchers,
    from the free public MLB Stats API (statsapi.mlb.com — no key needed).
    This is a different data source than the rest of the app (which uses
    pybaseball/Baseball-Reference/Statcast), but it's the only place that has
    a live game schedule with probable pitchers. Powers the Today's Games
    page's win predictions."""
    today = date.today().isoformat()
    columns = [
        "date", "game_pk", "game_time", "status", "venue",
        "away_team", "away_abbr", "away_wins", "away_losses", "away_pitcher_name", "away_pitcher_mlbID",
        "home_team", "home_abbr", "home_wins", "home_losses", "home_pitcher_name", "home_pitcher_mlbID",
    ]
    print(f"Fetching today's schedule ({today}) from MLB Stats API...")
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": today, "hydrate": "probablePitcher,team,venue"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  skipped ({e})")
        return pd.DataFrame(columns=columns)

    dates = data.get("dates", [])
    games = dates[0].get("games", []) if dates else []
    if not games:
        return pd.DataFrame(columns=columns)

    rows = []
    for g in games:
        away, home = g["teams"]["away"], g["teams"]["home"]
        away_pitcher = away.get("probablePitcher") or {}
        home_pitcher = home.get("probablePitcher") or {}
        rows.append({
            "date": today,
            "game_pk": g.get("gamePk"),
            "game_time": g.get("gameDate"),
            "status": g.get("status", {}).get("detailedState"),
            "venue": g.get("venue", {}).get("name"),
            "away_team": away["team"]["name"],
            "away_abbr": away["team"]["abbreviation"],
            "away_wins": away.get("leagueRecord", {}).get("wins"),
            "away_losses": away.get("leagueRecord", {}).get("losses"),
            "away_pitcher_name": away_pitcher.get("fullName"),
            "away_pitcher_mlbID": away_pitcher.get("id"),
            "home_team": home["team"]["name"],
            "home_abbr": home["team"]["abbreviation"],
            "home_wins": home.get("leagueRecord", {}).get("wins"),
            "home_losses": home.get("leagueRecord", {}).get("losses"),
            "home_pitcher_name": home_pitcher.get("fullName"),
            "home_pitcher_mlbID": home_pitcher.get("id"),
        })
    return pd.DataFrame(rows)


def fetch_standings():
    """Current division standings from the MLB Stats API. Replaced in full
    every run (current standings only — this isn't a historical table)."""
    print("Fetching standings from MLB Stats API...")
    columns = [
        "season", "league", "division", "team_name", "team_abbr",
        "wins", "losses", "pct", "games_back", "streak", "div_rank",
    ]
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/standings",
            params={"leagueId": "103,104", "season": CURRENT_SEASON},
            timeout=15,
        )
        resp.raise_for_status()
        records = resp.json().get("records", [])
    except Exception as e:
        print(f"  skipped ({e})")
        return pd.DataFrame(columns=columns)

    rows = []
    for rec in records:
        league = "AL" if rec["league"]["id"] == 103 else "NL"
        division = DIVISION_NAMES.get(rec["division"]["id"], "Unknown")
        for tr in rec.get("teamRecords", []):
            record = tr.get("leagueRecord", {})
            team_abbr, _ = app_teams.team_meta_from_nickname(tr["team"]["name"])
            rows.append({
                "season": CURRENT_SEASON,
                "league": league,
                "division": division,
                "team_name": tr["team"]["name"],
                "team_abbr": team_abbr,
                "wins": record.get("wins"),
                "losses": record.get("losses"),
                "pct": record.get("pct"),
                "games_back": tr.get("divisionGamesBack"),
                "streak": tr.get("streak", {}).get("streakCode"),
                "div_rank": tr.get("divisionRank"),
            })
    return pd.DataFrame(rows)


def build_player_history(batting, pitching, recent_batting, recent_pitching):
    """One row per player per day, appended to `player_history` on every run.
    Two purposes: season-to-date OPS/ERA power the Search page's trend line;
    day_PA/day_H and day_IP/day_ER (yesterday's single-game line, reused from
    the recent-performance fetch rather than a new network call) power hit-
    streak / scoreless-streak tracking. Append-only (not replaced) like the
    other tables, so it accumulates real history over time."""
    today = date.today().isoformat()

    bat_hist = batting[["mlbID", "Name", "Tm", "PA", "OPS"]].copy()
    bat_hist["role"] = "Batter"
    bat_hist["ERA"] = float("nan")
    bat_hist["IP"] = float("nan")
    if not recent_batting.empty:
        day_bat = recent_batting[recent_batting["period"] == "day"][["mlbID", "PA", "H"]].copy()
        day_bat["mlbID"] = pd.to_numeric(day_bat["mlbID"], errors="coerce")
        day_bat = day_bat.rename(columns={"PA": "day_PA", "H": "day_H"})
        bat_hist = bat_hist.merge(day_bat, on="mlbID", how="left")
    else:
        bat_hist["day_PA"] = float("nan")
        bat_hist["day_H"] = float("nan")
    bat_hist["day_IP"] = float("nan")
    bat_hist["day_ER"] = float("nan")

    pit_hist = pitching[["mlbID", "Name", "Tm", "IP", "ERA"]].copy()
    pit_hist["role"] = "Pitcher"
    pit_hist["PA"] = float("nan")
    pit_hist["OPS"] = float("nan")
    if not recent_pitching.empty:
        day_pit = recent_pitching[recent_pitching["period"] == "day"][["mlbID", "IP", "ER"]].copy()
        day_pit["mlbID"] = pd.to_numeric(day_pit["mlbID"], errors="coerce")
        day_pit = day_pit.rename(columns={"IP": "day_IP", "ER": "day_ER"})
        pit_hist = pit_hist.merge(day_pit, on="mlbID", how="left")
    else:
        pit_hist["day_IP"] = float("nan")
        pit_hist["day_ER"] = float("nan")
    pit_hist["day_PA"] = float("nan")
    pit_hist["day_H"] = float("nan")

    history = pd.concat([bat_hist, pit_hist], ignore_index=True)
    history["date"] = today
    history["season"] = CURRENT_SEASON
    return history[[
        "date", "season", "mlbID", "Name", "Tm", "role",
        "PA", "OPS", "IP", "ERA", "day_PA", "day_H", "day_IP", "day_ER",
    ]]


def _store_season_table(conn, table_name, df, season):
    """Write one season's worth of a table without touching other seasons'
    rows — DELETE that season, then append. This is what makes multi-season
    data possible: the old approach (`if_exists='replace'`) wiped the whole
    table on every run, so only the current season could ever be cached.

    Schema migration: `to_sql(if_exists="append")` requires the dataframe's
    columns to exactly match the existing table's, so adding/renaming/
    removing a column in a fetch_*() function breaks every other season's
    already-stored rows. Drop and let to_sql recreate the table if the
    incoming columns don't match — this loses other seasons' rows for that
    table, so after a schema change, re-run --backfill for every season
    you care about (batting/pitching/fielding are cheap, network-bound
    re-fetches, not expensive local computation)."""
    try:
        existing_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table_name})")}
        if existing_cols and existing_cols != set(df.columns):
            conn.execute(f"DROP TABLE {table_name}")
        else:
            conn.execute(f"DELETE FROM {table_name} WHERE season = ?", (season,))
    except sqlite3.OperationalError:
        pass  # table doesn't exist yet on first run
    df.to_sql(table_name, conn, if_exists="append", index=False)


def fetch_and_store():
    """Daily refresh: current season's batting/pitching/fielding/recent-performance
    data, plus today's player_history row. Does NOT touch other seasons already
    backfilled — see backfill_season() for adding historical years."""
    batting = fetch_batting(CURRENT_SEASON)
    pitching = fetch_pitching(CURRENT_SEASON)
    fielding = fetch_fielding(CURRENT_SEASON)
    recent_batting = fetch_recent_batting()
    recent_pitching = fetch_recent_pitching()
    todays_games = fetch_todays_games()
    standings = fetch_standings()
    history = build_player_history(batting, pitching, recent_batting, recent_pitching)

    conn = sqlite3.connect(DB_PATH)
    try:
        # one-time schema migration: player_history gained day_PA/day_H/day_IP/day_ER
        # columns after it first shipped; drop and let to_sql recreate it if an
        # older copy of the table is still around (loses only a few days of
        # season-trend history, which is an acceptable cost for a still-new feature)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(player_history)")]
            if cols and "day_H" not in cols:
                conn.execute("DROP TABLE player_history")
        except sqlite3.OperationalError:
            pass

        _store_season_table(conn, "batting", batting, CURRENT_SEASON)
        _store_season_table(conn, "pitching", pitching, CURRENT_SEASON)
        _store_season_table(conn, "fielding", fielding, CURRENT_SEASON)
        if not recent_batting.empty:
            recent_batting.to_sql("recent_batting", conn, if_exists="replace", index=False)
        if not recent_pitching.empty:
            recent_pitching.to_sql("recent_pitching", conn, if_exists="replace", index=False)
        # always replace, even if empty (e.g. an off day with zero games) — an
        # empty table is the correct signal for "nothing scheduled today"
        todays_games.to_sql("todays_games", conn, if_exists="replace", index=False)
        standings.to_sql("standings", conn, if_exists="replace", index=False)

        # player_history is append-only (not replaced) so it builds up real
        # day-over-day history; clear today's rows first so re-running the
        # script the same day doesn't create duplicates.
        try:
            conn.execute(
                "DELETE FROM player_history WHERE date = ? AND season = ?",
                (date.today().isoformat(), CURRENT_SEASON),
            )
        except sqlite3.OperationalError:
            pass  # table doesn't exist yet on first run
        history.to_sql("player_history", conn, if_exists="append", index=False)

        conn.commit()
    finally:
        conn.close()

    print(
        f"Saved {len(batting)} batters, {len(pitching)} pitchers, "
        f"{len(fielding)} fielders, {len(recent_batting)} recent-batting rows, "
        f"{len(recent_pitching)} recent-pitching rows, {len(history)} history rows, "
        f"{len(todays_games)} today's games, {len(standings)} standings rows to {DB_PATH}"
    )


def backfill_season(season):
    """One-time fetch of a single historical season's batting/pitching/fielding
    (no recent-performance or player_history — those are 'right now' concepts
    that don't apply to past seasons). Deliberately does ONE season per call
    and returns immediately after writing to disk, so memory doesn't build up
    across multiple seasons — run this once per season, checking the dashboard
    still behaves between each one, rather than looping over many seasons in
    a single process."""
    batting = fetch_batting(season)
    pitching = fetch_pitching(season)
    fielding = fetch_fielding(season)

    conn = sqlite3.connect(DB_PATH)
    try:
        _store_season_table(conn, "batting", batting, season)
        _store_season_table(conn, "pitching", pitching, season)
        _store_season_table(conn, "fielding", fielding, season)
        conn.commit()
    finally:
        conn.close()

    print(f"Backfilled {season}: {len(batting)} batters, {len(pitching)} pitchers, {len(fielding)} fielders to {DB_PATH}")


if __name__ == "__main__":
    import sys

    DB_PATH.parent.mkdir(exist_ok=True)
    if len(sys.argv) > 1 and sys.argv[1] == "--backfill":
        backfill_season(int(sys.argv[2]))
    else:
        fetch_and_store()
