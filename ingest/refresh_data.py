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
import json
import os
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

try:
    import anthropic
except ImportError:
    anthropic = None

from pybaseball import (
    batting_stats_bref,
    pitching_stats_bref,
    batting_stats_range,
    pitching_stats_range,
    bwar_bat,
    bwar_pitch,
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


def add_batting_plus_stats(df):
    """OPS+ and wRC+ (100 = league average, higher is better), computed from
    this same season's field rather than fetched from anywhere else, so they
    stay consistent with our own OBP/SLG/wOBA_calc numbers. Simplification:
    no park-factor adjustment (we don't have a park-factors source wired up),
    unlike FanGraphs/Baseball-Reference's published versions."""
    total_pa = df["PA"].sum()
    lg_obp = (df["OBP"] * df["PA"]).sum() / total_pa
    lg_slg = (df["SLG"] * df["PA"]).sum() / total_pa
    df["OPS_plus"] = (100 * (df["OBP"] / lg_obp + df["SLG"] / lg_slg - 1)).round(0)

    # wRC+: standard "runs created per PA, relative to league average" plus
    # stat. wOBA_scale converts wOBA points to runs; FanGraphs publishes an
    # exact value per season (recently ~1.20-1.25) — we use a fixed 1.20
    # approximation since we don't have their guts-constants feed.
    woba_scale = 1.20
    lg_woba = (df["wOBA_calc"] * df["PA"]).sum() / total_pa
    lg_r_pa = df["R"].sum() / total_pa
    wrc_per_pa = (df["wOBA_calc"] - lg_woba) / woba_scale + lg_r_pa
    df["wRC_plus"] = (100 * wrc_per_pa / lg_r_pa).round(0)
    return df


def add_pitching_plus_stats(df):
    """ERA+ (100 = league average, higher is better). Same no-park-factor
    simplification as OPS+/wRC+ above."""
    lg_era = df["ER"].sum() * 9 / df["IP"].sum()
    df["ERA_plus"] = (100 * lg_era / df["ERA"].replace(0, float("nan"))).round(0)
    return df


def fetch_war(is_pitcher, season):
    """Baseball-Reference's WAR (bwar_bat/bwar_pitch), keyed by mlb_ID. A
    player traded mid-season has one row per stint, so sum WAR across stints
    to get a season total — min_count=1 so a player with no numeric rows at
    all (older/legacy players lacking a WAR calc) stays NaN instead of 0."""
    raw = bwar_pitch() if is_pitcher else bwar_bat()
    raw = raw[raw["year_ID"] == season]
    war = raw.groupby("mlb_ID", as_index=False)["WAR"].sum(min_count=1)
    return war.rename(columns={"mlb_ID": "player_id"})


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
        ["player_id", "woba", "est_woba", "est_ba", "est_slg",
         "est_ba_minus_ba_diff", "est_slg_minus_slg_diff", "est_woba_minus_woba_diff"]
    ].rename(columns={
        "woba": "wOBA",
        "est_woba": "xwOBA",
        "est_ba": "xBA",
        "est_slg": "xSLG",
        "est_ba_minus_ba_diff": "xBA_diff",
        "est_slg_minus_slg_diff": "xSLG_diff",
        "est_woba_minus_woba_diff": "xwOBA_diff",
    })

    print(f"Fetching {season} WAR (Baseball-Reference)...")
    war = fetch_war(is_pitcher=False, season=season)

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
    for stats_df in (exitvelo, expected, sprint, baserunning_value, war):
        batting = batting.merge(stats_df, left_on="mlbID", right_on="player_id", how="left")
        batting = batting.drop(columns="player_id")

    batting = add_batting_plus_stats(batting)
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
    # used instead of trying to approximate xFIP from incomplete inputs. This
    # same leaderboard also has expected-contact-quality equivalents of
    # BA/SLG/wOBA against, so we're not limited to just xERA here.
    print(f"Fetching {season} Statcast expected stats (pitchers)...")
    expected = statcast_pitcher_expected_stats(season, minPA=1)[
        ["player_id", "xera", "est_ba", "est_slg", "est_woba", "era_minus_xera_diff"]
    ].rename(columns={
        "xera": "xERA",
        "est_ba": "xBA_against",
        "est_slg": "xSLG_against",
        "est_woba": "xwOBA_against",
        "era_minus_xera_diff": "xERA_diff",
    })

    print(f"Fetching {season} WAR (Baseball-Reference)...")
    war = fetch_war(is_pitcher=True, season=season)

    pitching["mlbID"] = pd.to_numeric(pitching["mlbID"], errors="coerce")
    for stats_df in (exitvelo, expected, war):
        pitching = pitching.merge(stats_df, left_on="mlbID", right_on="player_id", how="left", suffixes=("", "_dup"))
        pitching = pitching.drop(columns=[c for c in pitching.columns if c.endswith("_dup") or c == "player_id"])

    pitching = add_pitching_plus_stats(pitching)
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
        # Baseball-Reference leaves SV blank instead of 0 for pitchers with
        # no saves in the window (same quirk as the season pitching table).
        df["SV"] = df["SV"].fillna(0).astype(int)
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


def fetch_il_moves(days=2):
    """Injured-list placements from the last `days` days, via the same MLB
    Stats API transactions endpoint app/db.py's load_transactions() uses —
    duplicated here (rather than imported) so the ingest script doesn't have
    to pull in app/db.py's Streamlit dependency. Filtered to new placements
    only (activations excluded), matching the Daily Digest page's own filter."""
    end, start = date.today(), date.today() - timedelta(days=days)
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/transactions",
            params={"sportId": 1, "startDate": start.strftime("%m/%d/%Y"), "endDate": end.strftime("%m/%d/%Y")},
            timeout=15,
        )
        resp.raise_for_status()
        txs = resp.json().get("transactions", [])
    except Exception as e:
        print(f"  IL-moves fetch skipped ({e})")
        return pd.DataFrame(columns=["date", "description", "to_abbr", "from_abbr", "mlbID"])

    rows = []
    for t in txs:
        desc = t.get("description")
        if not desc or "injured list" not in desc.lower() or "activated" in desc.lower():
            continue
        rows.append({
            "date": t.get("date"),
            "description": desc,
            "to_abbr": app_teams.abbr_for_team_id((t.get("toTeam") or {}).get("id")),
            "from_abbr": app_teams.abbr_for_team_id((t.get("fromTeam") or {}).get("id")),
            "mlbID": (t.get("person") or {}).get("id"),
        })
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    df = pd.DataFrame(rows, columns=["date", "description", "to_abbr", "from_abbr", "mlbID"])
    return df[df["date"] == yesterday]


def percentile_rank(series, value, lower_is_better=False):
    """Small standalone copy of app/db.py's percentile_rank() — duplicated
    rather than imported for the same reason as fetch_il_moves() above."""
    clean = series.dropna()
    if value is None or pd.isna(value) or len(clean) == 0:
        return None
    pct = (clean >= value).mean() * 100 if lower_is_better else (clean <= value).mean() * 100
    return int(round(pct))


ARTICLE_MODEL = "claude-sonnet-5"

_ARTICLE_INSTRUCTIONS = (
    "You are a beat writer for a baseball analytics dashboard, writing a short "
    "\"storyline of the day\" article about yesterday's MLB action. No web "
    "search or outside research is available — write using ONLY the stats "
    "given to you below, which include this player's full season stat line, "
    "several advanced/percentile numbers, and yesterday's trigger performance. "
    "Write a headline (under 8 words), a one-sentence teaser, and exactly 3 "
    "paragraphs of prose (2-4 sentences each) in a factual, engaging "
    "beat-writer tone. Ground every claim in the stats given below — never "
    "invent quotes, injuries, trades, or stats that weren't given to you. "
    "Use the percentile numbers to add real context (e.g. \"top-10% in the "
    "league\") rather than just restating raw stats.\n\n"
    "Respond with ONLY a JSON object (no other text before or after it), in "
    'exactly this shape: {"headline": "...", "teaser": "...", "paragraphs": '
    '["...", "...", "..."]}'
)


def _generate_article(trigger, stat_context):
    """Calls Claude to write one article purely from the stats handed to it
    (no web search — see _ARTICLE_INSTRUCTIONS). Returns the parsed
    {"headline", "teaser", "paragraphs"} dict, or None on any failure —
    missing API key, network/API error, or a response that doesn't parse as
    the expected JSON. A single failed article should never take down the
    rest of the daily refresh."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or anthropic is None:
        return None
    prompt = f"{_ARTICLE_INSTRUCTIONS}\n\nYesterday's trigger: {trigger}\n\n{stat_context}"
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=ARTICLE_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group(0))
        if not all(k in data for k in ("headline", "teaser", "paragraphs")) or len(data["paragraphs"]) < 1:
            return None
        return data
    except Exception as e:
        print(f"  article generation failed: {e}")
        return None


def _batting_stat_dump(season_row, qualified):
    """Every batting stat we have on this player's season, handed to the
    model as-is (see build_daily_articles) rather than pre-summarized into a
    sentence or two — "feed it all the data we have" per the design call for
    this feature, now that there's no web search to fill in context instead."""
    if season_row is None:
        return "Season stats: not yet qualified for season leaderboards (under 50 PA)."
    fields = {
        "BA": season_row.get("BA"), "OBP": season_row.get("OBP"), "SLG": season_row.get("SLG"),
        "OPS": season_row.get("OPS"), "HR": season_row.get("HR"), "RBI": season_row.get("RBI"),
        "R": season_row.get("R"), "SB": season_row.get("SB"), "PA": season_row.get("PA"),
        "ISO": season_row.get("ISO"), "BABIP": season_row.get("BABIP"), "K%": season_row.get("K_PCT"),
        "BB%": season_row.get("BB_PCT"), "wOBA": season_row.get("wOBA"), "xwOBA": season_row.get("xwOBA"),
        "WAR": season_row.get("WAR"), "OPS+": season_row.get("OPS_plus"), "wRC+": season_row.get("wRC_plus"),
    }
    percentiles = {
        "OPS percentile": percentile_rank(qualified["OPS"], season_row.get("OPS")),
        "ISO percentile": percentile_rank(qualified["ISO"], season_row.get("ISO")),
        "WAR percentile": percentile_rank(qualified["WAR"], season_row.get("WAR")) if "WAR" in qualified else None,
    }
    parts = [f"{k} {v}" for k, v in fields.items() if v is not None and not pd.isna(v)]
    parts += [f"{k} {v}" for k, v in percentiles.items() if v is not None]
    return "Season stats: " + ", ".join(parts) + "."


def _pitching_stat_dump(season_row, qualified):
    """Pitching equivalent of _batting_stat_dump()."""
    if season_row is None:
        return "Season stats: not yet qualified for season leaderboards (under 20 IP)."
    fields = {
        "ERA": season_row.get("ERA"), "WHIP": season_row.get("WHIP"), "IP": season_row.get("IP"),
        "SO": season_row.get("SO"), "BB": season_row.get("BB"), "W": season_row.get("W"),
        "L": season_row.get("L"), "SV": season_row.get("SV"), "K_9": season_row.get("K_9"),
        "BB_9": season_row.get("BB_9"), "FIP": season_row.get("FIP"), "xERA": season_row.get("xERA"),
        "WAR": season_row.get("WAR"), "ERA+": season_row.get("ERA_plus"),
    }
    percentiles = {
        "ERA percentile": percentile_rank(qualified["ERA"], season_row.get("ERA"), lower_is_better=True),
        "K/9 percentile": percentile_rank(qualified["K_9"], season_row.get("K_9")),
        "WAR percentile": percentile_rank(qualified["WAR"], season_row.get("WAR")) if "WAR" in qualified else None,
    }
    parts = [f"{k} {v}" for k, v in fields.items() if v is not None and not pd.isna(v)]
    parts += [f"{k} {v}" for k, v in percentiles.items() if v is not None]
    return "Season stats: " + ", ".join(parts) + "."


def _batting_article(row, batting, used_ids):
    """Builds one AI-written article from a single day-window batting row.
    Returns None if the mlbID was already used for another article today
    (so the guaranteed-3rd-article fallback in build_daily_articles() can't
    duplicate the same player) or if _generate_article() itself fails."""
    mlbID = int(row["mlbID"])
    if mlbID in used_ids:
        return None
    hits, hr, rbi = int(row["H"]), int(row["HR"]), int(row["RBI"])
    tb = int(row["H"] + row["2B"] + 2 * row["3B"] + 3 * row["HR"])
    abbr, nickname, color = app_teams.team_meta_from_city(row["Tm"], row.get("Lev"))
    qualified = batting[batting["PA"] >= 50]
    season_row_df = batting[batting["mlbID"] == mlbID]
    season_row = season_row_df.iloc[0] if not season_row_df.empty else None
    trigger = (
        f"{row['Name']} ({nickname}) went {hits}-for-his-game yesterday with {tb} total bases, "
        f"{hr} home run(s), and {rbi} RBI."
    )
    article = _generate_article(trigger, _batting_stat_dump(season_row, qualified))
    if not article:
        return None
    article["mlbID"] = mlbID
    article["Tm"] = abbr
    article["color"] = color
    used_ids.add(mlbID)
    return article


def _pitching_article(row, pitching, used_ids):
    """Pitching equivalent of _batting_article()."""
    mlbID = int(pd.to_numeric(row["mlbID"]))
    if mlbID in used_ids:
        return None
    era, ip, so = row["ERA"], row["IP"], int(row["SO"])
    gsc = pd.to_numeric(row.get("GSc"), errors="coerce")
    gsc_clause = f" (Game Score {int(gsc)})" if pd.notna(gsc) else ""
    abbr, nickname, color = app_teams.team_meta_from_city(row["Tm"], row.get("Lev"))
    qualified = pitching[pitching["IP"] >= 20]
    season_row_df = pitching[pitching["mlbID"] == mlbID]
    season_row = season_row_df.iloc[0] if not season_row_df.empty else None
    trigger = (
        f"{row['Name']} ({nickname}) threw {ip:.1f} innings yesterday, allowing "
        f"{era:.2f} runs per nine with {so} strikeouts{gsc_clause}."
    )
    article = _generate_article(trigger, _pitching_stat_dump(season_row, qualified))
    if not article:
        return None
    article["mlbID"] = mlbID
    article["Tm"] = abbr
    article["color"] = color
    used_ids.add(mlbID)
    return article


def build_daily_articles(recent_batting, recent_pitching, batting, pitching):
    """Assembles the Daily Digest page's "Today's Storylines": 3 AI-written
    articles about yesterday's action — the day's best batting line, best
    pitching line, and (if there was one) the most notable injury, else a
    third notable performance so the digest still gets 3 stories most days.
    Written purely from this app's own stats (see _generate_article) — no
    outside research. Runs once here during the daily ingest, NOT at
    page-load time, since every article is a real API call. Returns []
    entirely if ANTHROPIC_API_KEY isn't configured — the Daily Digest page
    just shows its empty state in that case."""
    articles = []
    used_ids = set()

    day_batting = pd.DataFrame()
    if not recent_batting.empty:
        day_batting = recent_batting[
            (recent_batting["period"] == "day") & (recent_batting["PA"] >= RECENT_MIN_PA["day"])
        ].copy()
        if not day_batting.empty:
            day_batting["TB"] = day_batting["H"] + day_batting["2B"] + 2 * day_batting["3B"] + 3 * day_batting["HR"]
            day_batting = day_batting.sort_values("TB", ascending=False).reset_index(drop=True)
            article = _batting_article(day_batting.iloc[0], batting, used_ids)
            if article:
                articles.append(article)

    day_pitching = pd.DataFrame()
    if not recent_pitching.empty:
        day_pitching = recent_pitching[
            (recent_pitching["period"] == "day") & (recent_pitching["IP"] >= RECENT_MIN_IP["day"])
        ].copy()
        if not day_pitching.empty:
            gsc = pd.to_numeric(day_pitching["GSc"], errors="coerce")
            day_pitching = day_pitching.loc[gsc.sort_values(ascending=False).index].reset_index(drop=True)
            article = _pitching_article(day_pitching.iloc[0], pitching, used_ids)
            if article:
                articles.append(article)

    # Third slot: the most notable injury, judged by season percentile or
    # playing time (a September call-up's IL trip isn't a story) — falling
    # back to the next-best batting/pitching performance not already used
    # above, so the digest still lands on 3 stories on a day with no
    # newsworthy injury.
    third_article = None
    il_moves = fetch_il_moves()
    if not il_moves.empty:
        qualified_batting = batting[batting["PA"] >= 50]
        qualified_pitching = pitching[pitching["IP"] >= 20]
        candidates = []
        for _, row in il_moves.iterrows():
            mlbID = row.get("mlbID")
            if mlbID is None or pd.isna(mlbID):
                continue
            mlbID = int(mlbID)
            b_row = batting[batting["mlbID"] == mlbID]
            p_row = pitching[pitching["mlbID"] == mlbID]
            if not b_row.empty and b_row.iloc[0]["PA"] >= 50:
                pct = percentile_rank(qualified_batting["OPS"], b_row.iloc[0]["OPS"])
                if (pct is not None and pct >= 60) or b_row.iloc[0]["PA"] >= 300:
                    candidates.append((pct or 0, row, b_row.iloc[0], "batting"))
            elif not p_row.empty and p_row.iloc[0]["IP"] >= 20:
                pct = percentile_rank(qualified_pitching["ERA"], p_row.iloc[0]["ERA"], lower_is_better=True)
                if (pct is not None and pct >= 60) or p_row.iloc[0]["IP"] >= 60:
                    candidates.append((pct or 0, row, p_row.iloc[0], "pitching"))

        if candidates:
            candidates.sort(key=lambda c: c[0], reverse=True)
            pct, tx_row, season_row, kind = candidates[0]
            abbr = tx_row["to_abbr"] if isinstance(tx_row["to_abbr"], str) else tx_row["from_abbr"]
            nickname = app_teams.nickname_for_abbr(abbr)
            name = season_row["Name"]
            trigger = f"The {abbr} placed {name} on the injured list yesterday: \"{tx_row['description']}\"."
            if kind == "batting":
                stat_context = _batting_stat_dump(season_row, qualified_batting) + f" Team: {nickname}."
            else:
                stat_context = _pitching_stat_dump(season_row, qualified_pitching) + f" Team: {nickname}."
            article = _generate_article(trigger, stat_context)
            if article:
                article["mlbID"] = int(season_row["mlbID"])
                article["Tm"] = abbr
                article["color"] = app_teams.color_for_abbr(abbr)
                third_article = article

    if third_article is None:
        for i in range(1, len(day_batting)):
            third_article = _batting_article(day_batting.iloc[i], batting, used_ids)
            if third_article:
                break
    if third_article is None:
        for i in range(1, len(day_pitching)):
            third_article = _pitching_article(day_pitching.iloc[i], pitching, used_ids)
            if third_article:
                break

    if third_article:
        articles.append(third_article)

    return articles


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
    articles = build_daily_articles(recent_batting, recent_pitching, batting, pitching)

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

        # Always replace (current day's storylines only, like todays_games/
        # standings above) — an empty table is the correct signal for "no
        # ANTHROPIC_API_KEY configured" or "nothing notable happened".
        articles_df = pd.DataFrame([
            {
                "mlbID": a["mlbID"], "Tm": a["Tm"], "color": a["color"],
                "headline": a["headline"], "teaser": a["teaser"],
                "paragraphs": json.dumps(a["paragraphs"]),
            }
            for a in articles
        ], columns=["mlbID", "Tm", "color", "headline", "teaser", "paragraphs"])
        articles_df.to_sql("daily_articles", conn, if_exists="replace", index=False)

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
        f"{len(todays_games)} today's games, {len(standings)} standings rows, "
        f"{len(articles)} daily articles to {DB_PATH}"
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
