"""Shared helpers for reading the cached stats database."""
import json
import math
import re
import sqlite3
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import streamlit as st

import teams

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "stats.db"

FINAL_STATUSES = {"Final", "Game Over", "Completed Early"}


def today_pacific() -> date:
    """The current Pacific calendar date — the one source of truth for
    "what day is it" anywhere in the live app. Streamlit Community Cloud
    runs its servers in UTC, which is far enough ahead of Pacific that a
    plain date.today() rolls over to the next day while it's still evening
    in Pacific time, showing "tomorrow's" content hours too early. The
    daily ingest cron also runs at a fixed Pacific-morning UTC time, so
    Pacific is this app's natural notion of a baseball day anyway."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).date()


def normalize_text(text: str) -> str:
    """Lowercase and strip accents so 'garcia' matches 'García'."""
    if not isinstance(text, str):
        return ""
    stripped = unicodedata.normalize("NFKD", text)
    return "".join(c for c in stripped if not unicodedata.combining(c)).lower()


_LOW_CARD_COLS = {"Tm", "Lev", "Pos", "period", "role", "roles"}


def _downcast(df: pd.DataFrame) -> pd.DataFrame:
    """Shrink dtypes to cut memory footprint: float64/int64 -> 32-bit,
    and low-cardinality repeated strings (team, level, position...) -> category."""
    for col in df.select_dtypes(include="float64").columns:
        df[col] = pd.to_numeric(df[col], downcast="float")
    for col in df.select_dtypes(include="int64").columns:
        df[col] = pd.to_numeric(df[col], downcast="integer")
    for col in _LOW_CARD_COLS & set(df.columns):
        df[col] = df[col].astype("category")
    return df


def get_seasons(table: str) -> list[int]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(f"SELECT DISTINCT season FROM {table} ORDER BY season DESC").fetchall()
    return [r[0] for r in rows]


# Only the columns actually used anywhere in the app get pulled out of
# SQLite — Baseball-Reference/Statcast ship many raw columns (pitch counts,
# batted-ball splits, etc.) that nothing renders, so leaving them out cuts
# each dataframe's memory footprint noticeably.
BATTING_COLS = [
    "Name", "Age", "Lev", "Tm", "G", "PA", "AB", "R", "H", "2B", "3B", "HR",
    "RBI", "BB", "SO", "SB", "CS", "BA", "OBP", "SLG", "OPS", "mlbID",
    "ISO", "BABIP", "K_PCT", "BB_PCT", "wOBA", "avg_exit_velo", "max_exit_velo",
    "hard_hit_pct", "barrel_pct", "contact_pctile", "contact_pct",
    "chase_pctile", "chase_pct", "bat_speed_pctile", "bat_speed",
    "xISO_pctile", "xISO", "xOBP_pctile", "xOBP",
    "xwOBA", "xBA", "xSLG",
    "xBA_diff", "xSLG_diff", "xwOBA_diff", "OPS_plus", "wRC_plus", "WAR",
    "sprint_speed", "hp_to_1b", "baserunning_runs", "season",
]
PITCHING_COLS = [
    "Name", "Age", "Lev", "Tm", "G", "GS", "W", "L", "SV", "IP", "ERA", "WHIP",
    "SO", "BB", "HR", "mlbID", "K_9", "BB_9", "K_BB", "FIP", "xFIP", "xERA", "BAbip", "GB_FB",
    "xBA_against", "xSLG_against", "xwOBA_against", "xERA_diff", "ERA_plus", "WAR",
    "avg_exit_velo_against", "hard_hit_pct_against", "barrel_pct_against",
    "fastball_velo_pctile", "fastball_velo", "induced_chase_pctile", "induced_chase_pct", "season",
]
FIELDING_COLS = [
    "Name", "player_id", "Tm", "Pos", "OAA", "FRP", "success_rate",
    "adj_estimated_success_rate_formatted", "diff_success_rate_formatted",
    "arm_strength", "season",
]
RECENT_BATTING_COLS = ["mlbID", "Name", "Tm", "Lev", "PA", "H", "2B", "3B", "HR", "RBI", "SB", "OPS", "period", "season"]
RECENT_PITCHING_COLS = ["mlbID", "Name", "Tm", "Lev", "IP", "ERA", "GSc", "SO", "ER", "BB", "HBP", "H", "SV", "period", "season"]


def _select(cols: list[str]) -> str:
    return ", ".join(f'"{c}"' for c in cols)


@st.cache_data(show_spinner=False, max_entries=4)
def load_batting(season: int, db_mtime_val: float) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql(
            f"SELECT {_select(BATTING_COLS)} FROM batting WHERE season = ?", conn, params=(season,)
        )
    return _downcast(df)


@st.cache_data(show_spinner=False, max_entries=4)
def load_pitching(season: int, db_mtime_val: float) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql(
            f"SELECT {_select(PITCHING_COLS)} FROM pitching WHERE season = ?", conn, params=(season,)
        )
    return _downcast(df)


@st.cache_data(show_spinner=False, max_entries=4)
def load_fielding(season: int, db_mtime_val: float) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql(
            f"SELECT {_select(FIELDING_COLS)} FROM fielding WHERE season = ?", conn, params=(season,)
        )
    return _downcast(df)


RECENT_MIN_PA = {"day": 3, "week": 15, "month": 50}
RECENT_MIN_IP = {"day": 1, "week": 8, "month": 20}


@st.cache_data(show_spinner=False, max_entries=4)
def load_recent_batting(season: int, db_mtime_val: float) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        try:
            df = pd.read_sql(
                f"SELECT {_select(RECENT_BATTING_COLS)} FROM recent_batting WHERE season = ?",
                conn, params=(season,),
            )
        except pd.errors.DatabaseError:
            return pd.DataFrame()
    return _downcast(df)


@st.cache_data(show_spinner=False, max_entries=4)
def load_recent_pitching(season: int, db_mtime_val: float) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        try:
            df = pd.read_sql(
                f"SELECT {_select(RECENT_PITCHING_COLS)} FROM recent_pitching WHERE season = ?",
                conn, params=(season,),
            )
        except pd.errors.DatabaseError:
            return pd.DataFrame()
    # Baseball-Reference leaves GSc blank for some rows, which makes the
    # whole column round-trip through SQLite as TEXT (mixed blank/numeric
    # strings) instead of a number — sort_values("GSc") on a string column
    # sorts lexicographically, not numerically, so e.g. "9" outranks "88".
    # That let a genuinely terrible outing (a handful of Ks, a high single
    # digit GSc) show up as a "top" pitching performance over real gems.
    if "GSc" in df.columns:
        df["GSc"] = pd.to_numeric(df["GSc"], errors="coerce")
    return _downcast(df)


def top_recent_performer(recent_batting: pd.DataFrame, period: str) -> pd.Series | None:
    """Best batting performance for a day/week/month window. A single game's
    OPS is mostly noise (a 1-for-1 with a walk can show 3+ OPS), so 'day' is
    ranked by Total Bases instead — a counting stat that actually reflects
    how good the game was. Week/month have enough PA for OPS to mean something."""
    if recent_batting.empty:
        return None
    subset = recent_batting[recent_batting["period"] == period]
    qualified = subset[subset["PA"] >= RECENT_MIN_PA.get(period, 1)]
    if qualified.empty:
        return None
    if period == "day":
        qualified = qualified.copy()
        qualified["TB"] = qualified["H"] + qualified["2B"] + 2 * qualified["3B"] + 3 * qualified["HR"]
        return qualified.sort_values("TB", ascending=False).iloc[0]
    return qualified.sort_values("OPS", ascending=False).iloc[0]


def top_recent_pitcher(recent_pitching: pd.DataFrame, period: str) -> pd.Series | None:
    """Best pitching performance for a day/week/month window: Game Score for
    a single day (the standard single-game dominance metric), ERA (with a
    minimum IP bar) for week/month since Game Score isn't meaningful summed."""
    if recent_pitching.empty:
        return None
    subset = recent_pitching[recent_pitching["period"] == period]
    qualified = subset[subset["IP"] >= RECENT_MIN_IP.get(period, 1)]
    if qualified.empty:
        return None
    if period == "day" and "GSc" in qualified.columns:
        return qualified.sort_values("GSc", ascending=False).iloc[0]
    return qualified.sort_values("ERA", ascending=True).iloc[0]


def top_n_recent_batters(recent_batting: pd.DataFrame, period: str, n: int = 5) -> pd.DataFrame:
    """Same ranking as top_recent_performer(), but the top `n` rows instead
    of just the single best — for a digest-style list rather than one card."""
    if recent_batting.empty:
        return recent_batting
    subset = recent_batting[recent_batting["period"] == period]
    qualified = subset[subset["PA"] >= RECENT_MIN_PA.get(period, 1)].copy()
    if qualified.empty:
        return qualified
    if period == "day":
        qualified["TB"] = qualified["H"] + qualified["2B"] + 2 * qualified["3B"] + 3 * qualified["HR"]
        return qualified.sort_values("TB", ascending=False).head(n)
    return qualified.sort_values("OPS", ascending=False).head(n)


def top_n_recent_pitchers(recent_pitching: pd.DataFrame, period: str, n: int = 5) -> pd.DataFrame:
    """Same ranking as top_recent_pitcher(), but the top `n` rows instead of
    just the single best — for a digest-style list rather than one card."""
    if recent_pitching.empty:
        return recent_pitching
    subset = recent_pitching[recent_pitching["period"] == period]
    qualified = subset[subset["IP"] >= RECENT_MIN_IP.get(period, 1)]
    if qualified.empty:
        return qualified
    if period == "day" and "GSc" in qualified.columns:
        return qualified.sort_values("GSc", ascending=False).head(n)
    return qualified.sort_values("ERA", ascending=True).head(n)


# Season home-run totals worth calling out when a player's most recent game
# pushed them past one. Deliberately limited to "notable" round numbers
# (not 20/25) so this doesn't fire constantly — the whole point is that it's
# rare enough to be worth a special callout, not just another leaderboard.
HR_MILESTONE_THRESHOLDS = [30, 40, 50, 60, 70]

# Same idea, for pitchers: saves, strikeouts, innings pitched.
SV_MILESTONE_THRESHOLDS = [40, 50]
SO_MILESTONE_THRESHOLDS = [200]
IP_MILESTONE_THRESHOLDS = [200]

# Sort priority for display when multiple milestones happen on the same day
# (rarer first).
_MILESTONE_PRIORITY = {
    "Perfect Game": 0, "No-Hitter": 1, "Cycle": 2, "HR Milestone": 3,
    "SV Milestone": 4, "SO Milestone": 5, "IP Milestone": 6,
}


def get_milestones(season: int, db_mtime_val: float) -> list[dict]:
    """Detects notable single-day achievements from yesterday's games:
    hitting for the cycle, throwing a no-hitter or perfect game, and crossing
    a season home-run/save/strikeout/innings-pitched milestone. Built entirely
    from data already fetched
    daily (recent_batting/recent_pitching day-window rows + season totals) —
    no extra network calls. Returns an empty list on a day with nothing
    notable, which is the common case.

    Known limitations (documented rather than silently wrong):
    - Combined no-hitters/perfect games (multiple relief pitchers) aren't
      caught — only a single pitcher going 9+ IP solo is detected, since
      that's what a single day-window row represents.
    - Perfect game detection checks 0 H / 0 BB / 0 HBP over 9+ IP, which
      doesn't rule out reaching base via a fielding error — the closest
      approximation available from box-score-level stats.
    - HR/SV/SO/IP milestones are season totals only, not career totals
      (this app only caches the current season's cumulative stats)."""
    recent_batting = load_recent_batting(season, db_mtime_val)
    recent_pitching = load_recent_pitching(season, db_mtime_val)
    milestones = []

    if not recent_batting.empty:
        day_batting = recent_batting[recent_batting["period"] == "day"]
        season_batting = load_batting(season, db_mtime_val)[["mlbID", "HR"]].rename(columns={"HR": "season_HR"})
        day_batting = day_batting.merge(season_batting, on="mlbID", how="left")

        for _, row in day_batting.iterrows():
            singles = row["H"] - row["2B"] - row["3B"] - row["HR"]
            if singles >= 1 and row["2B"] >= 1 and row["3B"] >= 1 and row["HR"] >= 1:
                milestones.append({
                    "mlbID": row["mlbID"], "Name": row["Name"], "Tm": row["Tm"], "Lev": row.get("Lev"),
                    "category": "Cycle", "text": "Hit for the cycle",
                })

            if row["HR"] >= 1 and pd.notna(row.get("season_HR")):
                before = row["season_HR"] - row["HR"]
                for threshold in HR_MILESTONE_THRESHOLDS:
                    if before < threshold <= row["season_HR"]:
                        milestones.append({
                            "mlbID": row["mlbID"], "Name": row["Name"], "Tm": row["Tm"], "Lev": row.get("Lev"),
                            "category": "HR Milestone", "text": f"Reached {threshold} home runs this season",
                        })

    if not recent_pitching.empty:
        # recent_pitching.mlbID is stored as text in SQLite (unlike every
        # other table's mlbID) — cast before merging on it or pandas raises.
        recent_pitching = recent_pitching.assign(mlbID=recent_pitching["mlbID"].astype(int))
        day_pitching = recent_pitching[recent_pitching["period"] == "day"]
        no_hit_bids = day_pitching[(day_pitching["IP"] >= 9) & (day_pitching["H"] == 0)]
        for _, row in no_hit_bids.iterrows():
            is_perfect = row.get("BB") == 0 and row.get("HBP") == 0
            milestones.append({
                "mlbID": row["mlbID"], "Name": row["Name"], "Tm": row["Tm"], "Lev": row.get("Lev"),
                "category": "Perfect Game" if is_perfect else "No-Hitter",
                "text": "Threw a perfect game" if is_perfect else "Threw a no-hitter",
            })

        season_pitching = load_pitching(season, db_mtime_val)[["mlbID", "SV", "SO", "IP"]].rename(
            columns={"SV": "season_SV", "SO": "season_SO", "IP": "season_IP"}
        )
        day_pitching = day_pitching.merge(season_pitching, on="mlbID", how="left")

        for _, row in day_pitching.iterrows():
            if row["SV"] >= 1 and pd.notna(row.get("season_SV")):
                before = row["season_SV"] - row["SV"]
                for threshold in SV_MILESTONE_THRESHOLDS:
                    if before < threshold <= row["season_SV"]:
                        milestones.append({
                            "mlbID": row["mlbID"], "Name": row["Name"], "Tm": row["Tm"], "Lev": row.get("Lev"),
                            "category": "SV Milestone", "text": f"Reached {threshold} saves this season",
                        })

            if row["SO"] >= 1 and pd.notna(row.get("season_SO")):
                before = row["season_SO"] - row["SO"]
                for threshold in SO_MILESTONE_THRESHOLDS:
                    if before < threshold <= row["season_SO"]:
                        milestones.append({
                            "mlbID": row["mlbID"], "Name": row["Name"], "Tm": row["Tm"], "Lev": row.get("Lev"),
                            "category": "SO Milestone", "text": f"Reached {threshold} strikeouts this season",
                        })

            if row["IP"] > 0 and pd.notna(row.get("season_IP")):
                before = row["season_IP"] - row["IP"]
                for threshold in IP_MILESTONE_THRESHOLDS:
                    if before < threshold <= row["season_IP"]:
                        milestones.append({
                            "mlbID": row["mlbID"], "Name": row["Name"], "Tm": row["Tm"], "Lev": row.get("Lev"),
                            "category": "IP Milestone", "text": f"Reached {threshold} innings pitched this season",
                        })

    milestones.sort(key=lambda m: _MILESTONE_PRIORITY.get(m["category"], 99))
    return milestones


@st.cache_data(show_spinner=False, max_entries=2)
def load_todays_games(db_mtime_val: float) -> pd.DataFrame:
    """Today's schedule from the MLB Stats API (fetched daily by ingest,
    separate from the pybaseball/bref data everything else uses)."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            return pd.read_sql("SELECT * FROM todays_games", conn)
        except pd.errors.DatabaseError:
            return pd.DataFrame()


@st.cache_data(show_spinner=False, ttl=20, max_entries=2)
def load_live_scores(date_str: str) -> dict:
    """Live current score + inning state for every game on `date_str`, keyed
    by game_pk — a single schedule API call (hydrate=linescore), separate
    from the daily-ingested todays_games table (which only ever has each
    game's pre-game state: records, probable pitcher). Short TTL so scores
    actually move as games progress, without hitting the API on literally
    every script rerun."""
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": date_str, "hydrate": "linescore"},
            timeout=10,
        )
        resp.raise_for_status()
        dates = resp.json().get("dates", [])
        games = dates[0].get("games", []) if dates else []
    except Exception:
        return {}

    scores = {}
    for g in games:
        away, home = g["teams"]["away"], g["teams"]["home"]
        linescore = g.get("linescore") or {}
        inning_text = None
        if linescore.get("currentInningOrdinal"):
            half = "Top" if linescore.get("isTopInning") else "Bottom"
            inning_text = f"{half} {linescore['currentInningOrdinal']}"
        offense = linescore.get("offense") or {}
        scores[g.get("gamePk")] = {
            "away_score": away.get("score"),
            "home_score": home.get("score"),
            "status": g.get("status", {}).get("detailedState"),
            "inning": inning_text,
            "outs": linescore.get("outs"),
            # Each base's runner name (or None if empty) rather than a plain
            # bool — style.game_state_html uses the name for a hover
            # tooltip, but still just checks truthiness for occupied/empty,
            # so this is a drop-in replacement for the old True/False.
            # Only meaningful when the game is actually in progress (outs
            # is not None); the offense dict is present-but-baseless
            # between innings/at-bats too, so a missing key just means
            # "empty" rather than "unknown".
            "bases": {
                "first": (offense.get("first") or {}).get("fullName"),
                "second": (offense.get("second") or {}).get("fullName"),
                "third": (offense.get("third") or {}).get("fullName"),
            },
        }
    return scores


@st.cache_data(show_spinner=False, ttl=8, max_entries=10)
def load_live_pitch_tracker(game_pk) -> dict:
    """The CURRENT at-bat's pitches so far — plate location, type, speed,
    and result — plus who's up, for the Game Center page's live strike
    zone chart. A separate, shorter-TTL fetch from load_live_scores (8s vs
    20s) since a single at-bat can turn over several pitches in that
    window and the whole point of this view is watching them land one at
    a time. Hits the full live-feed endpoint (not the lighter schedule
    hydrate used elsewhere) since that's the only place MLB exposes
    pitch-level plate coordinates. Returns {} if the fetch fails or the
    game has no current play yet (hasn't started)."""
    try:
        resp = requests.get(
            f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live", timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        return {}

    current = (raw.get("liveData") or {}).get("plays", {}).get("currentPlay")
    if not current:
        return {}

    matchup = current.get("matchup") or {}
    pitches = []
    for event in current.get("playEvents", []):
        if not event.get("isPitch"):
            continue
        pitch_data = event.get("pitchData") or {}
        coords = pitch_data.get("coordinates") or {}
        details = event.get("details") or {}
        if "pX" not in coords or "pZ" not in coords:
            continue
        pitches.append({
            "number": event.get("pitchNumber"),
            "px": coords["pX"],
            "pz": coords["pZ"],
            "sz_top": pitch_data.get("strikeZoneTop"),
            "sz_bottom": pitch_data.get("strikeZoneBottom"),
            "speed": pitch_data.get("startSpeed"),
            "pitch_type": (details.get("type") or {}).get("description") or "Pitch",
            "description": details.get("description") or "",
            "is_strike": bool(details.get("isStrike")),
            "is_ball": bool(details.get("isBall")),
            "is_in_play": bool(details.get("isInPlay")),
        })

    return {
        "batter": (matchup.get("batter") or {}).get("fullName"),
        "pitcher": (matchup.get("pitcher") or {}).get("fullName"),
        "count": current.get("count") or {},
        "pitches": pitches,
    }


@st.cache_data(show_spinner=False, ttl=30, max_entries=10)
def load_due_up(game_pk) -> dict:
    """Who's up now / on deck / in the hole, plus the pitcher they're
    facing (with throwing hand), for Game Center's "Due Up" cards. From
    the live feed's linescore, which tracks the batting order live —
    returns {} for games not in progress or on any fetch failure."""
    try:
        resp = requests.get(
            f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live", timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        return {}

    line = (raw.get("liveData") or {}).get("linescore") or {}
    offense = line.get("offense") or {}
    defense = line.get("defense") or {}
    pitcher = defense.get("pitcher") or {}
    if not pitcher.get("id"):
        return {}

    # Throwing hand lives in gameData's player registry, not the linescore.
    players = (raw.get("gameData") or {}).get("players") or {}
    hand = (
        (players.get(f"ID{pitcher['id']}") or {}).get("pitchHand") or {}
    ).get("code") or ""

    due = []
    for slot, label in [("batter", "At Bat"), ("onDeck", "On Deck"), ("inHole", "In the Hole")]:
        p = offense.get(slot) or {}
        if p.get("id"):
            due.append({"mlbID": int(p["id"]), "name": p.get("fullName", ""), "label": label})
    if not due:
        return {}
    return {
        "pitcher_id": int(pitcher["id"]),
        "pitcher_name": pitcher.get("fullName", ""),
        "pitcher_hand": hand,
        "due": due,
    }


@st.cache_data(show_spinner=False, ttl=30, max_entries=10)
def load_current_pitchers(game_pk) -> list[dict]:
    """Each team's pitcher currently in the game — the one on the mound
    right now for the fielding side, and the batting side's most recent
    (still-active) pitcher — with tonight's line and season numbers, for
    Game Center's "On the Mound" cards. From the live feed's boxscore:
    the per-team `pitchers` list is in order of appearance, so its last
    entry is that team's current arm. Returns [] for games not in
    progress or on any fetch failure."""
    try:
        resp = requests.get(
            f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live", timeout=10,
        )
        resp.raise_for_status()
        live = resp.json().get("liveData", {})
    except Exception:
        return []

    line = live.get("linescore") or {}
    on_mound_id = ((line.get("defense") or {}).get("pitcher") or {}).get("id")
    box_teams = (live.get("boxscore") or {}).get("teams") or {}

    out = []
    for side in ("away", "home"):
        team = box_teams.get(side) or {}
        pitcher_ids = team.get("pitchers") or []
        if not pitcher_ids:
            continue
        pid = pitcher_ids[-1]
        player = (team.get("players") or {}).get(f"ID{pid}") or {}
        game_stats = (player.get("stats") or {}).get("pitching") or {}
        season_stats = (player.get("seasonStats") or {}).get("pitching") or {}
        out.append({
            "side": side,
            "mlbID": int(pid),
            "name": (player.get("person") or {}).get("fullName", ""),
            "on_mound": pid == on_mound_id,
            "game": {
                "ip": game_stats.get("inningsPitched"),
                "h": game_stats.get("hits"),
                "er": game_stats.get("earnedRuns"),
                "so": game_stats.get("strikeOuts"),
                "bb": game_stats.get("baseOnBalls"),
                "pitches": game_stats.get("numberOfPitches"),
            },
            "season": {
                "era": season_stats.get("era"),
                "whip": season_stats.get("whip"),
                "ip": season_stats.get("inningsPitched"),
                "so": season_stats.get("strikeOuts"),
            },
        })
    return out


@st.cache_data(show_spinner=False, ttl=15, max_entries=10)
def load_win_probability(game_pk) -> pd.DataFrame:
    """Home-team win probability after every completed plate appearance, for
    the Game Center page's live win-probability chart AND its "Play of the
    Game" callout (the play description/batter are carried along here too
    since this endpoint already returns them alongside the probability —
    no reason for a second fetch just to label the biggest swing). MLB's
    main live-feed endpoint doesn't carry win probability — it's only on
    this separate dedicated endpoint. Returns an empty DataFrame (not an
    error) if the fetch fails or the game hasn't completed any plate
    appearances yet."""
    cols = [
        "atBatIndex", "inning", "half_inning", "home_win_pct", "away_score", "home_score",
        "description", "batter",
    ]
    try:
        resp = requests.get(
            f"https://statsapi.mlb.com/api/v1/game/{game_pk}/winProbability", timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        return pd.DataFrame(columns=cols)

    rows = []
    for play in raw:
        about = play.get("about") or {}
        if not about.get("isComplete") or "homeTeamWinProbability" not in play:
            continue
        result = play.get("result") or {}
        rows.append({
            "atBatIndex": about.get("atBatIndex"),
            "inning": about.get("inning"),
            "half_inning": about.get("halfInning"),
            "home_win_pct": play["homeTeamWinProbability"],
            "away_score": result.get("awayScore"),
            "home_score": result.get("homeScore"),
            "description": result.get("description"),
            "batter": ((play.get("matchup") or {}).get("batter") or {}).get("fullName"),
        })
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


# --- In-house win probability model (the WPA engine) ------------------------
# Trained offline by ingest/train_wp_model.py from five seasons of real
# play-by-play; app/wp_model.json holds P(home wins) and a leverage index
# for every observed game state. Serving is a dict lookup — no ML runtime.

WP_MODEL_PATH = Path(__file__).resolve().parent / "wp_model.json"


@st.cache_resource(show_spinner=False)
def load_wp_model() -> dict | None:
    try:
        return json.loads(WP_MODEL_PATH.read_text())
    except Exception:
        return None


def wp_lookup(model: dict, inning: int, half: int, outs: int, base: int, diff: int) -> tuple[float, float]:
    """(win probability for the HOME team, leverage index) for a game
    state. half: 0=top, 1=bottom. base: bitmask 1st=1/2nd=2/3rd=4.
    Unseen exact states fall back to the coarse (inning, half, diff)
    average baked into the artifact."""
    cfg = model["config"]
    inning_c = min(int(inning), cfg["max_inning"])
    diff_c = max(-cfg["max_diff"], min(cfg["max_diff"], int(diff)))
    key = f"{inning_c}|{half}|{outs}|{base}|{diff_c}"
    entry = model["states"].get(key)
    if entry:
        return float(entry[0]), float(entry[1])
    coarse = model["fallback"].get(f"{inning_c}|{half}|{diff_c}")
    if coarse is not None:
        return float(coarse), float(model.get("mean_li", 0.03))
    return 0.5 + 0.04 * max(-5, min(5, diff_c)), float(model.get("mean_li", 0.03))


@st.cache_data(show_spinner=False, ttl=3600 * 6, max_entries=50)
def load_head_to_head(batter_id: int, pitcher_id: int) -> dict:
    """Career batter-vs-pitcher matchup totals from the MLB Stats API, for
    the Compare page's head-to-head section when one player is a hitter
    and the other a pitcher. Returns the raw stat dict ({} if they've
    never faced each other or the fetch fails)."""
    try:
        resp = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{int(batter_id)}/stats",
            params={"stats": "vsPlayerTotal", "opposingPlayerId": int(pitcher_id), "group": "hitting"},
            timeout=10,
        )
        resp.raise_for_status()
        splits = resp.json().get("stats", [{}])[0].get("splits", [])
    except Exception:
        return {}
    return splits[0].get("stat", {}) if splits else {}


def current_leverage(game_pk) -> dict | None:
    """Leverage of the CURRENT state of a live game, for Game Center's
    'how tense is this moment' badge. Returns {li, ratio, wp_home} or None."""
    model = load_wp_model()
    if model is None:
        return None
    try:
        resp = requests.get(
            f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live", timeout=10
        )
        resp.raise_for_status()
        live = resp.json().get("liveData", {})
    except Exception:
        return None
    line = live.get("linescore") or {}
    if (line.get("inningState") or "") not in ("Top", "Bottom"):
        return None
    offense = line.get("offense") or {}
    base = (
        (1 if offense.get("first") else 0)
        + (2 if offense.get("second") else 0)
        + (4 if offense.get("third") else 0)
    )
    inning = line.get("currentInning") or 1
    half = 1 if line.get("inningState") == "Bottom" else 0
    outs = min(line.get("outs") or 0, 2)
    teams = line.get("teams") or {}
    diff = (teams.get("home", {}).get("runs") or 0) - (teams.get("away", {}).get("runs") or 0)
    p, li = wp_lookup(model, inning, half, outs, base, diff)
    mean_li = model.get("mean_li") or 0.03
    return {"li": li, "ratio": li / mean_li if mean_li else 1.0, "wp_home": p}


@st.cache_data(show_spinner=False, max_entries=4)
def load_wpa_batting(season: int, db_mtime_val: float) -> pd.DataFrame:
    return _load_optional_table("wpa_batting", season, db_mtime_val)


@st.cache_data(show_spinner=False, max_entries=4)
def load_wpa_pitching(season: int, db_mtime_val: float) -> pd.DataFrame:
    return _load_optional_table("wpa_pitching", season, db_mtime_val)


@st.cache_data(show_spinner=False, max_entries=4)
def load_wpa_top_plays(season: int, db_mtime_val: float) -> pd.DataFrame:
    return _load_optional_table("wpa_top_plays", season, db_mtime_val)


@st.cache_data(show_spinner=False, ttl=3600 * 24, max_entries=500)
def load_schedule_for_date(date_str: str) -> pd.DataFrame:
    """Every game played on `date_str` — any past date, not just today —
    fetched directly from the MLB Stats API (not part of the daily ingest,
    which only ever pulls today's slate into the todays_games table; a
    historical lookup is rare enough per-date that fetching on demand beats
    pre-loading every date that might ever get searched). Long TTL since a
    past date's final scores never change once the games are over."""
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": date_str, "hydrate": "team,linescore"},
            timeout=10,
        )
        resp.raise_for_status()
        dates = resp.json().get("dates", [])
        games = dates[0].get("games", []) if dates else []
    except Exception:
        return pd.DataFrame()

    rows = []
    for g in games:
        away, home = g["teams"]["away"], g["teams"]["home"]
        rows.append({
            "game_pk": g.get("gamePk"),
            "status": g.get("status", {}).get("detailedState"),
            "away_team": away["team"]["name"],
            "home_team": home["team"]["name"],
            "away_abbr": teams.abbr_for_team_id(away["team"]["id"]),
            "home_abbr": teams.abbr_for_team_id(home["team"]["id"]),
            "away_score": away.get("score"),
            "home_score": home.get("score"),
        })
    return pd.DataFrame(rows)


# get_milestones' `category` -> the highlight taxonomy tag(s) MLB's own
# clip-tagging uses for that kind of play — used by find_milestone_highlight
# below to pick a clip that's actually ABOUT the milestone, not just any
# clip of that player from that game. SO/IP milestones have no entry (and
# so never get a video) since crossing a strikeout/innings-pitched total
# isn't itself a single taggable play the way a home run or save is.
_HIGHLIGHT_CATEGORY_TAGS = {
    "HR Milestone": {"home-run"},
    "Cycle": {"home-run"},  # closest single clip a cycle has — no dedicated "cycle" tag
    "SV Milestone": {"relief-performance"},
    "Perfect Game": {"highlight-reel-pitching", "highlight-reel-starting-pitching"},
    "No-Hitter": {"highlight-reel-pitching", "highlight-reel-starting-pitching"},
}

# load_statcast_daily_leaderboard's leaderboard keys -> taxonomy tag(s).
# "hardest_hit" and "fastest_pitch" fall back to the broadest tag for that
# side of the ball ("hitting"/"pitching") since MLB has no tag meaning
# "this specific pitch/swing" — confirmed this CAN match a clip that isn't
# literally that pitch/swing (e.g. an Automated Ball-Strike challenge clip
# carrying the right pitcher's ID and the generic "pitching" tag, not
# footage of their actual fastest pitch). The single-player-clip
# preference in _find_tagged_player_clip below cuts down how often that
# happens, but doesn't eliminate it for these two loose categories —
# unlike "longest_hr", where "home-run" IS an exact tag for that literal
# play. Re-added after being removed for exactly this reason: showing
# something (usually right, occasionally not) was preferred over showing
# nothing.
_STATCAST_HIGHLIGHT_TAGS = {
    "longest_hr": {"home-run"},
    "hardest_hit": {"home-run", "hitting"},
    "fastest_pitch": {"pitching"},
}

# Procedural/review clips that can carry a real player's ID and a broad
# category tag (e.g. "pitching") without being footage of an actual play —
# confirmed via a real "Ball 1 overturned by ABS" clip matching a
# fastest-pitch lookup this way. Excluded outright in
# _find_tagged_player_clip regardless of what else the clip is tagged.
_NON_HIGHLIGHT_TAGS = {"abs", "challenge"}


@st.cache_data(show_spinner=False, ttl=1800, max_entries=32)
def _game_highlight_items(abbr: str, date_str: str) -> list:
    """All of MLB's highlight-clip items for the game `abbr` played on
    `date_str` (schedule lookup -> game_pk -> content feed), shared by
    every clip-matching path below so one game's items are fetched once
    per half hour, not once per lookup. Returns [] on any failure."""
    schedule = load_schedule_for_date(date_str)
    if schedule.empty:
        return []
    match = schedule[(schedule["away_abbr"] == abbr) | (schedule["home_abbr"] == abbr)]
    if match.empty:
        return []
    game_pk = int(match.iloc[0]["game_pk"])
    try:
        resp = requests.get(f"https://statsapi.mlb.com/api/v1/game/{game_pk}/content", timeout=10)
        resp.raise_for_status()
        return ((resp.json().get("highlights") or {}).get("highlights") or {}).get("items", []) or []
    except Exception:
        return []


def _clip_mp4_url(item: dict) -> str | None:
    for pb in item.get("playbacks", []):
        pb_url = pb.get("url") or ""
        if pb.get("name") == "mp4Avc" or pb_url.endswith(".mp4"):
            return pb_url
    return None


def _stat_number_pattern(detail: str):
    """Compiled regex matching this stat line's own number in clip text —
    a clip whose headline/description literally contains "114.4" (mph) or
    "460-foot" IS the play the number came from, far more precisely than
    any taxonomy tag. Decimals are distinctive enough to match bare; a
    whole number (HR distance) must be followed by a feet-unit so "460"
    can't collide with some other number in unrelated text."""
    m = re.search(r"(\d+(?:\.\d+)?)", detail or "")
    if not m:
        return None
    num = m.group(1)
    if "." in num:
        return re.compile(rf"\b{re.escape(num)}\b")
    return re.compile(rf"\b{num}[-\s]?(?:ft|foot|feet)\b", re.IGNORECASE)


def _find_tagged_player_clip(mlbID, abbr: str, date_str: str, tags: set) -> str | None:
    """Shared lookup behind find_milestone_highlight/find_statcast_highlight
    — finds the player's game on `date_str` via the schedule, then searches
    that game's content/highlights for a clip tagged for both that player
    (keywordsAll's player_id) and any of `tags` (keywordsAll's taxonomy
    values), returning the first matching individual clip's direct .mp4 URL
    (playable via st.video). Among matches, a clip tagged with ONLY this
    player's ID is preferred over one tagged with several players' IDs
    (e.g. a "three players homered today" roundup) — confirmed via a real
    case where such a roundup clip (which happened to also carry an
    unrelated player's ID) beat the correct player's own individual home-
    run clip purely because it appeared first in MLB's list; a multi-player
    clip is only used as a last resort, if no individual one matches.
    Clips tagged as an Automated Ball-Strike challenge (taxonomy "abs" or
    "challenge") are skipped outright regardless of tag match — confirmed
    one such clip ("Ball 1 overturned by ABS") matched a "fastest_pitch"
    lookup purely by carrying the right player's ID and the generic
    "pitching" tag, despite having nothing to do with that pitch's speed.
    Returns None (never raises) if there's no schedule match, no content,
    or nothing tagged for both the player and the given tags — callers
    should render without a video rather than error out."""
    items = _game_highlight_items(abbr, date_str)
    fallback_url = None
    for item in items:
        keywords = item.get("keywordsAll", [])
        player_ids = {k["value"] for k in keywords if k.get("type") == "player_id"}
        if str(mlbID) not in player_ids:
            continue
        item_tags = {k["value"] for k in keywords if k.get("type") == "taxonomy"}
        if item_tags & _NON_HIGHLIGHT_TAGS:
            continue
        if not (item_tags & tags):
            continue
        url = _clip_mp4_url(item)
        if not url:
            continue
        if len(player_ids) == 1:
            return url
        if fallback_url is None:
            fallback_url = url
    return fallback_url


@st.cache_data(show_spinner=False, ttl=1800, max_entries=100)
def find_milestone_highlight(mlbID, abbr: str, date_str: str, category: str) -> str | None:
    """Best-effort highlight clip for one of get_milestones' entries — see
    _find_tagged_player_clip for how the match works, _HIGHLIGHT_CATEGORY_TAGS
    for the category->tag mapping. Deliberately NOT called from inside
    get_milestones itself, which promises "no extra network calls" — video
    lookup is a nice-to-have the Daily Digest can afford to wait on, not
    something every milestone consumer (e.g. the Home page's alert banner)
    needs to pay for. Ttl is 30min, not the hours-long cache a genuinely
    static past-date lookup could otherwise justify — a running app
    instance whose code changes underneath it (a redeploy that doesn't
    fully restart the process) would otherwise keep serving a stale
    None/wrong result from before the fix for however long the ttl is;
    confirmed this actually happened once already at the old 24h ttl."""
    tags = _HIGHLIGHT_CATEGORY_TAGS.get(category)
    if not tags:
        return None
    return _find_tagged_player_clip(mlbID, abbr, date_str, tags)


@st.cache_data(show_spinner=False, ttl=1800, max_entries=100)
def find_statcast_highlight(mlbID, abbr: str, date_str: str, kind: str, detail: str | None = None) -> str | None:
    """Best-effort highlight clip for one of load_statcast_daily_leaderboard's
    entries ("hardest_hit", "longest_hr", "fastest_pitch"). Two passes:

    1. Exact stat-number match: if `detail` (the leaderboard's own display
       line, e.g. "114.4 mph exit velo (Single)" or "460 ft home run")
       carries a number that appears verbatim in a clip's headline or
       description, that clip IS the play the number came from — more
       precise than any taxonomy tag, and it can find correctly-described
       clips the tag pass misses (MLB's tagging is inconsistent for
       non-HR plays). ABS-challenge clips stay excluded here too.
    2. Fallback: the shared player-id + taxonomy-tag match — see
       _find_tagged_player_clip and _STATCAST_HIGHLIGHT_TAGS' comment for
       why "hardest hit"/"fastest pitch" tags are inherently loose.

    Neither pass can conjure a clip MLB never produced (confirmed real
    case: a hardest-hit single with zero clips referencing the batter at
    all) — those still correctly show no video."""
    pattern = _stat_number_pattern(detail) if detail else None
    if pattern:
        for item in _game_highlight_items(abbr, date_str):
            keywords = item.get("keywordsAll", [])
            item_tags = {k["value"] for k in keywords if k.get("type") == "taxonomy"}
            if item_tags & _NON_HIGHLIGHT_TAGS:
                continue
            text = " ".join(filter(None, [item.get("headline"), item.get("description"), item.get("blurb")]))
            if pattern.search(text):
                url = _clip_mp4_url(item)
                if url:
                    return url
    tags = _STATCAST_HIGHLIGHT_TAGS.get(kind)
    if not tags:
        return None
    return _find_tagged_player_clip(mlbID, abbr, date_str, tags)


@st.cache_data(show_spinner=False, ttl=60, max_entries=20)
def load_linescore(game_pk) -> dict | None:
    """Live per-inning box score for one game, fetched on demand (not part
    of the daily ingest — there's no reason to pre-fetch a box score for
    every game when only a couple ever get clicked into). Short TTL so an
    in-progress game's score doesn't go stale for the rest of the session."""
    try:
        resp = requests.get(f"https://statsapi.mlb.com/api/v1/game/{int(game_pk)}/linescore", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


@st.cache_data(show_spinner=False, ttl=60, max_entries=20)
def load_boxscore_players(game_pk) -> dict | None:
    """Live per-player batting/pitching lines for one game (that game's
    stats only, not season totals) — fetched on demand like load_linescore,
    same short TTL so an in-progress game's lines keep moving. Returns
    {"away": {"batters": [...], "pitchers": [...]}, "home": {...}} or None
    on failure; batters are ordered by the lineup's battingOrder (subs sort
    after starters), pitchers by order of appearance."""
    try:
        resp = requests.get(f"https://statsapi.mlb.com/api/v1/game/{int(game_pk)}/boxscore", timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    def _side(side):
        team = data.get("teams", {}).get(side, {})
        players = team.get("players", {})

        batters = []
        for pid in team.get("batters", []):
            p = players.get(f"ID{pid}")
            stat = (p or {}).get("stats", {}).get("batting", {})
            if not p or not stat:
                continue
            hits = stat.get("hits", 0)
            doubles = stat.get("doubles", 0)
            triples = stat.get("triples", 0)
            homers = stat.get("homeRuns", 0)
            batters.append({
                "mlbID": p["person"]["id"],
                "Name": p["person"]["fullName"],
                "Pos": p.get("position", {}).get("abbreviation", ""),
                "AB": stat.get("atBats", 0),
                "R": stat.get("runs", 0),
                "H": hits,
                "1B": hits - doubles - triples - homers,
                "2B": doubles,
                "3B": triples,
                "HR": homers,
                "RBI": stat.get("rbi", 0),
                "BB": stat.get("baseOnBalls", 0),
                "SO": stat.get("strikeOuts", 0),
                "_order": p.get("battingOrder") or "999",
            })
        batters.sort(key=lambda b: b["_order"])
        for b in batters:
            del b["_order"]

        pitchers = []
        for pid in team.get("pitchers", []):
            p = players.get(f"ID{pid}")
            stat = (p or {}).get("stats", {}).get("pitching", {})
            if not p or not stat:
                continue
            pitchers.append({
                "Name": p["person"]["fullName"],
                "IP": stat.get("inningsPitched", "0.0"),
                "H": stat.get("hits", 0),
                "R": stat.get("runs", 0),
                "ER": stat.get("earnedRuns", 0),
                "BB": stat.get("baseOnBalls", 0),
                "SO": stat.get("strikeOuts", 0),
                "Pitches": stat.get("numberOfPitches", 0),
            })
        return {"batters": batters, "pitchers": pitchers}

    return {"away": _side("away"), "home": _side("home")}


def _parse_innings_pitched(ip_str) -> float:
    """MLB's boxscore API reports IP as e.g. "6.1"/"6.2", where the part
    after the dot is thirds of an inning (1 out, 2 outs), not a decimal —
    "6.1" is 6⅓ innings, not 6.1. Converts to a true float for comparisons."""
    try:
        whole, _, frac = str(ip_str).partition(".")
        return int(whole or 0) + int(frac or 0) / 3
    except (ValueError, TypeError):
        return 0.0


def _format_innings_pitched(total_ip: float) -> str:
    """Inverse of _parse_innings_pitched — a true float back into MLB's
    "whole.thirds" box-score notation (6⅓ innings displays as "6.1", not
    the misleading decimal "6.3")."""
    whole = int(total_ip)
    thirds = round((total_ip - whole) * 3)
    if thirds == 3:
        whole, thirds = whole + 1, 0
    return f"{whole}.{thirds}"


@st.cache_data(show_spinner=False, ttl=20, max_entries=4)
def no_hitter_watch(date_str: str) -> list[dict]:
    """No-hitter/perfect-game bids for `date_str`'s games, both "in
    progress" (a team's pitching staff — starter solo, or a combined
    effort — is 6.0+ IP into one, the threshold below which an early no-hit
    bid is too common to be notable) and "achieved" (the staff finished a
    real 9+ inning game with zero hits allowed). Achieved entries are
    derived fresh from the same boxscore call every time this runs, not
    stored anywhere — since a finished game's boxscore doesn't change for
    the rest of the day, that's what makes the achieved banner "stick"
    without any extra state. Approximate for the perfect-game flag: the
    boxscore API doesn't expose hit-by-pitch or errors, so it only checks
    hits + walks allowed — good enough for a home-page heads-up, not
    official scoring."""
    games = load_todays_games(db_mtime())
    if games.empty:
        return []
    live_scores = load_live_scores(date_str)

    watches = []
    for _, g in games.iterrows():
        live = live_scores.get(g["game_pk"], {})
        status = live.get("status") or g.get("status")
        if status not in ("In Progress", "Final", "Game Over"):
            continue
        box = load_boxscore_players(g["game_pk"])
        if not box:
            continue
        for side, pitching_team, pitching_abbr, opp_team in (
            ("away", g["away_team"], g["away_abbr"], g["home_team"]),
            ("home", g["home_team"], g["home_abbr"], g["away_team"]),
        ):
            pitchers = box.get(side, {}).get("pitchers", [])
            if not pitchers:
                continue
            total_h = sum(p["H"] for p in pitchers)
            if total_h > 0:
                continue
            total_ip = sum(_parse_innings_pitched(p["IP"]) for p in pitchers)
            total_bb = sum(p["BB"] for p in pitchers)
            is_perfect = total_bb == 0
            if status == "In Progress":
                if total_ip < 6.0:
                    continue
                kind = "perfect_watch" if is_perfect else "no_hitter_watch"
            else:
                if total_ip < 9.0:
                    continue
                kind = "perfect_achieved" if is_perfect else "no_hitter_achieved"
            watches.append({
                "kind": kind,
                "game_pk": g["game_pk"],
                "pitching_team": pitching_team,
                "pitching_abbr": pitching_abbr,
                "opponent": opp_team,
                "pitcher_names": [p["Name"] for p in pitchers],
                "combined": len(pitchers) > 1,
                "ip": total_ip,
                "ip_display": _format_innings_pitched(total_ip),
                "walks": total_bb,
                "inning": live.get("inning"),
            })
    return watches


_CYCLE_HIT_TYPES = (("1B", "single"), ("2B", "double"), ("3B", "triple"), ("HR", "home run"))


@st.cache_data(show_spinner=False, ttl=20, max_entries=4)
def batting_milestone_watch(date_str: str) -> list[dict]:
    """Cycle and 4-homer bids for `date_str`'s games: "watch" entries while
    the game is in progress (one hit-type away from the cycle; sitting on 3
    HR), "achieved" entries once it actually happens — achieved persists
    for the rest of the day the same way no_hitter_watch's does (derived
    fresh from the still-queryable final boxscore, not stored). A stalled
    3-HR bid deliberately does NOT get an achieved entry once the game goes
    final — only an actual 4th homer keeps the banner around."""
    games = load_todays_games(db_mtime())
    if games.empty:
        return []
    live_scores = load_live_scores(date_str)

    watches = []
    for _, g in games.iterrows():
        live = live_scores.get(g["game_pk"], {})
        status = live.get("status") or g.get("status")
        if status not in ("In Progress", "Final", "Game Over"):
            continue
        box = load_boxscore_players(g["game_pk"])
        if not box:
            continue
        for side, team, abbr, opp_team in (
            ("away", g["away_team"], g["away_abbr"], g["home_team"]),
            ("home", g["home_team"], g["home_abbr"], g["away_team"]),
        ):
            for b in box.get(side, {}).get("batters", []):
                counts = {label: b.get(key, 0) for key, label in _CYCLE_HIT_TYPES}
                types_hit = sum(1 for c in counts.values() if c >= 1)
                base = {
                    "game_pk": g["game_pk"], "mlbID": b["mlbID"], "name": b["Name"],
                    "team": team, "abbr": abbr, "opponent": opp_team, "inning": live.get("inning"),
                }
                if types_hit == 4:
                    watches.append({**base, "kind": "cycle_achieved"})
                elif types_hit == 3 and status == "In Progress":
                    missing = next(label for label, c in counts.items() if c == 0)
                    watches.append({**base, "kind": "cycle_watch", "missing": missing})

                hr = counts["home run"]
                if hr >= 4:
                    watches.append({**base, "kind": "four_hr_achieved", "hr": hr})
                elif hr == 3 and status == "In Progress":
                    watches.append({**base, "kind": "four_hr_watch", "hr": hr})
    return watches


# A blowout only makes the "On This Day" cut at a 15+ run margin (e.g.
# 15-0, 17-2) — 10 was too common to feel notable.
ON_THIS_DAY_BLOWOUT_MARGIN = 15


def _game_player_highlights(game_pk, years_ago, year, away_name, home_name):
    """Batting/pitching milestones from one historical game's boxscore:
    cycles, 3+ HR games, 5+ hit games, no-hitters, and perfect games. Looked
    up team-by-team so a combined no-hitter/perfect game (multiple pitchers
    together) is caught, not just a single starter's line. Best-effort —
    returns [] on any fetch failure rather than raising, since this runs
    once per historical game found for the date."""
    try:
        resp = requests.get(f"https://statsapi.mlb.com/api/v1/game/{int(game_pk)}/boxscore", timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    teams_data = data.get("teams", {})
    names = {"away": away_name, "home": home_name}
    highlights = []

    for side, opp_side in (("away", "home"), ("home", "away")):
        team = teams_data.get(side, {})
        players = team.get("players", {})

        for pid in team.get("batters", []):
            p = players.get(f"ID{pid}")
            stat = (p or {}).get("stats", {}).get("batting", {})
            if not p or not stat:
                continue
            hits = stat.get("hits", 0)
            doubles, triples, hrs = stat.get("doubles", 0), stat.get("triples", 0), stat.get("homeRuns", 0)
            singles = hits - doubles - triples - hrs
            name = p["person"]["fullName"]
            base = {"years_ago": years_ago, "year": year, "player": name, "team": names[side], "mlbID": p["person"]["id"]}
            if singles >= 1 and doubles >= 1 and triples >= 1 and hrs >= 1:
                highlights.append({**base, "kind": "Cycle", "text": f"Hit for the cycle ({hits}-for-{stat.get('atBats', hits)})"})
            if hrs >= 3:
                highlights.append({**base, "kind": "3+ HR", "text": f"{hrs} home runs"})
            if hits >= 5:
                highlights.append({**base, "kind": "5+ Hits", "text": f"{hits}-for-{stat.get('atBats', hits)}"})

        # Team-level pitching aggregate (not per-pitcher) so a combined
        # no-hitter/perfect game — several pitchers together — still counts.
        pitcher_ids = team.get("pitchers", [])
        if not pitcher_ids:
            continue
        total_h = total_bb = total_hbp = total_outs = 0
        pitcher_names, last_pitcher_id = [], None
        for pid in pitcher_ids:
            p = players.get(f"ID{pid}")
            stat = (p or {}).get("stats", {}).get("pitching", {})
            if not p or not stat:
                continue
            total_h += stat.get("hits", 0)
            total_bb += stat.get("baseOnBalls", 0)
            total_hbp += stat.get("hitBatsmen", 0)
            total_outs += stat.get("outs", 0)
            pitcher_names.append(p["person"]["fullName"])
            last_pitcher_id = p["person"]["id"]
        # A no-hitter/perfect game requires the pitching side to have
        # completed at least a full 9-inning game (outs >= 27) — excludes
        # shortened/rain-called games, which don't count in the record book.
        if total_outs < 27 or total_h > 0:
            continue
        combined = len(pitcher_names) > 1
        pitcher_label = f"{pitcher_names[-1]} (combined)" if combined else pitcher_names[-1]
        base = {
            "years_ago": years_ago, "year": year, "player": pitcher_label, "team": names[side],
            # A combined effort has no single face for the card — only a
            # lone starter's complete game gets a headshot.
            "mlbID": None if combined else last_pitcher_id,
        }
        if total_bb == 0 and total_hbp == 0:
            highlights.append({**base, "kind": "Perfect Game", "text": f"Perfect game vs. {names[opp_side]}"})
        else:
            highlights.append({**base, "kind": "No-Hitter", "text": f"No-hitter vs. {names[opp_side]}"})

    return highlights


def _fetch_on_this_day_schedule(args) -> tuple:
    """One year's worth of load_on_this_day's work — its own schedule
    fetch, split out so the `years_back` years can run concurrently (see
    below) instead of one after another."""
    current_year, month, day, years_ago = args
    year = current_year - years_ago
    try:
        d = date(year, month, day)
    except ValueError:
        return years_ago, year, []  # Feb 29 in a non-leap year
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": d.isoformat(), "hydrate": "linescore"},
            timeout=10,
        )
        resp.raise_for_status()
        dates_ = resp.json().get("dates", [])
        games = dates_[0].get("games", []) if dates_ else []
    except Exception:
        games = []
    return years_ago, year, games


@st.cache_data(show_spinner=False, ttl=3600 * 24, max_entries=1)
def load_on_this_day(month: int, day: int, years_back: int = 15) -> dict:
    """Real completed MLB games played on this calendar date in each of the
    past `years_back` years, plus notable player milestones from those
    games (cycles, 3+ HR games, 5+ hit games, no-hitters, perfect games) —
    cached a full day since "today" only changes once daily. Game scores
    come from one schedule API call per year (hydrate=linescore); player
    milestones require an extra boxscore call per completed game found
    (there's no way to know a cycle happened without looking at the box
    score) — up to a few hundred requests total once a day, not per page
    view, but run through thread pools (both the per-year schedule calls
    and the per-game boxscore calls are independent I/O-bound requests
    with nothing to gain from going one at a time) rather than serially,
    which was the actual dominant cause of the Daily Digest's slow first
    load each day — this dwarfed every other section's cost combined.
    Returns {"games": [...], "highlights": [...]}; a blowout in "games" is
    flagged at a ON_THIS_DAY_BLOWOUT_MARGIN+ run margin."""
    current_year = today_pacific().year
    with ThreadPoolExecutor(max_workers=years_back) as pool:
        year_results = list(pool.map(
            _fetch_on_this_day_schedule,
            [(current_year, month, day, years_ago) for years_ago in range(1, years_back + 1)],
        ))

    games_out = []
    finished_games = []
    for years_ago, year, games in year_results:
        for g in games:
            if g.get("status", {}).get("codedGameState") != "F":
                continue
            away, home = g["teams"]["away"], g["teams"]["home"]
            away_score, home_score = away.get("score"), home.get("score")
            if away_score is None or home_score is None:
                continue
            margin = abs(away_score - home_score)
            away_name, home_name = away["team"]["name"], home["team"]["name"]
            games_out.append({
                "years_ago": years_ago,
                "year": year,
                "away_team": away_name,
                "home_team": home_name,
                "away_score": int(away_score),
                "home_score": int(home_score),
                "blowout": margin >= ON_THIS_DAY_BLOWOUT_MARGIN,
            })
            finished_games.append((g.get("gamePk"), years_ago, year, away_name, home_name))

    highlights_out = []
    if finished_games:
        with ThreadPoolExecutor(max_workers=20) as pool:
            for result in pool.map(lambda args: _game_player_highlights(*args), finished_games):
                highlights_out.extend(result)
    return {"games": games_out, "highlights": highlights_out}


MILB_LEVELS = {
    "Triple-A": 11,
    "Double-A": 12,
    "High-A": 13,
    "Single-A": 14,
    "Rookie": 16,
}


@st.cache_data(show_spinner=False, ttl=3600 * 24, max_entries=4)
def load_milb_parent_orgs(season: int) -> dict:
    """MiLB team id -> parent MLB organization abbreviation, across every
    level — the affiliation map behind the Org Pipeline view ("show me
    every Yankees farmhand"). One teams call per level, cached a day
    (affiliations basically never change mid-season)."""
    mapping = {}
    for sport_id in MILB_LEVELS.values():
        try:
            resp = requests.get(
                "https://statsapi.mlb.com/api/v1/teams",
                params={"sportId": sport_id, "season": season}, timeout=15,
            )
            resp.raise_for_status()
            for t in resp.json().get("teams", []):
                abbr = teams.abbr_for_team_id(t.get("parentOrgId"))
                if t.get("id") and abbr:
                    mapping[t["id"]] = abbr
        except Exception:
            continue
    return mapping


@st.cache_data(show_spinner=False, ttl=3600 * 6, max_entries=40)
def load_milb_stats(sport_id: int, group: str, season: int) -> pd.DataFrame:
    """Real per-player minor-league season stats for one level/group/season
    — live-fetched from the MLB Stats API on demand rather than backfilled
    into the daily ingest like the MLB pages; this is a lighter "lesser
    version" of the main site for the minors, current-ish seasons only, no
    multi-year history. `playerPool=ALL` is required — the endpoint's
    default only returns ~30 "qualified" leaders, dropping almost
    everyone who played."""
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/stats",
            params={
                "stats": "season", "group": group, "sportId": sport_id, "season": season,
                "limit": 5000, "playerPool": "ALL",
            },
            timeout=20,
        )
        resp.raise_for_status()
        splits = resp.json().get("stats", [{}])[0].get("splits", [])
    except Exception:
        return pd.DataFrame()

    rows = []
    for s in splits:
        stat = s.get("stat", {})
        row = {
            "mlbID": s.get("player", {}).get("id"),
            "Name": s.get("player", {}).get("fullName"),
            "Tm": s.get("team", {}).get("name"),
            "team_id": s.get("team", {}).get("id"),
            "League": s.get("league", {}).get("name"),
            "Age": stat.get("age"),
        }
        if group == "hitting":
            row.update({
                "G": stat.get("gamesPlayed"), "PA": stat.get("plateAppearances"), "AB": stat.get("atBats"),
                "R": stat.get("runs"), "H": stat.get("hits"), "2B": stat.get("doubles"), "3B": stat.get("triples"),
                "HR": stat.get("homeRuns"), "RBI": stat.get("rbi"), "BB": stat.get("baseOnBalls"),
                "SO": stat.get("strikeOuts"), "SB": stat.get("stolenBases"),
                "AVG": stat.get("avg"), "OBP": stat.get("obp"), "SLG": stat.get("slg"), "OPS": stat.get("ops"),
            })
        else:
            row.update({
                "G": stat.get("gamesPitched"), "GS": stat.get("gamesStarted"), "W": stat.get("wins"),
                "L": stat.get("losses"), "SV": stat.get("saves"), "IP": stat.get("inningsPitched"),
                "ERA": stat.get("era"), "WHIP": stat.get("whip"), "SO": stat.get("strikeOuts"),
                "BB": stat.get("baseOnBalls"), "HR": stat.get("homeRuns"),
            })
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    numeric_cols = [c for c in df.columns if c not in ("mlbID", "Name", "Tm", "League")]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    return df


# Converts Statcast's raw hc_x/hc_y hit-coordinate fields (an internal SVG
# pixel-ish coordinate space, home plate near (125, 198)) into approximate
# feet from home plate, with (0, 0) = home plate and +y = toward center
# field. This is the standard community-derived transform (matches
# hit_distance_sc to within ~1-2% on real data) — Statcast doesn't publish
# real lat/lon-style coordinates, only this SVG space.
_HC_X0, _HC_Y0, _HC_SCALE = 125.42, 198.27, 2.495

# Groups Statcast's granular `events` values into the handful of outcomes a
# spray chart actually distinguishes by color — everything that isn't a hit
# (outs, double plays, fielder's choice, sac flies, errors) is just "Out"
# except a fielding error, which gets its own color since "reached on an
# error" reads differently than "made an out" on a spray chart.
_SPRAY_EVENT_LABELS = {
    "single": "Single", "double": "Double", "triple": "Triple", "home_run": "Home Run",
    "field_error": "Error",
}
SPRAY_EVENT_COLORS = {
    "Single": "#7CFC9A", "Double": "#3B82F6", "Triple": "#C084FC", "Home Run": "#F5B942",
    "Error": "#F87171", "Out": "#6B7280", "In Play": "#FAFAFA",
}


@st.cache_data(show_spinner=False, ttl=30, max_entries=30)
def load_game_batted_balls(game_pk) -> pd.DataFrame:
    """Every ball put in play by EITHER team in one game — LIVE, from
    MLB's own play-by-play feed (the same endpoint behind the Live Pitch
    Tracker), for Game Center's 2D/3D batted-ball charts. An earlier
    version of this fed from Baseball Savant's per-game export
    (pybaseball's statcast_single_game) and had to be gated to finished
    games, because that export is confirmed EMPTY until well after a game
    ends; the live feed's per-play hitData has no such lag — it's what
    MLB's own Gameday spray chart renders from. Verified against a
    finished game that the feed's hitData is the same data in the same
    coordinate space: exactly 53 balls in play in both sources, with
    coordX/coordY numerically equal to Savant's hc_x/hc_y (within
    rounding), so the existing _HC_X0/_HC_Y0/_HC_SCALE calibration
    applies unchanged. Only events flagged isInPlay are counted (fouls
    aren't charted); a ball in play whose plate appearance hasn't
    resolved yet (mid-play, live) is labeled "In Play" until the feed
    assigns the outcome — at most one point, corrected within a refresh.
    Short ttl so the chart grows pitch-by-pitch during live games.
    Returns empty (never raises) on fetch failure or before first pitch."""
    cols = ["x_ft", "y_ft", "outcome", "launch_speed", "launch_angle",
            "hit_distance_sc", "batter_name", "team_abbr"]
    try:
        resp = requests.get(
            f"https://statsapi.mlb.com/api/v1.1/game/{int(game_pk)}/feed/live", timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        return pd.DataFrame(columns=cols)

    gd_teams = (raw.get("gameData") or {}).get("teams", {})
    # "Top" of an inning = away team batting, "bottom" = home team.
    batting_abbr = {
        "top": (gd_teams.get("away") or {}).get("abbreviation"),
        "bottom": (gd_teams.get("home") or {}).get("abbreviation"),
    }
    hit_labels = {"Single", "Double", "Triple", "Home Run"}
    rows = []
    for play in (raw.get("liveData") or {}).get("plays", {}).get("allPlays", []) or []:
        event = (play.get("result") or {}).get("event")
        batter = ((play.get("matchup") or {}).get("batter") or {}).get("fullName")
        half = (play.get("about") or {}).get("halfInning")
        for ev in play.get("playEvents", []):
            if not (ev.get("details") or {}).get("isInPlay"):
                continue
            hd = ev.get("hitData") or {}
            coords = hd.get("coordinates") or {}
            if coords.get("coordX") is None or coords.get("coordY") is None:
                continue
            if event in hit_labels:
                outcome = event
            elif event == "Field Error":
                outcome = "Error"
            elif event:
                outcome = "Out"
            else:
                outcome = "In Play"
            rows.append({
                "x_ft": (coords["coordX"] - _HC_X0) * _HC_SCALE,
                "y_ft": (_HC_Y0 - coords["coordY"]) * _HC_SCALE,
                "outcome": outcome,
                "launch_speed": hd.get("launchSpeed"),
                "launch_angle": hd.get("launchAngle"),
                "hit_distance_sc": hd.get("totalDistance"),
                "batter_name": batter,
                "team_abbr": batting_abbr.get(half),
            })
    return pd.DataFrame(rows, columns=cols)


@st.cache_data(show_spinner=False, ttl=3600 * 6, max_entries=30)
def player_batted_ball_events(mlbID: int, season: int) -> pd.DataFrame:
    """Every ball a batter has put in play in a season, with a plot-ready
    (x_ft, y_ft) landing position (see _HC_X0/_HC_Y0/_HC_SCALE) AND its
    plate location (px, pz, sz_top, sz_bottom — same field names
    strike_zone_chart expects) plus a grouped outcome label. Landing
    position powers the player page's spray chart; plate location powers
    its hot/cold zone heatmap (where they hit it hardest, not where it
    landed) — both views share this one fetch rather than each pulling
    Statcast separately. Live-fetched from Baseball Savant via pybaseball
    (pitch-level Statcast data isn't part of the daily ingest — it's heavy
    and most players' pages are never visited, so backfilling it for
    everyone would be wasted work); pybaseball is imported lazily here so
    pages that don't need it don't pay its import cost. Returns columns:
    x_ft, y_ft, outcome, launch_speed, launch_angle, hit_distance_sc, px,
    pz, sz_top, sz_bottom — empty if the fetch fails or the player has no
    batted-ball data that season."""
    from pybaseball import statcast_batter

    cols = [
        "x_ft", "y_ft", "outcome", "launch_speed", "launch_angle", "hit_distance_sc",
        "px", "pz", "sz_top", "sz_bottom",
    ]
    today = today_pacific()
    start_dt = date(season, 1, 1)
    end_dt = date(season, 12, 31) if season < today.year else today
    if start_dt > end_dt:
        return pd.DataFrame(columns=cols)

    try:
        raw = statcast_batter(start_dt.isoformat(), end_dt.isoformat(), int(mlbID))
    except Exception:
        return pd.DataFrame(columns=cols)

    if raw.empty:
        return pd.DataFrame(columns=cols)

    bb = raw.dropna(subset=["hc_x", "hc_y", "events"]).copy()
    if bb.empty:
        return pd.DataFrame(columns=cols)

    bb["x_ft"] = (bb["hc_x"] - _HC_X0) * _HC_SCALE
    bb["y_ft"] = (_HC_Y0 - bb["hc_y"]) * _HC_SCALE
    bb["outcome"] = bb["events"].map(_SPRAY_EVENT_LABELS).fillna("Out")
    bb = bb.rename(columns={"plate_x": "px", "plate_z": "pz", "sz_bot": "sz_bottom"})
    return bb[cols].reset_index(drop=True)


_QOC_HARD_HIT_MPH = 95.0
# Fixed MLB league-average reference points, NOT computed live from a
# full-league Statcast pull — doing that would mean fetching every
# qualified batter's season data just to build the scale, the same
# "thousands of API calls" cost a season-wide Clutch stat was ruled out
# for. Approximate recent-season MLB averages; stable enough year to
# year that a fixed reference point keeps the score meaningful without
# needing to be recomputed.
_QOC_LEAGUE_AVG = {"hard_hit_pct": 35.0, "barrel_pct": 7.0, "avg_ev": 88.5}
_QOC_LEAGUE_STD = {"hard_hit_pct": 8.0, "barrel_pct": 4.0, "avg_ev": 2.5}
_QOC_WEIGHTS = {"hard_hit_pct": 0.35, "barrel_pct": 0.40, "avg_ev": 0.25}


def _is_barrel(ev, la) -> bool:
    """Approximation of MLB's official "Barrel" classification (the exact
    formula is proprietary) — batted balls whose exit-velocity/launch-
    angle combination historically produces roughly .500 AVG/1.500 SLG.
    Uses the widely-cited open approximation: EV >=98 mph required, with
    the qualifying launch-angle window widening from 26-30 degrees right
    at 98 mph out to 8-50 degrees by 116+ mph."""
    if pd.isna(ev) or pd.isna(la) or ev < 98:
        return False
    if ev >= 116:
        return 8 <= la <= 50
    frac = (ev - 98) / (116 - 98)
    lower = 26 - frac * (26 - 8)
    upper = 30 + frac * (50 - 30)
    return lower <= la <= upper


def quality_of_contact_score(mlbID: int, season: int) -> dict | None:
    """Our own single 1-100 "Quality of Contact" number, blending hard-hit
    rate, barrel rate, and average exit velocity — not a stat MLB/Statcast
    publishes directly, an in-house composite. Built entirely from
    player_batted_ball_events (the same Statcast pull the spray chart
    already fetches) rather than a new call. Scaled against the FIXED
    _QOC_LEAGUE_AVG/_QOC_LEAGUE_STD constants above rather than a live
    league-wide pool — see that comment for why. Returns None if the
    player has no batted-ball data that season."""
    bb = player_batted_ball_events(mlbID, season)
    bb = bb.dropna(subset=["launch_speed"])
    if bb.empty:
        return None

    hard_hit_pct = (bb["launch_speed"] >= _QOC_HARD_HIT_MPH).mean() * 100
    barrel_pct = bb.apply(lambda r: _is_barrel(r["launch_speed"], r.get("launch_angle")), axis=1).mean() * 100
    avg_ev = bb["launch_speed"].mean()

    components = {"hard_hit_pct": hard_hit_pct, "barrel_pct": barrel_pct, "avg_ev": avg_ev}
    z = sum(
        _QOC_WEIGHTS[k] * (components[k] - _QOC_LEAGUE_AVG[k]) / _QOC_LEAGUE_STD[k]
        for k in components
    )
    score = int(round(min(100, max(1, 50 + 15 * z))))
    return {
        "score": score,
        "hard_hit_pct": round(hard_hit_pct, 1),
        "barrel_pct": round(barrel_pct, 1),
        "avg_ev": round(avg_ev, 1),
        "n": len(bb),
    }


# Hard Contact's three Statcast inputs are strongly correlated with ISO
# (0.56-0.78 in real data) and contact_pct is negatively correlated with
# both (-0.34 to -0.43) — a genuine baseball tradeoff (harder swings whiff
# more), not a stat artifact. That means Hard Contact + Power aren't
# independent signals; nominal weights on them compound rather than just
# add, systematically underrating contact hitters relative to what the
# raw percentages suggest. Weighted down from an initial 30/25/30/15 split
# after confirming real leaderboard results skewed toward power hitters.
# Volume (PA) added after that: producing at a given rate over more plate
# appearances is more valuable than the same rate over a small sample —
# the same principle counting-and-playing-time-sensitive stats like WAR
# already build in, which this composite otherwise doesn't (every other
# input here is a rate/percentage, blind to how much of it a player
# actually did). The other four categories' weights were scaled down
# proportionally (same 20:20:35:25 ratio) to make room for it.
_HVS_WEIGHTS = {"hard_contact": 0.17, "power": 0.17, "bat_to_ball": 0.30, "plate_eye": 0.21, "volume": 0.15}
# Sub-weights within the Hard Contact category only — same split
# quality_of_contact_score above already uses for its three Statcast
# inputs, reused here rather than re-deriving a second opinion.
_HVS_HARD_CONTACT_SUBWEIGHTS = {"hard_hit_pct": 0.35, "barrel_pct": 0.40, "avg_exit_velo": 0.25}


def hitting_value_score(batting: pd.DataFrame, min_pa: int = 100) -> pd.Series:
    """HVS ("Hitting Value Score") — our own 1-100 composite blending five
    categories: Hard Contact (hard_hit_pct/barrel_pct/avg_exit_velo, 17%),
    Power (ISO, 17%), Bat-to-Ball (contact_pct, 30%), Plate Eye (BB_PCT,
    21%), and Volume (PA, 15% — see _HVS_WEIGHTS comment for why playing
    time counts toward "value" here). Deliberately excludes WAR/wRC+/OPS+
    (already comprehensive weighted composites of their own — folding
    them in would just double-count the same underlying production) and
    speed/baserunning stats (a different skill from hitting).
    Unlike quality_of_contact_score's FIXED reference constants (needed
    there since that function only ever sees one player at a time, with
    no pool to measure against), this scales each stat against the ACTUAL
    mean/std of `batting`'s own qualified players (PA >= min_pa) — more
    accurate for whatever season/pool is actually being viewed, and no
    guessed constants to keep in sync with reality.
    `batting` must have hard_hit_pct, barrel_pct, avg_exit_velo, ISO,
    contact_pct, BB_PCT, PA (see load_batting). Returns a 1-100 Series
    aligned to `batting`'s index, NaN wherever the underlying stats are
    NaN (e.g. contact_pctile's tighter minimum leaves some rows without
    contact_pct)."""
    qualified = batting[batting["PA"] >= min_pa]

    def z(col):
        std = qualified[col].std()
        if not std or pd.isna(std):
            return pd.Series(0.0, index=batting.index)
        return (batting[col] - qualified[col].mean()) / std

    hard_contact_z = (
        _HVS_HARD_CONTACT_SUBWEIGHTS["hard_hit_pct"] * z("hard_hit_pct")
        + _HVS_HARD_CONTACT_SUBWEIGHTS["barrel_pct"] * z("barrel_pct")
        + _HVS_HARD_CONTACT_SUBWEIGHTS["avg_exit_velo"] * z("avg_exit_velo")
    )
    composite_z = (
        _HVS_WEIGHTS["hard_contact"] * hard_contact_z
        + _HVS_WEIGHTS["power"] * z("ISO")
        + _HVS_WEIGHTS["bat_to_ball"] * z("contact_pct")
        + _HVS_WEIGHTS["plate_eye"] * z("BB_PCT")
        + _HVS_WEIGHTS["volume"] * z("PA")
    )
    return (50 + 15 * composite_z).round().clip(1, 100)



def _readable_event(events) -> str:
    return events.replace("_", " ").title() if isinstance(events, str) and events else "In Play"


@st.cache_data(show_spinner=False, ttl=3600 * 24, max_entries=10)
def load_statcast_daily_leaderboard(date_iso: str) -> dict:
    """League-wide Statcast highlights for a single date — hardest-hit ball,
    longest home run, and fastest pitch — for the Daily Digest' Statcast
    Highlights section. Live-fetched from Baseball Savant via pybaseball
    (like player_batted_ball_events above, pitch-level Statcast isn't part
    of the daily ingest — it's heavy and most days it'd go unused), but
    unlike that per-player function this uses pybaseball.statcast() itself,
    which pulls every pitch leaguewide for a date range in one request —
    a leaderboard needs every player who played that day, not one player's
    history, so one request per player would mean dozens of requests
    instead of one.
    Returns a dict with keys "hardest_hit", "longest_hr", "fastest_pitch" —
    each either None (fetch failed or nothing qualified that day) or a dict
    with mlbID (batter for the first two, pitcher for the last) and a
    ready-to-display `detail` string."""
    import pybaseball as pb
    from pybaseball.utils import pitch_code_to_name_map

    empty = {"hardest_hit": None, "longest_hr": None, "fastest_pitch": None}
    try:
        raw = pb.statcast(start_dt=date_iso, end_dt=date_iso, verbose=False)
    except Exception:
        return empty
    if raw is None or raw.empty:
        return empty

    result = dict(empty)

    batted = raw.dropna(subset=["launch_speed", "batter"])
    if not batted.empty:
        hardest = batted.loc[batted["launch_speed"].idxmax()]
        result["hardest_hit"] = {
            "mlbID": int(hardest["batter"]),
            "detail": f"{hardest['launch_speed']:.1f} mph exit velo ({_readable_event(hardest.get('events'))})",
        }

    homers = raw.dropna(subset=["hit_distance_sc", "batter"])
    homers = homers[homers["events"] == "home_run"]
    if not homers.empty:
        longest = homers.loc[homers["hit_distance_sc"].idxmax()]
        result["longest_hr"] = {
            "mlbID": int(longest["batter"]),
            "detail": f"{longest['hit_distance_sc']:.0f} ft home run",
        }

    pitches = raw.dropna(subset=["release_speed", "pitcher"])
    if not pitches.empty:
        fastest = pitches.loc[pitches["release_speed"].idxmax()]
        pitch_name = pitch_code_to_name_map.get(fastest.get("pitch_type"), fastest.get("pitch_type") or "pitch")
        result["fastest_pitch"] = {
            "mlbID": int(fastest["pitcher"]),
            "detail": f"{fastest['release_speed']:.1f} mph {pitch_name}",
        }

    return result


# Our team_abbr -> pybaseball's STADIUM_COORDS team key (lowercase franchise
# nickname; a few are historical — "indians" predates the Guardians rename,
# pybaseball hasn't relabeled it). No entry for a team means no digitized
# outline is bundled for it (falls back to the generic stylized field).
STADIUM_KEY_BY_ABBR = {
    "ARI": "diamondbacks", "ATL": "braves", "ATH": "athletics", "BAL": "orioles",
    "BOS": "red_sox", "CWS": "white_sox", "CHC": "cubs", "CIN": "reds",
    "CLE": "indians", "COL": "rockies", "DET": "tigers", "HOU": "astros",
    "KC": "royals", "LAA": "angels", "LAD": "dodgers", "MIA": "marlins",
    "MIL": "brewers", "MIN": "twins", "NYY": "yankees", "NYM": "mets",
    "PHI": "phillies", "PIT": "pirates", "SD": "padres", "SF": "giants",
    "SEA": "mariners", "STL": "cardinals", "TB": "rays", "TEX": "rangers",
    "TOR": "blue_jays", "WSH": "nationals",
}

# Real straightaway center-field distance (feet) for each park, used to
# calibrate STADIUM_COORDS' own (unrelated-to-Statcast) coordinate scale —
# see team_stadium_outline. Public, commonly-cited figures; a park with a
# quirky angled CF wall (not a single "straightaway" point) is approximate.
STADIUM_CF_FEET = {
    "ARI": 407, "ATL": 400, "ATH": 403, "BAL": 400, "BOS": 390, "CWS": 400,
    "CHC": 400, "CIN": 404, "CLE": 405, "COL": 415, "DET": 412, "HOU": 409,
    "KC": 410, "LAA": 396, "LAD": 395, "MIA": 400, "MIL": 400, "MIN": 404,
    "NYY": 408, "NYM": 408, "PHI": 401, "PIT": 399, "SD": 396, "SF": 399,
    "SEA": 401, "STL": 400, "TB": 404, "TEX": 407, "TOR": 400, "WSH": 402,
}


@st.cache_data(show_spinner=False)
def team_stadium_outline(team_abbr: str) -> dict[str, list[tuple[float, float]]]:
    """One team's real ballpark outline, in the spray chart's own
    feet-from-home-plate coordinate space — pybaseball bundles a digitized
    per-park outline (STADIUM_COORDS) for exactly this kind of overlay, but
    in its own coordinate system, unrelated in scale to Statcast's hc_x/
    hc_y (confirmed by comparing raw distances against real dimensions —
    naively reusing the hc_x/hc_y transform on this data silently produces
    a nonsense-scale shape). STADIUM_COORDS actually bundles TWO outfield
    boundaries — "outfield_outer" turns out to be the back-of-stands/
    structural limit (i.e. roughly where the fans sit), while
    "outfield_inner" is the actual fence; plotting outfield_outer put a
    stadium-structure line in the chart that has nothing to do with where
    a ball can be caught, so only outfield_inner is used here. Calibrated
    per team from that park's own data: home plate is the foul lines'
    shared vertex, "deepest" is whichever outfield_inner point sits
    farthest from it, and the scale factor is real_cf_ft / that raw
    distance (see STADIUM_CF_FEET) — then every segment is re-centered on
    home plate and scaled the same way. Returns {segment_name:
    [(x_ft, y_ft), ...]} for the fence plus the infield grass/dirt arcs
    and foul lines; empty if the team has no bundled outline."""
    key = STADIUM_KEY_BY_ABBR.get(team_abbr)
    if not key:
        return {}

    from pybaseball.plotting import STADIUM_COORDS

    park = STADIUM_COORDS[STADIUM_COORDS["team"] == key]
    home_plate = park[park["segment"] == "home_plate"]
    outfield = park[park["segment"] == "outfield_inner"]
    if home_plate.empty or outfield.empty:
        return {}

    # The home_plate segment's own centroid is a far more reliable "home"
    # anchor than the first row of foul_lines — for most teams they agree,
    # but at least one park's (Astros) foul_lines segment doesn't actually
    # start at home plate, which silently threw off that team's whole
    # calibration (and produced hundreds-of-feet-off points behind home).
    home_x, home_y = home_plate[["x", "y"]].mean()
    raw_dist = ((outfield["x"] - home_x) ** 2 + (outfield["y"] - home_y) ** 2) ** 0.5
    # A handful of parks (e.g. Minute Maid) have a few wildly mis-digitized
    # points hundreds of raw units past the real fence — a plain max() lets
    # one bad point corrupt the whole park's scale, so anchor off the 95th
    # percentile instead.
    raw_deep = raw_dist.quantile(0.95)
    if not raw_deep or pd.isna(raw_deep):
        return {}
    real_cf = STADIUM_CF_FEET.get(team_abbr, 400)
    scale = real_cf / raw_deep
    max_plausible_ft = real_cf * 1.3

    outline = {}
    for segment in ("outfield_inner", "infield_outer", "infield_inner", "foul_lines"):
        seg_df = park[park["segment"] == segment]
        if seg_df.empty:
            continue
        xs = (seg_df["x"] - home_x) * scale
        ys = (seg_df["y"] - home_y) * scale
        pts = [
            (x, y) for x, y in zip(xs.tolist(), ys.tolist())
            if (x ** 2 + y ** 2) ** 0.5 <= max_plausible_ft
        ]
        if pts:
            outline[segment] = pts
    return outline


_DEPTH_CHART_POSITIONS = {"SP", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH", "CP"}


@st.cache_data(show_spinner=False, ttl=3600 * 6, max_entries=30)
def load_depth_chart(team_id: int) -> dict:
    """Current starter at each defensive position (plus the rotation's #1
    starting pitcher and the closer, as "RP") for one team, from the MLB
    Stats API's depth chart roster — a live lookup, not part of the daily
    ingest, since depth charts shift with trades/call-ups more often than
    once a day. Returns {position_code: {"name", "mlbID", "bats"}}, e.g.
    {"SS": {"name": "...", "mlbID": ..., "bats": "L"|"R"|"S"}}; a position
    is simply absent if the API has no one listed there. "bats" is each
    player's batting side."""
    try:
        resp = requests.get(
            f"https://statsapi.mlb.com/api/v1/teams/{int(team_id)}/roster",
            params={"rosterType": "depthChart", "hydrate": "person(batSide)"},
            timeout=10,
        )
        resp.raise_for_status()
        roster = resp.json().get("roster", [])
    except Exception:
        return {}

    starters = {}
    for entry in roster:
        pos = entry.get("position", {}).get("abbreviation")
        if pos not in _DEPTH_CHART_POSITIONS or pos in starters:
            continue
        person = entry.get("person", {})
        if person.get("id") and person.get("fullName"):
            starters[pos] = {
                "name": person["fullName"], "mlbID": person["id"],
                "bats": person.get("batSide", {}).get("code"),
            }
    if "CP" in starters:
        starters["RP"] = starters.pop("CP")
    return starters


_INJURY_STATUS_CODES = {"D7": "7-Day IL", "D10": "10-Day IL", "D15": "15-Day IL", "D60": "60-Day IL"}


@st.cache_data(show_spinner=False, ttl=3600 * 24, max_entries=2000)
def is_player_active(mlbID) -> bool | None:
    """Whether MLB currently considers this player active (on a 40-man
    roster somewhere, even hurt) vs. actually retired — from the Stats
    API's own `active` flag on the person record, which is the only
    reliable signal for this. A player with zero rows in the current
    season's batting/pitching tables looks identical either way (Félix
    Bautista out all year hurt vs. a retiree) from this app's own data
    alone, which is what previously mislabeled injured players as
    "retired." Returns None on a lookup failure so callers can fall back
    to that no-stats-this-season heuristic instead of guessing wrong."""
    try:
        resp = requests.get(f"https://statsapi.mlb.com/api/v1/people/{int(mlbID)}", timeout=10)
        resp.raise_for_status()
        people = resp.json().get("people", [])
        return bool(people[0].get("active")) if people else None
    except Exception:
        return None


# Curated marquee award IDs, keyed to a display label and color, for the
# Player page's awards summary — real MLB Stats API award ids, confirmed
# against actual recipients (Judge: ALMVP/ALSS/ALHAA/ALROY/ALAS; Skenes:
# NLCY/NLROY/NLAS; Ohtani: NLMVP/NLCSMVP/DHOY/WSCHAMP; Arenado: NLGG).
# {AL,NL} prefix covers both leagues for every award that has one.
_MARQUEE_AWARDS = {
    "ALMVP": ("AL MVP", "#F5B942"), "NLMVP": ("NL MVP", "#F5B942"),
    "ALCY": ("AL Cy Young", "#F5B942"), "NLCY": ("NL Cy Young", "#F5B942"),
    "ALROY": ("AL Rookie of the Year", "#7CFC9A"), "NLROY": ("NL Rookie of the Year", "#7CFC9A"),
    "ALGG": ("AL Gold Glove", "#9AA3B5"), "NLGG": ("NL Gold Glove", "#9AA3B5"),
    "ALSS": ("AL Silver Slugger", "#3B82F6"), "NLSS": ("NL Silver Slugger", "#3B82F6"),
    "ALHAA": ("AL Hank Aaron Award", "#F87171"), "NLHAA": ("NL Hank Aaron Award", "#F87171"),
    "ALAS": ("AL All-Star", "#C084FC"), "NLAS": ("NL All-Star", "#C084FC"),
    "MLBAFIRST": ("All-MLB First Team", "#F5B942"), "MLBSECOND": ("All-MLB Second Team", "#9AA3B5"),
    "WSCHAMP": ("World Series Champion", "#F5B942"), "WSMVP": ("World Series MVP", "#F5B942"),
    "ALCSMVP": ("ALCS MVP", "#C084FC"), "NLCSMVP": ("NLCS MVP", "#C084FC"),
    "DHOY": ("Outstanding DH", "#3B82F6"),
    "MLBRC": ("Roberto Clemente Award", "#F87171"),
    "WDPOY": ("Wilson Defensive Player of the Year", "#9AA3B5"),
}
# Real but too frequent/minor to headline a career trophy case (a good
# player earns a dozen Player-of-the-Week/Month nods a year, and minor-
# league honors stop being the point once someone has an MLB profile) —
# folded into a single "+N other honors" count instead of hidden outright.
_NOISY_AWARD_PREFIXES = ("POW", "POM", "ROM", "PITOM")


@st.cache_data(show_spinner=False, ttl=3600 * 6, max_entries=500)
def load_player_awards(mlbID) -> dict | None:
    """This player's full MLB award history, live from the Stats API's own
    `awards` hydrate (confirmed real and current for real recipients —
    Judge's 2022/2024 AL MVPs, Skenes' 2024 NL Cy Young + ROY, Ohtani's
    2023 WSCHAMP, Arenado's Gold Gloves — all showed up correctly). NOT
    pybaseball's awards_players()/awards_share_players(): those depend on
    a bundled Lahman-database zip fetched from
    chadwickbureau/baseballdatabank on GitHub, and that repository no
    longer exists (confirmed: the repo page itself 404s, not just a
    branch rename) — broken upstream, not something this app can fix.
    This MLB-native route also has real advantages over that dead one:
    always current (updates the moment a new award is announced, no
    ingest/backfill needed) and it's a live per-player fetch, same
    pattern as is_player_active.
    Returns {"marquee": [{"season","label","color"}, ...] sorted newest
    first, "other_count": int} or None if the player has no awards at
    all or the lookup fails."""
    try:
        resp = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{int(mlbID)}",
            params={"hydrate": "awards"}, timeout=10,
        )
        resp.raise_for_status()
        people = resp.json().get("people", [])
    except Exception:
        return None
    if not people:
        return None
    awards = people[0].get("awards") or []
    if not awards:
        return None

    marquee, other_count = [], 0
    for a in awards:
        award_id = a.get("id") or ""
        if award_id in _MARQUEE_AWARDS:
            label, color = _MARQUEE_AWARDS[award_id]
            marquee.append({"season": a.get("season"), "label": label, "color": color})
        elif any(award_id.endswith(suffix) for suffix in _NOISY_AWARD_PREFIXES):
            other_count += 1
        elif "MiLB" in (a.get("name") or "") or award_id.startswith(("AFL", "MILB", "INT", "BAAA", "SAL")):
            continue  # minor-league honors: not noise to count, just not relevant on an MLB profile
        else:
            other_count += 1
    marquee.sort(key=lambda m: m["season"] or "", reverse=True)
    if not marquee and not other_count:
        return None
    return {"marquee": marquee, "other_count": other_count}


@st.cache_data(show_spinner=False, ttl=3600, max_entries=3)
def load_injury_report() -> pd.DataFrame:
    """Every player currently on a major-league injured list, across all 30
    teams. The Stats API has no direct "give me the IL" endpoint, so this
    pulls each team's 40-man roster and keeps entries whose status code is
    an IL tier (D7/D10/D15/D60 — "D" is the API's historical "Disabled
    List" code, still used for today's injured list). That gives the
    authoritative current status but no injury description, so it's cross-
    referenced against the last 45 days of transactions (typeCode "SC" /
    Status Change) to pull in the actual injury text (e.g. "Left elbow
    soreness") when a matching recent placement exists; older placements
    outside that window just show the IL tier with no detail."""
    rows = []
    for abbr, team_id in teams._TEAM_IDS.items():
        try:
            resp = requests.get(
                f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster",
                params={"rosterType": "40Man"},
                timeout=10,
            )
            resp.raise_for_status()
            roster = resp.json().get("roster", [])
        except Exception:
            continue
        for entry in roster:
            code = entry.get("status", {}).get("code")
            if code not in _INJURY_STATUS_CODES:
                continue
            person = entry.get("person", {})
            if not person.get("id"):
                continue
            rows.append({
                "mlbID": person["id"],
                "Name": person.get("fullName"),
                "Tm": abbr,
                "Position": entry.get("position", {}).get("abbreviation"),
                "Status": _INJURY_STATUS_CODES[code],
            })
    if not rows:
        return pd.DataFrame(columns=["mlbID", "Name", "Tm", "Position", "Status", "Detail"])

    detail_by_id = {}
    try:
        end, start = datetime.now(), datetime.now() - timedelta(days=45)
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/transactions",
            params={"sportId": 1, "startDate": start.strftime("%m/%d/%Y"), "endDate": end.strftime("%m/%d/%Y")},
            timeout=15,
        )
        resp.raise_for_status()
        txs = sorted(resp.json().get("transactions", []), key=lambda t: t.get("date") or "")
        for t in txs:
            desc = t.get("description") or ""
            if t.get("typeCode") != "SC" or "injured list" not in desc.lower() or "activated" in desc.lower():
                continue
            pid = t.get("person", {}).get("id")
            if not pid:
                continue
            parts = desc.split(". ")
            detail_by_id[pid] = parts[-1].strip().rstrip(".") if len(parts) > 1 else None
    except Exception:
        pass

    df = pd.DataFrame(rows)
    df["Detail"] = df["mlbID"].map(detail_by_id)
    return df


@st.cache_data(show_spinner=False, ttl=1800, max_entries=5)
def load_transactions(days: int) -> pd.DataFrame:
    """Recent MLB transactions (trades, signings, DFAs, injured-list moves,
    etc.) from the Stats API, most recent first. `days` is part of the
    cache key so switching the lookback window in the UI doesn't have to
    wait out an old entry's TTL."""
    end, start = datetime.now(), datetime.now() - timedelta(days=days)
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/transactions",
            params={"sportId": 1, "startDate": start.strftime("%m/%d/%Y"), "endDate": end.strftime("%m/%d/%Y")},
            timeout=15,
        )
        resp.raise_for_status()
        txs = resp.json().get("transactions", [])
    except Exception:
        return pd.DataFrame(columns=["date", "type", "to_abbr", "from_abbr", "description", "mlbID"])

    rows = []
    for t in txs:
        desc = t.get("description")
        if not desc:
            continue
        rows.append({
            "id": t.get("id"),
            "date": t.get("date"),
            "type": t.get("typeDesc"),
            "to_abbr": teams.abbr_for_team_id((t.get("toTeam") or {}).get("id")),
            "from_abbr": teams.abbr_for_team_id((t.get("fromTeam") or {}).get("id")),
            "description": desc,
            "mlbID": (t.get("person") or {}).get("id"),
        })
    if not rows:
        return pd.DataFrame(columns=["date", "type", "to_abbr", "from_abbr", "description", "mlbID"])
    # The API emits one entry per team on each side of a trade (e.g. a 1-for-1
    # trade yields two rows sharing the same "id" with an identical
    # description) — keep just one per transaction id.
    df = pd.DataFrame(rows).drop_duplicates(subset="id").drop(columns="id")
    return df.sort_values("date", ascending=False, kind="stable").reset_index(drop=True)


# Free agency isn't a clean flag anywhere in the Stats API — it has to be
# inferred from the transaction log: whichever of these event types last
# happened to a player determines whether they're currently unattached.
_FA_TYPES = {"Declared Free Agency", "Released"}
_FA_RESOLVED_TYPES = {
    "Signed as Free Agent", "Signed", "Trade", "Claimed Off Waivers",
    "Rule 5 Selection", "Rule 5 Draft Minors",
}
_FA_EXCLUDE_TYPES = {"Retired"}


@st.cache_data(show_spinner=False, ttl=3600 * 6, max_entries=500)
def _people_lookup(mlb_ids: tuple) -> pd.DataFrame:
    """Batched name/position/age/debut-date lookup for a list of mlbIDs —
    chunked at 300 ids per call, same limit fetch_career_totals's ingest
    step works around (the endpoint 414s past that many comma-joined ids
    in one request). `mlb_ids` is a tuple (not list) so it's hashable for
    st.cache_data's key."""
    rows = []
    ids = list(mlb_ids)
    for i in range(0, len(ids), 300):
        chunk = ids[i:i + 300]
        try:
            resp = requests.get(
                "https://statsapi.mlb.com/api/v1/people",
                params={"personIds": ",".join(str(x) for x in chunk)},
                timeout=30,
            )
            resp.raise_for_status()
            people = resp.json().get("people", [])
        except Exception:
            continue
        for p in people:
            rows.append({
                "mlbID": p["id"],
                "Name": p.get("fullName"),
                "Pos": (p.get("primaryPosition") or {}).get("abbreviation"),
                "Age": p.get("currentAge"),
                "debut_date": p.get("mlbDebutDate"),
            })
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["mlbID", "Name", "Pos", "Age", "debut_date"])


def _years_experience(debut_date) -> float | None:
    if not debut_date:
        return None
    try:
        debut = datetime.strptime(debut_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    return round((datetime.now() - debut).days / 365.25, 1)


def _latest_season_stat_line(mlbID: int, db_mtime_val: float) -> dict:
    """Whichever of the current or prior season has this player's most
    recent stat line (a released player often has zero rows in the
    current season if they were let go before ever appearing in a game
    this year) — batting checked before pitching, same "primary role"
    tie-break precedent as player_primary_role elsewhere in this file."""
    for season in (get_seasons("batting")[0], get_seasons("batting")[0] - 1):
        bat = get_player_batting(mlbID, season, db_mtime_val)
        if bat is not None:
            return {
                "season": season, "role": "Batter", "PA": bat.get("PA"),
                "line": f"{bat.get('BA', float('nan')):.3f} AVG, {int(bat.get('HR', 0))} HR, {bat.get('OPS', float('nan')):.3f} OPS",
            }
        pit = get_player_pitching(mlbID, season, db_mtime_val)
        if pit is not None:
            return {
                "season": season, "role": "Pitcher", "IP": pit.get("IP"),
                "line": f"{pit.get('ERA', float('nan')):.2f} ERA, {int(pit.get('SO', 0))} SO, {pit.get('IP', float('nan')):.1f} IP",
            }
    return {"season": None, "role": None, "line": "No recent MLB stats"}


@st.cache_data(show_spinner=False, ttl=3600 * 6, max_entries=2)
def free_agent_tracker(db_mtime_val: float) -> pd.DataFrame:
    """Currently-unattached players, inferred from the transaction log (see
    _FA_TYPES/_FA_RESOLVED_TYPES/_FA_EXCLUDE_TYPES) — whoever's most recent
    relevant transaction was a release or free-agency declaration, with no
    signing/trade/waiver-claim since. Approximate by nature (a team's own
    internal roster moves the Stats API doesn't publish as a transaction
    could theoretically be missed), but covers the vast majority of real
    free agents. 420-day lookback covers a full offseason plus in-season
    releases; someone who's been unsigned longer than that still shows up
    as long as nothing else happened to their transaction record since."""
    txs = load_transactions(420)
    if txs.empty:
        return pd.DataFrame()

    relevant_types = _FA_TYPES | _FA_RESOLVED_TYPES | _FA_EXCLUDE_TYPES
    relevant = txs[txs["type"].isin(relevant_types) & txs["mlbID"].notna()].copy()
    if relevant.empty:
        return pd.DataFrame()
    relevant["mlbID"] = relevant["mlbID"].astype(int)
    relevant = relevant.sort_values("date")
    latest = relevant.groupby("mlbID", as_index=False).tail(1)
    fa = latest[latest["type"].isin(_FA_TYPES)].copy()
    if fa.empty:
        return pd.DataFrame()

    people = _people_lookup(tuple(sorted(fa["mlbID"].unique().tolist())))
    fa = fa.merge(people, on="mlbID", how="left")
    fa["experience_years"] = fa["debut_date"].map(_years_experience)
    stat_lines = fa["mlbID"].map(lambda mid: _latest_season_stat_line(mid, db_mtime_val))
    fa["last_season"] = stat_lines.map(lambda d: d["season"])
    fa["last_stat_line"] = stat_lines.map(lambda d: d["line"])

    return fa.rename(columns={"to_abbr": "last_team", "date": "fa_date", "type": "fa_type"})[
        ["mlbID", "Name", "Pos", "Age", "experience_years", "last_team", "fa_date", "fa_type",
         "last_season", "last_stat_line", "description"]
    ].sort_values("fa_date", ascending=False).reset_index(drop=True)


@st.cache_data(show_spinner=False, ttl=3600, max_entries=2)
def recent_free_agent_signings(db_mtime_val: float, days: int = 90) -> pd.DataFrame:
    """Free agents who signed somewhere in the last `days` days — the
    "moved off the market" counterpart to free_agent_tracker, from the
    same transaction log (see _FA_RESOLVED_TYPES)."""
    txs = load_transactions(days)
    if txs.empty:
        return pd.DataFrame()
    signed = txs[txs["type"].isin({"Signed as Free Agent", "Signed"}) & txs["mlbID"].notna()].copy()
    if signed.empty:
        return pd.DataFrame()
    signed["mlbID"] = signed["mlbID"].astype(int)
    people = _people_lookup(tuple(sorted(signed["mlbID"].unique().tolist())))
    signed = signed.merge(people, on="mlbID", how="left")
    return signed.rename(columns={"to_abbr": "new_team", "date": "signed_date", "type": "sign_type"})[
        ["mlbID", "Name", "Pos", "Age", "new_team", "signed_date", "sign_type", "description"]
    ].sort_values("signed_date", ascending=False).reset_index(drop=True)


_COMPOSITE_FIELD_POSITIONS = ["1B", "2B", "3B", "SS", "LF", "CF", "RF"]
_COMPOSITE_MIN_PA = 150
_COMPOSITE_MIN_IP = 20
_COMPOSITE_MIN_RP_IP = 15


@st.cache_data(show_spinner=False, ttl=3600 * 6, max_entries=5)
def load_league_catchers(db_mtime_val: float) -> pd.DataFrame:
    """Every team's primary catcher (mlbID/Name/Tm), assembled from each
    team's live depth chart (see load_depth_chart) — the only source of
    catcher identity available here, since Statcast Outs Above Average
    (fielding table, the position source for every other spot) excludes
    the battery (pitchers/catchers) entirely."""
    rows = []
    for abbr, _nickname in teams.all_teams():
        team_id = teams.team_id_for_abbr(abbr)
        if not team_id:
            continue
        catcher = load_depth_chart(team_id).get("C")
        if catcher:
            rows.append({"mlbID": catcher["mlbID"], "Name": catcher["name"], "Tm": abbr})
    return pd.DataFrame(rows, columns=["mlbID", "Name", "Tm"])


def build_composite_team(season: int, mtime: float, scope: str) -> dict:
    """Best qualified player at each position leaguewide (not tied to one
    real team), in the same {position: {"name","mlbID","note"}} shape
    load_depth_chart() returns, ready for style.baseball_diamond().

    scope:
      "all"   - full-season stats (min _COMPOSITE_MIN_PA PA / _COMPOSITE_MIN_IP IP).
      "month" - best performer over the trailing 30 days, from the same
                recent_batting/recent_pitching tables and min-PA/IP bars
                (RECENT_MIN_PA/RECENT_MIN_IP["month"]) as the Home page's
                "Hot This Month" cards.

    SP and RP are picked separately so a low-IP reliever can't take the SP
    spot: season pitching has a Games-Started column to split on directly;
    recent_pitching (month) doesn't, so it's joined against the season
    table's GS just to classify each pitcher as starter/reliever, IP filters
    still keyed to the trailing-30-days IP.
    """
    fielding = load_fielding(season, mtime)[["player_id", "Pos"]].rename(columns={"player_id": "mlbID"})
    season_roles = load_pitching(season, mtime)[["mlbID", "GS"]]

    if scope == "month":
        batting = load_recent_batting(season, mtime)
        batting = batting[(batting["period"] == "month") & (batting["PA"] >= RECENT_MIN_PA["month"])]
        pitching = load_recent_pitching(season, mtime)
        # recent_pitching.mlbID is stored as text in SQLite (unlike every
        # other table's mlbID) — cast before merging on it or pandas raises.
        pitching = pitching.assign(mlbID=pitching["mlbID"].astype(int))
        pitching = pitching[pitching["period"] == "month"].merge(season_roles, on="mlbID", how="inner")
        sp_pool = pitching[(pitching["GS"] > 0) & (pitching["IP"] >= RECENT_MIN_IP["month"])]
        rp_pool = pitching[(pitching["GS"] == 0) & (pitching["IP"] >= max(RECENT_MIN_IP["month"] / 2, 1))]
    else:
        batting = load_batting(season, mtime)
        batting = batting[batting["PA"] >= _COMPOSITE_MIN_PA]
        pitching = load_pitching(season, mtime)
        sp_pool = pitching[(pitching["GS"] > 0) & (pitching["IP"] >= _COMPOSITE_MIN_IP)]
        rp_pool = pitching[(pitching["GS"] == 0) & (pitching["IP"] >= _COMPOSITE_MIN_RP_IP)]

    starters = {}

    fielders = batting.merge(fielding, on="mlbID", how="inner")
    for pos in _COMPOSITE_FIELD_POSITIONS:
        candidates = fielders[fielders["Pos"] == pos]
        if not candidates.empty:
            best = candidates.sort_values("OPS", ascending=False).iloc[0]
            starters[pos] = {
                "name": best["Name"], "mlbID": int(best["mlbID"]),
                "note": f"{best['OPS']:.3f} OPS",
            }

    catchers = load_league_catchers(mtime)
    if not catchers.empty and not batting.empty:
        catcher_stats = batting.merge(catchers[["mlbID"]], on="mlbID", how="inner")
        if not catcher_stats.empty:
            best_c = catcher_stats.sort_values("OPS", ascending=False).iloc[0]
            starters["C"] = {
                "name": best_c["Name"], "mlbID": int(best_c["mlbID"]),
                "note": f"{best_c['OPS']:.3f} OPS",
            }

    if not sp_pool.empty:
        best_sp = sp_pool.sort_values("ERA", ascending=True).iloc[0]
        starters["SP"] = {
            "name": best_sp["Name"], "mlbID": int(best_sp["mlbID"]),
            "note": f"{best_sp['ERA']:.2f} ERA",
        }
    if not rp_pool.empty:
        best_rp = rp_pool.sort_values("ERA", ascending=True).iloc[0]
        starters["RP"] = {
            "name": best_rp["Name"], "mlbID": int(best_rp["mlbID"]),
            "note": f"{best_rp['ERA']:.2f} ERA",
        }

    # DH: best remaining bat by OPS, excluding whoever already has a spot
    # (a real DH slot goes to the best hitter not needed in the field).
    if not batting.empty:
        used_ids = {p["mlbID"] for p in starters.values()}
        remaining = batting[~batting["mlbID"].isin(used_ids)]
        if not remaining.empty:
            best_dh = remaining.sort_values("OPS", ascending=False).iloc[0]
            starters["DH"] = {
                "name": best_dh["Name"], "mlbID": int(best_dh["mlbID"]),
                "note": f"{best_dh['OPS']:.3f} OPS",
            }

    return starters


@st.cache_data(show_spinner=False)
def all_star_seasons() -> list[int]:
    """Seasons with a cached All-Star roster — 2020 is deliberately absent
    (the game was canceled that year), not a gap in the ingest."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            rows = conn.execute("SELECT DISTINCT season FROM all_star_rosters ORDER BY season DESC").fetchall()
        except sqlite3.OperationalError:
            return []
    return [r[0] for r in rows]


@st.cache_data(show_spinner=False)
def load_all_star_roster(season: int, league: str, db_mtime_val: float) -> pd.DataFrame:
    """One league's (AL/NL) All-Star Game roster for a season — see
    ingest/refresh_data.py's fetch_all_star_roster() for where this comes
    from (the ASG itself has real team IDs, so its boxscore doubles as the
    roster). `is_starter` marks the actual starting lineup (fan-elected
    position players + the game's starting pitcher) vs. reserves — used to
    build the starters dict for style.baseball_diamond(). Sorted by
    position then name for a stable, scannable table."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            df = pd.read_sql(
                "SELECT mlbID, Name, Pos, Tm, is_starter FROM all_star_rosters WHERE season = ? AND league = ?",
                conn, params=(season, league),
            )
        except pd.errors.DatabaseError:
            return pd.DataFrame(columns=["mlbID", "Name", "Pos", "Tm", "is_starter"])
    # SQLite has no native boolean type — is_starter round-trips as 0/1
    # ints, which pandas won't treat as a boolean mask (df[df["int_col"]]
    # raises instead of filtering) unless cast back to bool explicitly.
    df["is_starter"] = df["is_starter"].astype(bool)
    return df.sort_values(["Pos", "Name"]).reset_index(drop=True)



@st.cache_data(show_spinner=False, max_entries=2)
def load_standings(db_mtime_val: float) -> pd.DataFrame:
    """Current MLB standings from the Stats API (current standings only,
    not historical — replaced in full on every ingest run)."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            return pd.read_sql("SELECT * FROM standings", conn)
        except pd.errors.DatabaseError:
            return pd.DataFrame()


@st.cache_data(show_spinner=False, max_entries=2)
def load_schedule(db_mtime_val: float) -> pd.DataFrame:
    """Full current-season regular-season schedule — every team, every game,
    past results and future matchups (see ingest's fetch_schedule()).
    Replaced in full on every ingest run, not historical across seasons."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            return pd.read_sql("SELECT * FROM schedule", conn)
        except pd.errors.DatabaseError:
            return pd.DataFrame()


@st.cache_data(show_spinner=False, ttl=3600, max_entries=4)
def load_upcoming_games(days: int = 7) -> pd.DataFrame:
    """League-wide upcoming schedule with probable starters, for the
    Schedule page — live from the MLB Stats API (the ingested schedule
    table has no probable-pitcher data). One row per game, today through
    today+days."""
    start = today_pacific()
    end = start + timedelta(days=days)
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={
                "sportId": 1, "startDate": start.isoformat(), "endDate": end.isoformat(),
                "hydrate": "probablePitcher",
            },
            timeout=20,
        )
        resp.raise_for_status()
        dates = resp.json().get("dates", [])
    except Exception:
        return pd.DataFrame()

    rows = []
    for d in dates:
        for g in d.get("games", []):
            if g.get("gameType") not in ("R",):  # regular season only
                continue
            away = (g.get("teams", {}).get("away", {}) or {})
            home = (g.get("teams", {}).get("home", {}) or {})
            away_pp = away.get("probablePitcher") or {}
            home_pp = home.get("probablePitcher") or {}
            rows.append({
                "game_pk": g.get("gamePk"),
                "date": d.get("date"),
                "game_time_utc": g.get("gameDate"),
                "status": (g.get("status") or {}).get("abstractGameState"),
                "away_abbr": teams.abbr_for_team_id((away.get("team") or {}).get("id")),
                "home_abbr": teams.abbr_for_team_id((home.get("team") or {}).get("id")),
                "away_pitcher_name": away_pp.get("fullName"),
                "away_pitcher_mlbID": away_pp.get("id"),
                "home_pitcher_name": home_pp.get("fullName"),
                "home_pitcher_mlbID": home_pp.get("id"),
            })
    return pd.DataFrame(rows)


def team_schedule(team_abbr: str, db_mtime_val: float) -> pd.DataFrame:
    """One team's full regular-season schedule — past results and upcoming
    matchups both, in date/time order (game_time, not just date, so a
    doubleheader's two games land in the right order). `result` is 'W'/'L'
    for played games, None for games not yet final."""
    schedule = load_schedule(db_mtime_val)
    columns = ["date", "game_time", "opponent", "home", "runs_for", "runs_against", "status", "result"]
    if schedule.empty:
        return pd.DataFrame(columns=columns)

    mine = schedule[(schedule["home_abbr"] == team_abbr) | (schedule["away_abbr"] == team_abbr)].copy()
    is_home = mine["home_abbr"] == team_abbr
    mine["opponent"] = mine["away_abbr"].where(is_home, mine["home_abbr"])
    mine["home"] = is_home
    mine["runs_for"] = mine["home_score"].where(is_home, mine["away_score"])
    mine["runs_against"] = mine["away_score"].where(is_home, mine["home_score"])
    mine["result"] = None
    # A status of "Final" with a null score does happen (a suspended game's
    # placeholder entry, resumed/completed as a separate row) — require an
    # actual score too, so that edge case falls through to the "upcoming"
    # branch (shows its status text) instead of a bogus "L nan-nan".
    played = (mine["status"] == "Final") & mine["runs_for"].notna() & mine["runs_against"].notna()
    mine.loc[played, "result"] = (mine.loc[played, "runs_for"] > mine.loc[played, "runs_against"]).map({True: "W", False: "L"})
    return mine[columns].sort_values("game_time").reset_index(drop=True)


def team_recent_form(team_abbr: str, db_mtime_val: float) -> dict | None:
    """Last-10 record and current win/loss streak for one team, from
    team_schedule's played games — for Today's Games' streak ticker, a
    lightweight view of how a team's been trending lately, beyond the
    season-long record the trained win model already uses for the odds
    themselves. Returns None if the team has no played games yet."""
    played = team_schedule(team_abbr, db_mtime_val)
    played = played[played["result"].notna()]
    if played.empty:
        return None
    last10 = played.tail(10)
    wins = int((last10["result"] == "W").sum())
    losses = int((last10["result"] == "L").sum())
    results = played["result"].tolist()
    streak_result = results[-1]
    streak_len = 0
    for r in reversed(results):
        if r != streak_result:
            break
        streak_len += 1
    return {"last10": f"{wins}-{losses}", "streak": f"{streak_result}{streak_len}"}


# Number of remaining-season simulations run for playoff odds. High enough
# for stable percentages (~1-2% simulation noise), cheap enough (a few
# hundred ms, vectorized with numpy) to run on every cache miss.
PLAYOFF_SIM_COUNT = 4000

# Current (2022+) postseason format: 3 division winners + 3 wild cards per
# league = 6 teams/league, 12 total.
WILD_CARDS_PER_LEAGUE = 3


def team_strength_profile(team_abbr: str, season: int, db_mtime_val: float) -> dict | None:
    """One team's offense/starters/bullpen/defense snapshot — the building
    block for the playoff matchup preview. Pitchers are split into
    starters/bullpen by role (GS > 0 counts as a starter — a
    simplification that misclassifies a rare long-man/piggyback reliever
    with a spot start, but is right for the vast majority of a roster) so
    a "great rotation, shaky bullpen" team reads as exactly that instead
    of being averaged into one bland team ERA. Returns None if the team
    has no batting rows for the season (shouldn't happen for a real
    playoff team, but keeps this from throwing on bad input)."""
    batting = teams.add_team_abbr(load_batting(season, db_mtime_val))
    pitching = teams.add_team_abbr(load_pitching(season, db_mtime_val))
    fielding = load_fielding(season, db_mtime_val)

    bat = batting[batting["Tm"] == team_abbr].dropna(subset=["OPS", "PA"])
    if bat.empty:
        return None
    pit = pitching[pitching["Tm"] == team_abbr].dropna(subset=["ERA", "IP"])

    def _pa_weighted(df, col):
        return (df[col] * df["PA"]).sum() / df["PA"].sum() if df["PA"].sum() > 0 else float("nan")

    def _ip_weighted_era(df):
        er = (df["ERA"] * df["IP"] / 9).sum()
        ip = df["IP"].sum()
        return 9 * er / ip if ip > 0 else float("nan")

    starters = pit[pit["GS"] > 0]
    bullpen = pit[pit["GS"] == 0]

    oaa_total = None
    if not fielding.empty:
        fld = teams.add_team_abbr_from_nickname(fielding)
        fld_team = fld[fld["Tm"] == team_abbr].dropna(subset=["OAA"])
        if not fld_team.empty:
            oaa_total = fld_team["OAA"].sum()

    return {
        "team_abbr": team_abbr,
        "ops": _pa_weighted(bat, "OPS"),
        "hr": int(bat["HR"].sum()),
        "sb": int(bat["SB"].sum()) if "SB" in bat.columns else None,
        "team_era": _ip_weighted_era(pit) if not pit.empty else float("nan"),
        "starter_era": _ip_weighted_era(starters) if not starters.empty else float("nan"),
        "bullpen_era": _ip_weighted_era(bullpen) if not bullpen.empty else float("nan"),
        "oaa": oaa_total,
    }


def _series_win_prob(p_game: float, n_games: int) -> float:
    """Probability of winning a best-of-`n_games` series, given a constant
    per-game win probability `p_game` — the exact binomial-tail
    probability of reaching the needed win count, not a per-game
    simulation (equivalent in distribution for a fixed p, since with an odd
    n_games "first to (n_games+1)//2 wins" and "wins the majority of all
    n_games games played" are the same event)."""
    needed = n_games // 2 + 1
    p_game = min(max(p_game, 1e-6), 1 - 1e-6)
    return sum(
        math.comb(n_games, k) * p_game ** k * (1 - p_game) ** (n_games - k)
        for k in range(needed, n_games + 1)
    )


@st.cache_data(show_spinner=False, max_entries=2)
def compute_playoff_odds(db_mtime_val: float) -> pd.DataFrame:
    """Monte Carlo playoff AND World Series odds for every team: simulate
    the rest of the regular season PLAYOFF_SIM_COUNT times, tally how often
    each team finishes among its league's 3 division winners + 3 wild
    cards, then simulate a full postseason bracket (Wild Card best-of-3 ->
    Division Series best-of-5 -> Championship Series best-of-7 -> World
    Series best-of-7, real 2022+ reseeding rules) on top of each of those
    simulated regular seasons for a championship probability.

    Each game's win probability comes from the trained win-probability
    model's team-only variant (see ingest/train_win_model.py) — the same
    walk-forward-backtested logistic regression behind Today's Games'
    odds, minus its starter feature (games simulated weeks/months ahead
    have unknown starters). Its features are frozen at today's state for
    the whole simulated remainder, exactly as the old blended rating was:
    shrunk record, shrunk run differential, prior-season strength, and a
    LEARNED home-field intercept for regular-season games (dropped for
    postseason series, which the bracket treats as venue-neutral — the
    same simplification the old Log5 path made, except "neutral" is now
    a principled zeroing of the model's home term rather than omitting a
    bolt-on constant). The old hand-blended 65/35 Pythagorean + OPS/ERA
    composite rating is retired with this: run-differential signal is
    now carried by a fitted, backtested coefficient instead of a hand-
    set blend weight, at the cost of the peripheral OPS/ERA read (team
    OPS/ERA as-of-date isn't reconstructable historically, so it
    couldn't be trained on honestly). Returns one row per team, keyed by
    team_abbr, with `playoff_pct` and `ws_pct` columns (0-100 each)."""
    standings = load_standings(db_mtime_val)
    schedule = load_schedule(db_mtime_val)
    columns = ["team_abbr", "playoff_pct", "division_pct", "wildcard_pct", "ws_pct"]
    if standings.empty or schedule.empty:
        return pd.DataFrame(columns=columns)

    standings = standings.dropna(subset=["team_abbr", "wins", "losses"]).drop_duplicates("team_abbr")
    team_list = standings["team_abbr"].tolist()
    n_teams = len(team_list)
    team_idx = {abbr: i for i, abbr in enumerate(team_list)}

    current_wins = standings["wins"].to_numpy(dtype=float)

    params = load_win_model_params()
    team_model = (params or {}).get("team_only")
    if not team_model:
        # The committed model artifact is required — same graceful-empty
        # convention as the missing-standings/schedule cases above.
        return pd.DataFrame(columns=columns)

    # Per-team model features, frozen at today's state for the whole
    # simulated remainder (the old blended-strength rating was equally
    # static) — the exact features the team-only variant was trained on.
    k = params["k_shrink"]
    games_played = current_wins + standings["losses"].to_numpy(dtype=float)
    runs_scored = standings["runs_scored"].fillna(0).to_numpy(dtype=float)
    runs_allowed = standings["runs_allowed"].fillna(0).to_numpy(dtype=float)
    shrunk_win = (current_wins + 0.5 * k) / (games_played + k)
    shrunk_rd = (runs_scored - runs_allowed) / (games_played + k)
    prior_map = params["prior_winpct_by_team_id"]
    prior = np.array([
        prior_map.get(str(teams.team_id_for_abbr(teams.normalize_mlb_abbr(a)) or ""), 0.5)
        for a in team_list
    ])

    def _model_p_home(home_cols, away_cols, neutral: bool = False):
        """Team-only model probability for a matchup; works on scalar or
        vector column indices. neutral=True drops the intercept — the
        intercept IS the learned home-field edge, so zeroing it gives a
        true neutral-field probability for postseason series."""
        feats = {
            "d_win": shrunk_win[home_cols] - shrunk_win[away_cols],
            "d_rundiff": shrunk_rd[home_cols] - shrunk_rd[away_cols],
            "d_prior": prior[home_cols] - prior[away_cols],
        }
        z = 0.0 if neutral else team_model["intercept"]
        for name, coef, mean, std in zip(
            team_model["features"], team_model["coef"], team_model["mean"], team_model["std"],
        ):
            z = z + coef * ((feats[name] - mean) / (std or 1.0))
        return 1.0 / (1.0 + np.exp(-z))

    remaining = schedule[
        (schedule["status"] != "Final")
        & schedule["away_abbr"].isin(team_idx) & schedule["home_abbr"].isin(team_idx)
    ]
    home_idx = remaining["home_abbr"].map(team_idx).to_numpy()
    away_idx = remaining["away_abbr"].map(team_idx).to_numpy()
    n_games = len(remaining)

    rng = np.random.default_rng()
    total_wins = np.tile(current_wins, (PLAYOFF_SIM_COUNT, 1))
    if n_games > 0:
        p_home = np.clip(_model_p_home(home_idx, away_idx), 0.01, 0.99)

        draws = rng.random((PLAYOFF_SIM_COUNT, n_games))
        home_wins = draws < p_home[None, :]

        home_onehot = np.zeros((n_games, n_teams))
        home_onehot[np.arange(n_games), home_idx] = 1
        away_onehot = np.zeros((n_games, n_teams))
        away_onehot[np.arange(n_games), away_idx] = 1

        total_wins += home_wins @ home_onehot + (~home_wins) @ away_onehot

    league_by_abbr = dict(zip(standings["team_abbr"], standings["league"]))
    division_by_abbr = dict(zip(standings["team_abbr"], standings["division"]))

    division_flags = np.zeros((PLAYOFF_SIM_COUNT, n_teams), dtype=bool)
    wildcard_flags = np.zeros((PLAYOFF_SIM_COUNT, n_teams), dtype=bool)
    # Per-league (SIM, 3) column-index arrays, kept for the bracket
    # simulation below — reusing these instead of recomputing them avoids
    # a second pass over the same division/wild-card logic.
    league_division_cols: dict[str, np.ndarray] = {}
    league_wc_cols: dict[str, np.ndarray] = {}

    for league in standings["league"].dropna().unique():
        league_teams = [abbr for abbr in team_list if league_by_abbr.get(abbr) == league]
        league_cols = [team_idx[a] for a in league_teams]

        division_winner_cols = []
        for division in sorted({division_by_abbr[a] for a in league_teams}):
            div_cols = [team_idx[a] for a in league_teams if division_by_abbr[a] == division]
            div_wins = total_wins[:, div_cols]
            winner_within_div = np.argmax(div_wins, axis=1)
            winner_cols = np.array(div_cols)[winner_within_div]
            division_flags[np.arange(PLAYOFF_SIM_COUNT), winner_cols] = True
            division_winner_cols.append(winner_cols)
        division_winner_cols = np.stack(division_winner_cols, axis=1)  # (SIM, num_divisions)

        league_wins = total_wins[:, league_cols].copy()
        league_cols_arr = np.array(league_cols)
        # Mask out this row's division winners (by global column index, not
        # position — league_cols_arr isn't guaranteed sorted) before picking
        # wild cards, via a broadcast compare rather than a per-row loop.
        winner_mask = (league_cols_arr[None, :, None] == division_winner_cols[:, None, :]).any(axis=2)
        masked_wins = np.where(winner_mask, -np.inf, league_wins)

        wc_order = np.argsort(-masked_wins, axis=1)[:, :WILD_CARDS_PER_LEAGUE]
        wc_cols = league_cols_arr[wc_order]  # already sorted best (seed 4) -> worst (seed 6)
        for w in range(WILD_CARDS_PER_LEAGUE):
            wildcard_flags[np.arange(PLAYOFF_SIM_COUNT), wc_cols[:, w]] = True

        league_division_cols[league] = division_winner_cols
        league_wc_cols[league] = wc_cols

    playoff_flags = division_flags | wildcard_flags

    # Postseason bracket: real 2022+ MLB format. Seeds 1-3 are always the
    # division winners (ranked by wins among themselves — a wild card can
    # never outrank a division winner regardless of record), seeds 4-6 the
    # wild cards (ranked by wins among themselves). Not vectorized across
    # simulations — each row's bracket depends on which specific teams
    # qualified that row, so the natural unit of work is "one simulated
    # season's whole postseason," done in a plain loop (cheap: ~11 series
    # per simulation, each an O(1) binomial-tail lookup).
    leagues = list(league_division_cols)
    ws_wins = np.zeros(n_teams)

    def _series_winner(col_a: int, col_b: int, n_games: int) -> int:
        p_a = float(_model_p_home(col_a, col_b, neutral=True))
        return col_a if rng.random() < _series_win_prob(p_a, n_games) else col_b

    for i in range(PLAYOFF_SIM_COUNT):
        league_champ = {}
        for league in leagues:
            div_cols_row = league_division_cols[league][i]
            wc_cols_row = league_wc_cols[league][i]  # already seed 4 -> 5 -> 6 order
            seeds = sorted(div_cols_row, key=lambda c: -total_wins[i, c]) + list(wc_cols_row)
            seed_num = {col: rank + 1 for rank, col in enumerate(seeds)}

            wc1 = _series_winner(seeds[2], seeds[5], 3)  # seed 3 vs seed 6
            wc2 = _series_winner(seeds[3], seeds[4], 3)  # seed 4 vs seed 5

            # Division Series reseeding: #1 seed plays the lowest surviving
            # seed number (the stronger of the two Wild Card round winners),
            # #2 seed plays the other.
            lo, hi = sorted([wc1, wc2], key=lambda c: seed_num[c])
            ds1 = _series_winner(seeds[0], lo, 5)
            ds2 = _series_winner(seeds[1], hi, 5)

            league_champ[league] = _series_winner(ds1, ds2, 7)

        ws_champ = _series_winner(league_champ[leagues[0]], league_champ[leagues[1]], 7) if len(leagues) == 2 else league_champ[leagues[0]]
        ws_wins[ws_champ] += 1

    result = pd.DataFrame({
        "team_abbr": team_list,
        "playoff_pct": 100 * playoff_flags.mean(axis=0),
        "division_pct": 100 * division_flags.mean(axis=0),
        "wildcard_pct": 100 * wildcard_flags.mean(axis=0),
        "ws_pct": 100 * ws_wins / PLAYOFF_SIM_COUNT,
    })
    return _clamp_playoff_odds(result, db_mtime_val)


# A PLAYOFF_SIM_COUNT-run Monte Carlo can land a team at a flat 0% or 100%
# purely from sample noise (every one of 4000 sims broke the same way)
# well before that team is actually mathematically clinched or eliminated
# — misleading, since 0%/100% reads as certainty. Nudged just off the
# extremes so "still mathematically alive/not yet locked up" always shows
# as such, while a team that IS actually clinched/eliminated (per
# clinch_elimination_status's exact math, not simulation sampling) still
# shows the true 100%/0%.
_ODDS_EPSILON = 0.1


def _clamp_playoff_odds(result: pd.DataFrame, db_mtime_val: float) -> pd.DataFrame:
    events = clinch_elimination_status(db_mtime_val)
    clinched_playoff = {e["team_abbr"] for e in events if e["kind"] in ("division_clinch", "wildcard_clinch")}
    clinched_division = {e["team_abbr"] for e in events if e["kind"] == "division_clinch"}
    clinched_wildcard = {e["team_abbr"] for e in events if e["kind"] == "wildcard_clinch"}
    eliminated = {e["team_abbr"] for e in events if e["kind"] == "eliminated"}

    def _clamp_col(col, guaranteed_set):
        vals = result[col].to_numpy(dtype=float)
        is_guaranteed = result["team_abbr"].isin(guaranteed_set).to_numpy()
        is_eliminated = result["team_abbr"].isin(eliminated).to_numpy()
        vals = np.clip(vals, _ODDS_EPSILON, 100 - _ODDS_EPSILON)
        vals = np.where(is_guaranteed, 100.0, vals)
        vals = np.where(is_eliminated, 0.0, vals)
        result[col] = vals

    _clamp_col("playoff_pct", clinched_playoff)
    _clamp_col("division_pct", clinched_division)
    _clamp_col("wildcard_pct", clinched_wildcard)
    _clamp_col("ws_pct", set())  # no team is ever guaranteed a championship before winning it
    return result


def current_playoff_picture(db_mtime_val: float) -> dict[str, pd.DataFrame]:
    """"If the season ended today" postseason seeding, straight from actual
    current standings (no simulation) — the 3 division winners as seeds 1-3
    (ranked by wins among themselves), the next-3-best non-division-winners
    in the league as seeds 4-6. Returns {league: DataFrame} with a `seed`
    column (1-6), one entry per league that has standings data."""
    standings = load_standings(db_mtime_val)
    if standings.empty:
        return {}
    standings = standings.dropna(subset=["team_abbr", "wins", "losses", "league"]).drop_duplicates("team_abbr")

    picture = {}
    for league in sorted(standings["league"].unique()):
        league_df = standings[standings["league"] == league].copy()
        # Rank by winning PERCENTAGE, not raw win total. Teams reach a given
        # date having played different numbers of games (rainouts, doubleheader
        # splits, an uneven schedule), so a 78-53 team is ahead of a 79-58 one
        # even though it has fewer wins — sorting on wins alone silently seeded
        # the bracket wrong whenever games-played diverged.
        games = league_df["wins"] + league_df["losses"]
        league_df["_win_pct"] = np.where(games > 0, league_df["wins"] / games.where(games > 0, 1), 0.0)
        # Real MLB tiebreakers are head-to-head/intradivision records, which we
        # don't carry. Falling through wins -> run differential -> abbr at least
        # makes the order deterministic, so an exact tie doesn't make the
        # bracket flip around between reruns on identical data.
        order, ascending = ["_win_pct", "wins", "run_diff", "team_abbr"], [False, False, False, True]
        div_winners = league_df[league_df["div_rank"] == "1"].sort_values(order, ascending=ascending)
        wildcards = (
            league_df[league_df["div_rank"] != "1"]
            .sort_values(order, ascending=ascending)
            .head(WILD_CARDS_PER_LEAGUE)
        )
        seeded = pd.concat([div_winners, wildcards], ignore_index=True).drop(columns="_win_pct")
        if seeded.empty:
            continue
        seeded.insert(0, "seed", range(1, len(seeded) + 1))
        picture[league] = seeded
    return picture


@st.cache_data(show_spinner=False, ttl=3600, max_entries=2)
def clinch_elimination_status(db_mtime_val: float) -> list[dict]:
    """Which teams have clinched a division, clinched at least a wild-card
    spot, or been mathematically eliminated from the postseason entirely —
    computed fresh from current standings + remaining schedule every time,
    so a clinch/elimination "sticks" for the rest of the season without any
    stored state (once true these can only stay true: wins don't decrease,
    games remaining only decreases).

    Uses the standard simplified magic-number approach (each contender
    compared against the *current* wins total of the team it needs to
    catch, not a full simulation of every remaining game's possible
    outcomes) — the same simplification most fan-facing standings pages
    use. It can be off by a game or two right at a tiebreaker boundary,
    but is correct in the vast majority of cases and self-corrects every
    time standings refresh."""
    standings = load_standings(db_mtime_val)
    schedule = load_schedule(db_mtime_val)
    if standings.empty or schedule.empty:
        return []
    standings = (
        standings.dropna(subset=["team_abbr", "wins", "losses", "league", "division", "div_rank"])
        .drop_duplicates("team_abbr").copy()
    )
    standings["wins"] = standings["wins"].astype(int)

    unplayed = schedule[schedule["status"] != "Final"]
    remaining = unplayed.groupby("home_abbr").size().add(unplayed.groupby("away_abbr").size(), fill_value=0)
    standings["games_remaining"] = standings["team_abbr"].map(remaining).fillna(0).astype(int)
    standings["max_wins"] = standings["wins"] + standings["games_remaining"]

    results = []
    for league in sorted(standings["league"].unique()):
        league_df = standings[standings["league"] == league]
        non_leaders = league_df[league_df["div_rank"] != "1"].sort_values("wins", ascending=False)

        for division in sorted(league_df["division"].unique()):
            div_df = league_df[league_df["division"] == division]
            leader = div_df.sort_values("wins", ascending=False).iloc[0]
            rivals = div_df[div_df["team_abbr"] != leader["team_abbr"]]
            if not rivals.empty and (leader["wins"] > rivals["max_wins"]).all():
                results.append({
                    "team_abbr": leader["team_abbr"], "team_name": leader["team_name"],
                    "kind": "division_clinch", "division": division,
                })

        if len(non_leaders) < WILD_CARDS_PER_LEAGUE:
            continue
        cutoff_wins = non_leaders.iloc[WILD_CARDS_PER_LEAGUE - 1]["wins"]
        if len(non_leaders) > WILD_CARDS_PER_LEAGUE:
            first_out_max_wins = non_leaders.iloc[WILD_CARDS_PER_LEAGUE]["max_wins"]
            for _, row in non_leaders.iloc[:WILD_CARDS_PER_LEAGUE].iterrows():
                if row["wins"] > first_out_max_wins:
                    results.append({
                        "team_abbr": row["team_abbr"], "team_name": row["team_name"],
                        "kind": "wildcard_clinch", "division": row["division"],
                    })

        for _, row in non_leaders.iterrows():
            # Strict "<": a team whose max possible wins only ties the
            # target isn't eliminated yet — a tie can still force a
            # tiebreaker game, so it's mathematically (if barely) alive.
            if row["max_wins"] >= cutoff_wins:
                continue
            own_leader = league_df[(league_df["division"] == row["division"]) & (league_df["div_rank"] == "1")]
            if not own_leader.empty and row["max_wins"] < own_leader.iloc[0]["wins"]:
                results.append({
                    "team_abbr": row["team_abbr"], "team_name": row["team_name"],
                    "kind": "eliminated", "division": row["division"],
                })
    return results


def moneyline_odds(prob: float) -> str:
    """Convert a win probability into American moneyline odds (our own
    calculated estimate — not a real sportsbook line)."""
    prob = min(max(prob, 0.01), 0.99)
    if prob >= 0.5:
        return f"{-round(100 * prob / (1 - prob)):d}"
    return f"+{round(100 * (1 - prob) / prob):d}"


WIN_MODEL_PARAMS_PATH = Path(__file__).resolve().parent / "win_model_params.json"


@st.cache_data(show_spinner=False)
def load_win_model_params() -> dict | None:
    """The trained Today's Games win-probability model — coefficients,
    standardization stats, and serve-time reference data (prior-season
    team strength and league ERA), produced offline by
    ingest/train_win_model.py (see its docstring for the training and
    backtesting protocol; the artifact's own "metrics" block records how
    it scored on held-out seasons). Returns None if the artifact is
    missing, in which case predict_game shows no odds rather than
    crashing the page."""
    try:
        return json.loads(WIN_MODEL_PARAMS_PATH.read_text())
    except Exception:
        return None


@st.cache_data(show_spinner=False, max_entries=2)
def _team_entering_stats(db_mtime_val: float) -> dict:
    """Per-team [games, wins, runs_for, runs_against] across the current
    season's completed games, from the ingested schedule table — the
    serve-time twin of the running per-season state
    ingest/train_win_model.py reconstructs during training, so the
    model's in-season features come from the same kind of inputs it was
    trained on."""
    schedule = load_schedule(db_mtime_val)
    stats: dict = {}
    if schedule.empty:
        return stats
    played = schedule[
        (schedule["status"] == "Final")
        & schedule["home_score"].notna() & schedule["away_score"].notna()
        & (schedule["home_score"] != schedule["away_score"])
    ]
    for _, g in played.iterrows():
        for abbr, scored, allowed in (
            (g["home_abbr"], g["home_score"], g["away_score"]),
            (g["away_abbr"], g["away_score"], g["home_score"]),
        ):
            s = stats.setdefault(abbr, [0, 0, 0.0, 0.0])
            s[0] += 1
            s[1] += 1 if scored > allowed else 0
            s[2] += float(scored)
            s[3] += float(allowed)
    return stats


def _starter_prior_era(mlbID, params: dict, db_mtime_val: float) -> float:
    """The probable starter's PRIOR-season ERA, clipped — mirroring the
    training feature exactly (see ingest/train_win_model.py's leakage
    notes for why prior-season rather than current-season ERA). An
    unknown or unqualified (< era_ip_min prior IP) starter gets the prior
    season's qualified league-average ERA, same as in training."""
    lo, hi = params["era_clip"]
    era = params["prior_league_era"]
    if mlbID is not None and not pd.isna(mlbID):
        prior = load_pitching(params["prior_season"], db_mtime_val)
        if not prior.empty:
            match = prior[(prior["mlbID"] == int(mlbID)) & (prior["IP"] >= params["era_ip_min"])]
            if not match.empty:
                best = match.sort_values("IP", ascending=False).iloc[0]
                if pd.notna(best["ERA"]):
                    era = float(best["ERA"])
    return min(max(era, lo), hi)


def predict_game(row: pd.Series, db_mtime_val: float) -> dict | None:
    """Home/away win probability for one row of todays_games, from a
    logistic-regression model trained and walk-forward backtested on
    2015-2025 games (see ingest/train_win_model.py) — replacing the old
    hand-tuned Log5-plus-adjustments formula, whose replayed
    probabilities scored worse than a coin flip on log-loss in every
    backtest season (systematically overconfident). Features, mirrored
    exactly from training: shrunk in-season record and run-differential
    diffs, shrunk prior-season record diff, the probable starters'
    prior-season ERA diff, and a learned home-field intercept. Still our
    own estimate — no injuries, park factors, weather, or external odds
    provider. Returns None only if the trained artifact
    (app/win_model_params.json) is missing."""
    params = load_win_model_params()
    if not params:
        return None
    k = params["k_shrink"]
    stats = _team_entering_stats(db_mtime_val)
    home_abbr = teams.normalize_mlb_abbr(row.get("home_abbr", ""))
    away_abbr = teams.normalize_mlb_abbr(row.get("away_abbr", ""))
    h = stats.get(home_abbr, [0, 0, 0.0, 0.0])
    a = stats.get(away_abbr, [0, 0, 0.0, 0.0])

    priors = params["prior_winpct_by_team_id"]
    h_id, a_id = teams.team_id_for_abbr(home_abbr), teams.team_id_for_abbr(away_abbr)
    h_era = _starter_prior_era(row.get("home_pitcher_mlbID"), params, db_mtime_val)
    a_era = _starter_prior_era(row.get("away_pitcher_mlbID"), params, db_mtime_val)
    feats = {
        "d_win": (h[1] + 0.5 * k) / (h[0] + k) - (a[1] + 0.5 * k) / (a[0] + k),
        "d_rundiff": (h[2] - h[3]) / (h[0] + k) - (a[2] - a[3]) / (a[0] + k),
        "d_prior": priors.get(str(h_id), 0.5) - priors.get(str(a_id), 0.5),
        "d_starter_era": a_era - h_era,
    }
    z = params["intercept"]
    for name, coef, mean, std in zip(params["features"], params["coef"], params["mean"], params["std"]):
        z += coef * ((feats[name] - mean) / (std or 1.0))
    home_prob = 1.0 / (1.0 + math.exp(-z))
    # Same display clamp the old formula used — the UI never claims a lock.
    home_prob = min(max(home_prob, 0.05), 0.95)
    return {
        "home_prob": home_prob,
        "away_prob": 1 - home_prob,
        "home_odds": moneyline_odds(home_prob),
        "away_odds": moneyline_odds(1 - home_prob),
    }


# ---------------------------------------------------------------------------
# Umpire scorecards. Zone-judgment constants and the signed-distance math
# are an exact MIRROR of ingest/ump_scorecards.py (see its docstring for
# the full methodology) — the ingest side grades finished games from
# Savant bulk data into the ump_games table; this side grades live/on-
# demand games straight from the play-by-play feed for the Umpires page's
# live scorecards and per-game zone plots. Keep the two in lockstep.
_UMP_BALL_RADIUS_FT = 0.1208
_UMP_HALF_PLATE_FT = 17 / 2 / 12
_UMP_ZONE_HALF_X = _UMP_HALF_PLATE_FT + _UMP_BALL_RADIUS_FT
UMP_CLEAR_MISS_IN = 1.0


def _ump_signed_distance_in(px: float, pz: float, sz_top: float, sz_bot: float) -> float:
    """Signed inches from the ball-radius-expanded strike region: negative
    = inside (depth to nearest boundary), positive = outside (euclidean
    distance to the region). Mirror of ingest/ump_scorecards.py."""
    lo_z, hi_z = sz_bot - _UMP_BALL_RADIUS_FT, sz_top + _UMP_BALL_RADIUS_FT
    dx = abs(px) - _UMP_ZONE_HALF_X
    dz = max(lo_z - pz, pz - hi_z)
    if dx <= 0 and dz <= 0:
        return 12.0 * max(dx, dz)
    return 12.0 * ((max(dx, 0.0) ** 2 + max(dz, 0.0) ** 2) ** 0.5)


@st.cache_data(show_spinner=False, max_entries=4)
def load_ump_games(db_mtime_val: float) -> pd.DataFrame:
    """Every graded game summary from the ump_games table (see
    ingest/ump_scorecards.py). Empty DataFrame before the backfill has
    ever run, same convention as every other optional table here."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            return pd.read_sql("SELECT * FROM ump_games", conn)
        except pd.errors.DatabaseError:
            return pd.DataFrame()


def ump_leaderboard(games: pd.DataFrame, season: int, min_games: int = 5) -> pd.DataFrame:
    """Season leaderboard with the difficulty adjustment: `vs Expected` is
    each ump's actual accuracy minus what a league-average ump would have
    scored on the SAME pitches — league accuracy per signed-distance
    bucket (that season), weighted by this ump's own bucket mix. Corrects
    for one ump catching more borderline pitches than another; a plain
    accuracy%% comparison would punish the harder schedule."""
    season_games = games[games["season"] == season]
    if season_games.empty:
        return pd.DataFrame()
    bucket_n = [f"b{i}_n" for i in range(6)]
    bucket_c = [f"b{i}_c" for i in range(6)]
    league_acc = [
        (season_games[c].sum() / season_games[n].sum()) if season_games[n].sum() else 1.0
        for n, c in zip(bucket_n, bucket_c)
    ]
    rows = []
    for (ump_id, ump_name), g in season_games.groupby(["ump_id", "ump_name"]):
        n_games = len(g)
        if n_games < min_games:
            continue
        called = int(g["called"].sum())
        correct = int(g["correct"].sum())
        expected = sum(g[n].sum() * acc for n, acc in zip(bucket_n, league_acc))
        rows.append({
            "Umpire": ump_name, "G": n_games, "Called": called,
            "Accuracy": 100 * correct / called,
            "vs Expected": 100 * (correct - expected) / called,
            "Wrong K": int(g["wrong_strikes"].sum()),
            "Wrong BB": int(g["wrong_balls"].sum()),
            "Clear Misses/G": g["clear_misses"].sum() / n_games,
        })
    out = pd.DataFrame(rows)
    return out.sort_values("Accuracy", ascending=False).reset_index(drop=True) if not out.empty else out


@st.cache_data(show_spinner=False, ttl=120, max_entries=30)
def load_ump_game_detail(game_pk) -> dict | None:
    """One game's full called-pitch detail, graded live from the play-by-
    play feed — powers both in-progress scorecards (nothing is in the DB
    yet mid-game) and the zone plot for any historical game (per-pitch
    locations aren't stored in ump_games; one cached feed fetch on demand
    beats permanently storing ~140 rows per game). Only human judgment
    calls count: codes C/B/*B (called strike / ball / ball in dirt),
    excluding automatic pitch-clock balls/strikes. Returns None when the
    feed is unavailable or has no called pitches yet."""
    try:
        resp = requests.get(
            f"https://statsapi.mlb.com/api/v1.1/game/{int(game_pk)}/feed/live", timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        return None
    officials = (raw.get("liveData") or {}).get("boxscore", {}).get("officials", [])
    hp = next((o for o in officials if o.get("officialType") == "Home Plate"), None)
    ump_name = ((hp or {}).get("official") or {}).get("fullName")

    pitches = []
    for play in (raw.get("liveData") or {}).get("plays", {}).get("allPlays", []) or []:
        for ev in play.get("playEvents", []):
            details = ev.get("details") or {}
            if details.get("code") not in ("C", "B", "*B"):
                continue
            if "utomatic" in (details.get("description") or ""):
                continue
            pdata = ev.get("pitchData") or {}
            coords = pdata.get("coordinates") or {}
            px, pz = coords.get("pX"), coords.get("pZ")
            sz_top, sz_bot = pdata.get("strikeZoneTop"), pdata.get("strikeZoneBottom")
            if px is None or pz is None or not sz_top or not sz_bot:
                continue
            d = _ump_signed_distance_in(px, pz, sz_top, sz_bot)
            is_strike_call = details["code"] == "C"
            pitches.append({
                "px": px, "pz": pz, "sz_top": sz_top, "sz_bottom": sz_bot,
                "call": "strike" if is_strike_call else "ball",
                "correct": (d <= 0) == is_strike_call,
                "d_in": round(d, 2),
            })
    if not pitches:
        return None
    correct = sum(1 for p in pitches if p["correct"])
    return {
        "ump_name": ump_name,
        "called": len(pitches),
        "correct": correct,
        "accuracy": 100 * correct / len(pitches),
        "wrong_strikes": sum(1 for p in pitches if not p["correct"] and p["call"] == "strike"),
        "wrong_balls": sum(1 for p in pitches if not p["correct"] and p["call"] == "ball"),
        "pitches": pitches,
    }


# Shohei Ohtani is the only player whose search/profile "roles" description
# shows both — everyone else shows a single primary role (see
# player_roles_label below). Without this, a position player who mopped up
# one inning in a blowout gets mislabeled "Pitcher", and a real starter who
# happened to bat under the old NL rules (e.g. Kershaw) gets mislabeled a
# hitter, just because they have at least one row in the other table.
TWO_WAY_PLAYER_MLBIDS = {660271}  # Shohei Ohtani


@st.cache_data(show_spinner=False)
def _player_role_totals(db_mtime_val: float) -> pd.DataFrame:
    """Career totals (summed across every cached season) of batting PA and
    pitching IP per mlbID — the basis for player_primary_role()."""
    with sqlite3.connect(DB_PATH) as conn:
        pa = pd.read_sql("SELECT mlbID, SUM(PA) AS total_pa FROM batting GROUP BY mlbID", conn)
        ip = pd.read_sql("SELECT mlbID, SUM(IP) AS total_ip FROM pitching GROUP BY mlbID", conn)
    return pa.merge(ip, on="mlbID", how="outer")


def player_primary_role(mlbID: int, db_mtime_val: float) -> str:
    """Batter vs Pitcher, decided by raw career PA vs raw career IP. A real
    everyday player racks up hundreds of PA a season against at most a
    handful of mop-up innings; a real pitcher racks up dozens to hundreds
    of IP against, at most (under the old NL rules), maybe 60-70 PA/season
    on the days he started. That gap is lopsided enough in both directions
    that a raw-count comparison doesn't need anything fancier."""
    totals = _player_role_totals(db_mtime_val)
    row = totals[totals["mlbID"] == mlbID]
    if row.empty:
        return "Batter"
    # A player with zero rows in one table (e.g. a pure pitcher who has
    # never batted) has NaN, not 0, for that side after the outer merge in
    # _player_role_totals -- "NaN or 0" evaluates to NaN (NaN is truthy in
    # Python), so a plain `or 0` fallback silently leaves it as NaN, which
    # then makes total_ip > total_pa always False (any comparison against
    # NaN is False) and wrongly returns "Batter" for real pitchers.
    total_pa = row.iloc[0]["total_pa"]
    total_pa = 0 if pd.isna(total_pa) else total_pa
    total_ip = row.iloc[0]["total_ip"]
    total_ip = 0 if pd.isna(total_ip) else total_ip
    return "Pitcher" if total_ip > total_pa else "Batter"


def player_roles_label(mlbID: int, db_mtime_val: float) -> str:
    """The "roles" string shown in search results and the profile caption.
    Only TWO_WAY_PLAYER_MLBIDS gets the dual "Batter / Pitcher" label —
    everyone else gets their single primary role."""
    if mlbID in TWO_WAY_PLAYER_MLBIDS:
        return "Batter / Pitcher"
    return player_primary_role(mlbID, db_mtime_val)


@st.cache_data(show_spinner=False)
def _player_name_index(season: int, db_mtime_val: float) -> pd.DataFrame:
    """Small (mlbID, Name, Tm, role, name_norm) index built once per season,
    so searches don't re-normalize every name on every keystroke/rerun."""
    batting = load_batting(season, db_mtime_val)
    pitching = load_pitching(season, db_mtime_val)

    frames = []
    for df, role in [(batting, "Batter"), (pitching, "Pitcher")]:
        small = df[["mlbID", "Name", "Tm"]].copy()
        small["role"] = role
        frames.append(small)
    combined = pd.concat(frames, ignore_index=True)
    combined["name_norm"] = combined["Name"].map(normalize_text)
    return combined


@st.cache_data(show_spinner=False)
def search_players(query: str, season: int, db_mtime_val: float) -> pd.DataFrame:
    """Search batters and pitchers by name (accent/case-insensitive substring match).
    Returns one row per player with their roles label (see player_roles_label)."""
    query_norm = normalize_text(query.strip())
    if not query_norm:
        return pd.DataFrame(columns=["mlbID", "Name", "Tm", "roles"])

    index = _player_name_index(season, db_mtime_val)
    matches = index[index["name_norm"].str.contains(query_norm, na=False, regex=False)]
    if matches.empty:
        return pd.DataFrame(columns=["mlbID", "Name", "Tm", "roles"])

    # A player with both a batting and pitching row this season can have a
    # different Tm in each (a mid-season trade correction applied to one
    # table but not the other, or a pitcher's incidental at-bat row) —
    # grouping by (mlbID, Tm) used to show that player TWICE, once per
    # team, one of them stale. Keep the batting row's Tm when both exist,
    # matching the player page's own team-of-record convention, and always
    # return exactly one row per mlbID.
    role_priority = {"Batter": 0, "Pitcher": 1}
    matches = matches.assign(_prio=matches["role"].map(role_priority))
    deduped = matches.sort_values("_prio").drop_duplicates(subset="mlbID", keep="first")
    deduped = deduped[["mlbID", "Name", "Tm"]].copy()
    deduped["roles"] = deduped["mlbID"].map(lambda m: player_roles_label(m, db_mtime_val))
    return deduped.sort_values("Name").reset_index(drop=True)


@st.cache_data(show_spinner=False)
def _player_name_index_all_seasons(db_mtime_val: float) -> pd.DataFrame:
    """Same idea as _player_name_index, but spans every cached season
    instead of just one — so retired/inactive players (e.g. Kershaw) are
    still searchable, not just whoever's active in the most recent season.
    Reads mlbID/Name/Tm/season directly via SQL rather than going through
    load_batting/load_pitching, since those pull every stat column and
    this only needs a name lookup. Keeps one row per (mlbID, role): the
    most recent season, since that's the season a profile click should
    open to (a retired player has no row in the current season)."""
    frames = []
    with sqlite3.connect(DB_PATH) as conn:
        for table, role in [("batting", "Batter"), ("pitching", "Pitcher")]:
            df = pd.read_sql(f"SELECT mlbID, Name, Tm, season FROM {table}", conn)
            df["role"] = role
            frames.append(df)
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values("season").drop_duplicates(subset=["mlbID", "role"], keep="last")
    combined["name_norm"] = combined["Name"].map(normalize_text)
    return combined.reset_index(drop=True)


@st.cache_data(show_spinner=False)
def search_players_all_seasons(query: str, db_mtime_val: float) -> pd.DataFrame:
    """Search batters and pitchers by name across every cached season (not
    just the current one) — used by the persistent sidebar search, so
    retired/inactive players are findable too. Returns one row per player
    with their roles label (see player_roles_label) and the most recent
    season they have a row in (the profile page opens to that season)."""
    query_norm = normalize_text(query.strip())
    if not query_norm:
        return pd.DataFrame(columns=["mlbID", "Name", "Tm", "roles", "season"])

    index = _player_name_index_all_seasons(db_mtime_val)
    matches = index[index["name_norm"].str.contains(query_norm, na=False, regex=False)]
    if matches.empty:
        return pd.DataFrame(columns=["mlbID", "Name", "Tm", "roles", "season"])

    # Each mlbID has at most one Batter row and one Pitcher row here (see
    # _player_name_index_all_seasons). Pick the row from whichever role has
    # the more recent season (a retired player's profile should open to
    # their actual last season); on a tie, prefer the batting row, matching
    # the player page's own team-of-record convention. This used to be a
    # plain .agg(Tm=("Tm","last"), season=("season","max")) after a bare
    # sort_values("season") — pandas' default sort isn't stable, so tied
    # rows landed in an unpredictable order, and Tm/season were aggregated
    # independently, so they could even end up pulled from two DIFFERENT
    # rows for the same player. Both bugs together are what made search
    # show an inconsistent/wrong team.
    role_priority = {"Batter": 0, "Pitcher": 1}
    matches = matches.assign(_prio=matches["role"].map(role_priority))
    picked = (
        matches.sort_values(["season", "_prio"], ascending=[False, True])
        .drop_duplicates(subset="mlbID", keep="first")
    )
    picked = picked[["mlbID", "Name", "Tm", "season"]].copy()
    picked["roles"] = picked["mlbID"].map(lambda m: player_roles_label(m, db_mtime_val))
    return picked.sort_values("Name").reset_index(drop=True)


# pybaseball has no Hall of Fame data, and there's no live source wired up
# here to scrape Baseball-Reference's HOF page — so this is a hand-curated
# list, not a query. Only covers players confirmed inducted as of when this
# list was last updated who also have a row somewhere in our 2010+ cached
# range (anyone who retired before 2010 never appears in this app at all,
# so there's no point listing them). MLB announces a new class each January
# and inducts in July — add a line here when that happens; this list may
# already be behind by the time you're reading it.
HALL_OF_FAME_MLBIDS = {
    116539: "Derek Jeter",
    121250: "Mariano Rivera",
    136880: "Roy Halladay",
    116706: "Chipper Jones",
    123272: "Jim Thome",
    116034: "Trevor Hoffman",
    115223: "Vladimir Guerrero",
    121358: "Iván Rodríguez",
    115135: "Ken Griffey Jr.",
    134181: "Adrian Beltré",
    115732: "Todd Helton",
    408045: "Joe Mauer",
    400085: "Ichiro Suzuki",
    282332: "CC Sabathia",
    123790: "Billy Wagner",
    120074: "David Ortiz",
}


# The underlying column names use a trailing "_plus" (SQL/pandas can't have
# a bare "+" in a column name) — this maps them to how they're actually
# written everywhere else (OPS+, ERA+, wRC+). Pass as a selectbox's
# format_func wherever one of these columns is a dropdown option, so the
# stored value (used for sorting/querying) stays the real column name while
# only the displayed text changes.
STAT_DISPLAY_LABELS = {
    "OPS_plus": "OPS+", "ERA_plus": "ERA+", "wRC_plus": "wRC+",
    "K_PCT": "K%", "BB_PCT": "BB%", "K_9": "K/9", "BB_9": "BB/9", "K_BB": "K/BB",
    "GB_FB": "GB/FB", "BAbip": "BABIP",
    "avg_exit_velo": "Avg Exit Velo", "max_exit_velo": "Max Exit Velo",
    "hard_hit_pct": "Hard-Hit%", "barrel_pct": "Barrel%",
    "contact_pct": "Contact%", "contact_pctile": "Contact Pctile",
    "chase_pct": "Chase%", "chase_pctile": "Chase Pctile",
    "bat_speed": "Bat Speed (mph)", "bat_speed_pctile": "Bat Speed Pctile",
    "xISO_pctile": "xISO Pctile", "xOBP_pctile": "xOBP Pctile",
    "xBA_diff": "BA − xBA", "xSLG_diff": "SLG − xSLG", "xwOBA_diff": "wOBA − xwOBA",
    "xERA_diff": "ERA − xERA",
    "sprint_speed": "Sprint Speed (ft/s)", "hp_to_1b": "Home-to-1st (s)",
    "baserunning_runs": "Baserunning Runs (BsR)",
    "avg_exit_velo_against": "Avg EV Against", "hard_hit_pct_against": "Hard-Hit% Against",
    "barrel_pct_against": "Barrel% Against",
    "fastball_velo": "Fastball Velo (mph)", "fastball_velo_pctile": "FB Velo Pctile",
    "induced_chase_pct": "Induced Chase%", "induced_chase_pctile": "Induced Chase Pctile",
    "xBA_against": "xBA Against", "xSLG_against": "xSLG Against", "xwOBA_against": "xwOBA Against",
    "HVS": "HVS (Hitting Value Score)",
}


# Curated so every option is a real column in BATTING_COLS/PITCHING_COLS —
# the player profile's "Career Arc" stat selector (see pages/_Player.py)
# offers exactly these, depending on the player's role.
CAREER_ARC_BATTING_STATS = ["OPS", "BA", "OBP", "SLG", "HR", "RBI", "WAR", "OPS_plus", "wRC_plus"]
CAREER_ARC_PITCHING_STATS = ["ERA", "WHIP", "SO", "WAR", "ERA_plus", "FIP"]
CAREER_ARC_FORMATS = {
    "OPS": "{:.3f}", "BA": "{:.3f}", "OBP": "{:.3f}", "SLG": "{:.3f}",
    "HR": "{:.0f}", "RBI": "{:.0f}", "WAR": "{:.1f}", "OPS_plus": "{:.0f}", "wRC_plus": "{:.0f}",
    "ERA": "{:.2f}", "WHIP": "{:.3f}", "SO": "{:.0f}", "ERA_plus": "{:.0f}", "FIP": "{:.2f}",
}


@st.cache_data(show_spinner=False, max_entries=300)
def player_career_arc(mlbID: int, is_batter: bool, stat_col: str, db_mtime_val: float) -> pd.DataFrame:
    """Season-by-season value of `stat_col` (must be one of
    CAREER_ARC_BATTING_STATS/CAREER_ARC_PITCHING_STATS) for one player
    across every cached season (2020+, whatever's been backfilled), oldest
    to newest — feeds the "Career Arc" chart on the player profile page.
    Seasons the player has no row in are simply skipped, not filled with
    a placeholder, so a short career just produces a short line."""
    table = "batting" if is_batter else "pitching"
    with sqlite3.connect(DB_PATH) as conn:
        try:
            df = pd.read_sql(
                f'SELECT season, "{stat_col}" AS stat FROM {table} WHERE mlbID = ? ORDER BY season',
                conn, params=(int(mlbID),),
            )
        except pd.errors.DatabaseError:
            return pd.DataFrame(columns=["season", "stat"])
    return df.dropna(subset=["stat"])


@st.cache_data(show_spinner=False)
def league_aging_curve(is_batter: bool, stat_col: str, db_mtime_val: float) -> pd.DataFrame:
    """League-wide average of `stat_col` (must be one of
    CAREER_ARC_BATTING_STATS/CAREER_ARC_PITCHING_STATS) by age, computed
    across every cached season combined and restricted to a qualification
    threshold (PA>=100 / IP>=20) so noise from tiny partial-season samples
    doesn't distort the shape. One row per whole-number age — feeds the
    Career Arc chart's "By Age" mode background line on the player
    profile page."""
    table = "batting" if is_batter else "pitching"
    qual_col, qual_min = ("PA", 100) if is_batter else ("IP", 20)
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql(
            f'SELECT Age, "{stat_col}" AS stat FROM {table} WHERE {qual_col} >= ?',
            conn, params=(qual_min,),
        )
    df = df.dropna(subset=["Age", "stat"])
    df["Age"] = df["Age"].round().astype(int)
    return df.groupby("Age")["stat"].mean().reset_index().sort_values("Age")


@st.cache_data(show_spinner=False, max_entries=300)
def player_aging_points(mlbID: int, is_batter: bool, stat_col: str, db_mtime_val: float) -> pd.DataFrame:
    """One player's own (Age, `stat_col`) points across every cached season —
    no qualification threshold, unlike league_aging_curve, since we want
    this specific player's full career shown regardless of playing time.
    Overlaid on league_aging_curve's line in the Career Arc chart's "By
    Age" mode on the player profile page."""
    table = "batting" if is_batter else "pitching"
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql(
            f'SELECT Age, "{stat_col}" AS stat FROM {table} WHERE mlbID = ? ORDER BY Age',
            conn, params=(int(mlbID),),
        )
    return df.dropna(subset=["Age", "stat"])


@st.cache_data(show_spinner=False, max_entries=300)
def get_player_name(mlbID: int, db_mtime_val: float) -> str | None:
    """This player's Name from their most recent batting or pitching row —
    used to hydrate a shared player-page link (?mlbid=...), which only
    carries the ID, not the display name."""
    with sqlite3.connect(DB_PATH) as conn:
        for table in ("batting", "pitching"):
            row = conn.execute(
                f"SELECT Name FROM {table} WHERE mlbID = ? ORDER BY season DESC LIMIT 1", (mlbID,),
            ).fetchone()
            if row:
                return row[0]
    return None


@st.cache_data(show_spinner=False, max_entries=300)
def player_seasons(mlbID: int, db_mtime_val: float) -> list[int]:
    """Every season a player has a row in — batting, pitching, or fielding
    combined — sorted most recent first. Feeds the "Season" selectbox on
    the player profile page so a retired player's dropdown only offers
    seasons they actually played, instead of every cached season (picking
    a season past their retirement just hit the "no stats found" dead
    end)."""
    with sqlite3.connect(DB_PATH) as conn:
        seasons = set()
        for table in ("batting", "pitching", "fielding"):
            try:
                rows = conn.execute(f"SELECT DISTINCT season FROM {table} WHERE mlbID = ?", (int(mlbID),)).fetchall()
            except sqlite3.OperationalError:
                continue
            seasons.update(r[0] for r in rows)
    return sorted(seasons, reverse=True)


def percentile_rank(series: pd.Series, value, lower_is_better: bool = False) -> int | None:
    """Percentile of `value` within `series` (0-100). For lower_is_better
    stats (ERA, WHIP, ...) a lower value yields a higher percentile."""
    clean = series.dropna()
    if value is None or pd.isna(value) or len(clean) == 0:
        return None
    if lower_is_better:
        pct = (clean >= value).mean() * 100
    else:
        pct = (clean <= value).mean() * 100
    return int(round(pct))


def _zscore(series: pd.Series) -> pd.Series:
    std = series.std()
    if not std or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


# Rate/percentage stats only (never raw counting stats like HR or SO) so a
# part-timer and a full-time regular with the same underlying skill profile
# still land close together — a counting stat would separate them purely on
# playing time, which isn't what "statistically similar" should mean.
SIMILARITY_BATTING_STATS = [
    "BA", "OBP", "SLG", "ISO", "BB_PCT", "K_PCT", "wRC_plus",
    "sprint_speed", "barrel_pct", "hard_hit_pct",
]
SIMILARITY_PITCHING_STATS = [
    "ERA", "FIP", "WHIP", "K_9", "BB_9", "ERA_plus", "xERA", "hard_hit_pct_against",
]
SIMILARITY_MIN_PA = 50
SIMILARITY_MIN_IP = 20


def similar_players(mlbID: int, season: int, is_batter: bool, db_mtime_val: float, n: int = 5) -> pd.DataFrame:
    """The `n` most statistically similar qualified players (same season,
    same batter/pitcher role) to `mlbID`, by Euclidean distance across
    z-scored rate stats (see SIMILARITY_BATTING_STATS/SIMILARITY_PITCHING_STATS)
    — not real scouting comps, just "whose statistical profile this season
    looks like this one." A stat missing for a given player (e.g. sprint
    speed before Statcast tracked it) is treated as league-average for that
    one column rather than excluding the player entirely.
    Returns columns: mlbID, Name, Tm, Lev, distance (lower = more similar)."""
    df = load_batting(season, db_mtime_val) if is_batter else load_pitching(season, db_mtime_val)
    min_col, min_val = ("PA", SIMILARITY_MIN_PA) if is_batter else ("IP", SIMILARITY_MIN_IP)
    stats = SIMILARITY_BATTING_STATS if is_batter else SIMILARITY_PITCHING_STATS
    stats = [s for s in stats if s in df.columns]

    pool = df[df[min_col] >= min_val].copy()
    if mlbID not in pool["mlbID"].values or len(pool) < 2 or not stats:
        return pd.DataFrame(columns=["mlbID", "Name", "Tm", "Lev", "distance"])

    z = pool[stats].apply(_zscore).fillna(0.0)
    target_pos = pool.index.get_loc(pool.index[pool["mlbID"] == mlbID][0])
    target_vec = z.iloc[target_pos]
    distance = ((z - target_vec) ** 2).sum(axis=1) ** 0.5

    result = pool[["mlbID", "Name", "Tm", "Lev"]].assign(distance=distance.values)
    return result[result["mlbID"] != mlbID].sort_values("distance").head(n).reset_index(drop=True)


MVP_MIN_PA = 200
CY_YOUNG_MIN_IP = 40


PITCHER_MVP_DISCOUNT = 0.5  # pure-pitcher WAR z-score multiplier — see mvp_race docstring


@st.cache_data(show_spinner=False, max_entries=16)
def mvp_race(season: int, league: str, db_mtime_val: float) -> pd.DataFrame:
    """WAR-anchored MVP composite for one league/season, spanning both
    batters and pitchers. Batters: 50% WAR / 25% wRC+ (pure offensive
    production — still the biggest driver of real MVP narratives) / 12.5%
    BsR / 12.5% OAA (baserunning and defense get smaller, equal shares
    since WAR already partly prices them in — they reward a genuinely
    all-around player over a one-dimensional slugger with similar WAR, not
    double-counting).

    A two-way player (qualifies as both a batter and a pitcher in the same
    league/season — i.e. Ohtani) is one combined row, not two: their
    pitching WAR is added to their batting WAR before scoring, and the
    batting-side formula above still applies for wRC+/BsR/OAA. Every other
    pitcher is scored on WAR alone, but discounted by
    PITCHER_MVP_DISCOUNT — in real MVP voting a pitcher (even a great one)
    is a rare down-ballot mention, not a top-5 regular, and an undiscounted
    WAR z-score let pitchers crowd out batters unrealistically (4 of a
    league's top 5 were pitchers before this discount existed). WAR is
    z-scored across the combined pool (batters with two-way WAR already
    folded in, plus pure pitchers) so every role lands on one scale before
    the discount is applied. Not real award-voting data — a stats-only
    proxy, sorted by "MVP Score" descending."""
    batting = load_batting(season, db_mtime_val)
    pitching = load_pitching(season, db_mtime_val)
    fielding = load_fielding(season, db_mtime_val)

    bat = batting[(batting["Lev"] == league) & (batting["PA"] >= MVP_MIN_PA)].copy()
    pit = pitching[(pitching["Lev"] == league) & (pitching["IP"] >= CY_YOUNG_MIN_IP)].copy()
    if bat.empty and pit.empty:
        return pd.DataFrame()

    two_way_ids = set(bat["mlbID"]) & set(pit["mlbID"])
    pit_war_by_id = pit.set_index("mlbID")["WAR"]
    if not bat.empty:
        bat["WAR"] = bat.apply(
            lambda r: r["WAR"] + pit_war_by_id.get(r["mlbID"], 0.0) if r["mlbID"] in two_way_ids else r["WAR"],
            axis=1,
        )
        bat["Role"] = bat["mlbID"].apply(lambda i: "Two-Way" if i in two_way_ids else "Batter")
    pure_pit = pit[~pit["mlbID"].isin(two_way_ids)].copy()

    combined_war = pd.concat([bat["WAR"], pure_pit["WAR"]], ignore_index=True).fillna(0.0)
    war_mean, war_std = combined_war.mean(), combined_war.std()

    def _war_z(series: pd.Series) -> pd.Series:
        filled = series.fillna(0.0)
        if not war_std or pd.isna(war_std):
            return pd.Series(0.0, index=series.index)
        return (filled - war_mean) / war_std

    rows = []
    if not bat.empty:
        if not fielding.empty and "player_id" in fielding.columns:
            oaa_by_player = fielding.groupby("player_id")["OAA"].sum()
            bat["OAA"] = bat["mlbID"].map(oaa_by_player).fillna(0.0)
        else:
            bat["OAA"] = 0.0
        bat["baserunning_runs"] = bat["baserunning_runs"].fillna(0.0)
        wrc_plus_filled = bat["wRC_plus"].fillna(bat["wRC_plus"].mean())
        bat["MVP Score"] = (
            0.50 * _war_z(bat["WAR"])
            + 0.25 * _zscore(wrc_plus_filled)
            + 0.125 * _zscore(bat["baserunning_runs"])
            + 0.125 * _zscore(bat["OAA"])
        )
        rows.append(bat)
    if not pure_pit.empty:
        pure_pit["wRC_plus"] = float("nan")
        pure_pit["baserunning_runs"] = float("nan")
        pure_pit["OAA"] = float("nan")
        pure_pit["MVP Score"] = PITCHER_MVP_DISCOUNT * _war_z(pure_pit["WAR"])
        pure_pit["Role"] = "Pitcher"
        rows.append(pure_pit)

    combined = pd.concat(rows, ignore_index=True, sort=False)
    return combined.sort_values("MVP Score", ascending=False).reset_index(drop=True)


CY_YOUNG_RELIABILITY_IP = 100  # innings at which FIP/ERA+ get roughly half their full weight


@st.cache_data(show_spinner=False, max_entries=16)
def cy_young_race(season: int, league: str, db_mtime_val: float) -> pd.DataFrame:
    """WAR-anchored Cy Young composite for one league/season, pitchers
    only: 50% WAR (rewards durability/innings along with rate performance),
    30% FIP (the most defense-independent, skill-isolating rate stat), 20%
    ERA+ (park/league-adjusted actual results, correlated with FIP but adds
    real-outcome context). FIP is lower-is-better, so its z-score is
    negated before weighting.

    The FIP/ERA+ terms are scaled by a reliability factor (IP / (IP + 100))
    before weighting — without it, a reliever with a small, dominant IP
    sample (gaudy rate stats over 40-50 innings) can post a more extreme
    z-score than any full-workload starter and land at #1 by a landslide,
    which isn't realistic (real Cy Young cases for relievers exist but are
    rare and never landslides). WAR itself isn't shrunk, since it already
    reflects the pitcher's actual (limited) workload. This tempers a short-
    relief season rather than excluding it — reliability approaches 1 as
    IP grows, so it only meaningfully discounts pitchers with a small
    innings total. Not real award-voting data — a stats-only proxy, sorted
    by "Cy Young Score" descending."""
    pitching = load_pitching(season, db_mtime_val)
    pit = pitching[(pitching["Lev"] == league) & (pitching["IP"] >= CY_YOUNG_MIN_IP)].copy()
    if pit.empty:
        return pit

    fip_filled = pit["FIP"].fillna(pit["FIP"].mean())
    era_plus_filled = pit["ERA_plus"].fillna(pit["ERA_plus"].mean())
    reliability = pit["IP"] / (pit["IP"] + CY_YOUNG_RELIABILITY_IP)

    pit["Cy Young Score"] = (
        0.50 * _zscore(pit["WAR"].fillna(0.0))
        + 0.30 * _zscore(-fip_filled) * reliability
        + 0.20 * _zscore(era_plus_filled) * reliability
    )
    return pit.sort_values("Cy Young Score", ascending=False).reset_index(drop=True)


ROOKIE_MAX_CAREER_AB = 130
ROOKIE_MAX_CAREER_IP = 50

# The real MLB rookie-eligibility rule has a third clause this app can't
# check from AB/IP alone: a player also loses rookie status after more than
# 45 days on a Major League club's active roster (excluding IL time) before
# rosters expand on September 1, even with a low AB/IP total. There's no
# active-roster-days data available here to compute that automatically, so
# players known to be excluded on that clause are listed manually.
# mlbID -> short note on why.
ROOKIE_MANUAL_EXCLUSIONS = {
    695505: "Chase Burns — exceeded 45 days on the Reds' active roster before rosters expanded",
}


@st.cache_data(show_spinner=False, max_entries=16)
def rookie_of_the_year_race(season: int, league: str, db_mtime_val: float) -> pd.DataFrame:
    """Rookie of the Year candidates for one league/season, real MLB rule:
    fewer than 130 career AB AND fewer than 50 career IP in the majors
    before this season, AND not on ROOKIE_MANUAL_EXCLUSIONS (the rule's
    third clause — 45+ days on an active MLB roster — which needs
    roster-day data this app doesn't have, so exceptions are tracked by
    hand there). Checked against every earlier season in this database —
    a player who cleared those limits before 2008 (the app's earliest
    season) would be misclassified as still rookie-eligible here, the
    same "since 2008" caveat as the rest of the app.

    Batters are scored with the MVP formula, pitchers with the Cy Young
    formula (see mvp_race/cy_young_race) — both are z-scores within their
    own league/season pool, so they land on a comparable scale and can be
    ranked together in one combined "ROY Score" list."""
    with sqlite3.connect(DB_PATH) as conn:
        prior_ab = pd.read_sql(
            "SELECT mlbID, SUM(AB) AS career_ab FROM batting WHERE season < ? GROUP BY mlbID",
            conn, params=(season,),
        )
        prior_ip = pd.read_sql(
            "SELECT mlbID, SUM(IP) AS career_ip FROM pitching WHERE season < ? GROUP BY mlbID",
            conn, params=(season,),
        )
    ab_by_id = prior_ab.set_index("mlbID")["career_ab"]
    ip_by_id = prior_ip.set_index("mlbID")["career_ip"]

    def _is_rookie_eligible(mlbID) -> bool:
        if mlbID in ROOKIE_MANUAL_EXCLUSIONS:
            return False
        return ab_by_id.get(mlbID, 0) < ROOKIE_MAX_CAREER_AB and ip_by_id.get(mlbID, 0) < ROOKIE_MAX_CAREER_IP

    mvp = mvp_race(season, league, db_mtime_val)
    cy = cy_young_race(season, league, db_mtime_val)

    rookies = []
    if not mvp.empty:
        bat_pool = mvp[mvp["Role"].isin(["Batter", "Two-Way"])]
        bat_rookies = bat_pool[bat_pool["mlbID"].apply(_is_rookie_eligible)].copy()
        bat_rookies["ROY Score"] = bat_rookies["MVP Score"]
        rookies.append(bat_rookies)
    if not cy.empty:
        pit_rookies = cy[cy["mlbID"].apply(_is_rookie_eligible)].copy()
        pit_rookies["Role"] = "Pitcher"
        pit_rookies["ROY Score"] = pit_rookies["Cy Young Score"]
        rookies.append(pit_rookies)

    if not rookies:
        return pd.DataFrame()
    combined = pd.concat(rookies, ignore_index=True, sort=False)
    return combined.sort_values("ROY Score", ascending=False).reset_index(drop=True)


def get_player_batting(mlbID, season: int, db_mtime_val: float) -> pd.Series | None:
    batting = load_batting(season, db_mtime_val)
    match = batting[batting["mlbID"] == mlbID]
    return match.iloc[0] if len(match) else None


def get_player_pitching(mlbID, season: int, db_mtime_val: float) -> pd.Series | None:
    pitching = load_pitching(season, db_mtime_val)
    match = pitching[pitching["mlbID"] == mlbID]
    return match.iloc[0] if len(match) else None


def get_player_fielding(mlbID, season: int, db_mtime_val: float) -> pd.DataFrame:
    fielding = load_fielding(season, db_mtime_val)
    return fielding[fielding["player_id"] == mlbID].reset_index(drop=True)


def get_player_pitch_arsenal(mlbID, season: int, db_mtime_val: float) -> pd.DataFrame:
    """One row per pitch type a pitcher threw that season (velocity, usage%,
    whiff%, run value, movement), sorted by usage — most-thrown pitch
    first. Empty if the season has no pitch_arsenal table yet (older
    backfilled seasons) or the pitcher didn't clear Savant's attempt floor."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            df = pd.read_sql(
                "SELECT * FROM pitch_arsenal WHERE season = ? AND mlbID = ?",
                conn, params=(season, mlbID),
            )
        except pd.errors.DatabaseError:
            return pd.DataFrame()
    return df.sort_values("usage_pct", ascending=False).reset_index(drop=True)


@st.cache_data(show_spinner=False, ttl=3600 * 6, max_entries=40)
def load_split_stats(mlbID: int, season: int, group: str) -> dict:
    """Home/Away and vs-Left/vs-Right split stats for one player/season —
    live from the MLB Stats API (sitCodes=h,a,vl,vr), not part of the daily
    ingest (splits are a per-player on-demand lookup, not something every
    page needs pre-aggregated). `group` is "hitting" or "pitching". Returns
    {"Home": {...}, "Away": {...}, "vs LHP"/"vs LHB": {...}, "vs RHP"/"vs RHB": {...}},
    each a dict of the raw MLB Stats API stat fields — empty dict for a
    split with no at-bats/innings yet. Returns {} entirely on any fetch
    failure or if the player has no stats this season."""
    label_map = (
        {"h": "Home", "a": "Away", "vl": "vs LHP", "vr": "vs RHP"} if group == "hitting"
        else {"h": "Home", "a": "Away", "vl": "vs LHB", "vr": "vs RHB"}
    )
    try:
        resp = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{int(mlbID)}/stats",
            params={"stats": "statSplits", "group": group, "season": season, "sitCodes": "h,a,vl,vr"},
            timeout=15,
        )
        resp.raise_for_status()
        splits = resp.json().get("stats", [{}])[0].get("splits", [])
    except Exception:
        return {}

    result = {}
    for s in splits:
        code = s.get("split", {}).get("code")
        label = label_map.get(code)
        if label:
            result[label] = s.get("stat", {})
    return result


@st.cache_data(show_spinner=False, ttl=3600 * 6, max_entries=20)
def load_pitch_locations(mlbID: int, season: int) -> pd.DataFrame:
    """Every individual pitch a pitcher threw in `season` (plate_x/plate_z
    location, pitch type, outcome, and the count it was thrown on), for
    plotting a strike-zone heatmap and a pitch-mix-by-count breakdown —
    live per-pitch Statcast data via pybaseball, not part of the daily
    ingest (the pitch_arsenal table only stores pre-aggregated per-pitch-
    type summaries, not individual pitches, and pulling every pitch for
    every pitcher every day would be a much heavier ingest for a chart
    almost nobody will open). Cached a few hours since this is an
    expensive network call (~20-30s) independent of stats.db, so it isn't
    keyed to db_mtime — it refetches on its own schedule as the season
    progresses, not when the daily batting/pitching refresh runs."""
    import pybaseball as pb

    try:
        df = pb.statcast_pitcher(f"{season}-01-01", f"{season}-12-31", int(mlbID))
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty or "plate_x" not in df.columns:
        return pd.DataFrame()
    cols = ["plate_x", "plate_z", "pitch_type", "pitch_name", "description", "events", "balls", "strikes"]
    return df[[c for c in cols if c in df.columns]].dropna(subset=["plate_x", "plate_z"])


def _load_optional_table(table: str, season: int, db_mtime_val: float) -> pd.DataFrame:
    """Generic loader for the newer season-keyed Statcast tables (batted
    ball, bat tracking, catcher framing/pop time, outfielder jump) that
    may not exist yet on an older DB snapshot, or have no rows for a
    season the underlying Statcast system didn't cover (bat tracking
    pre-2023, any of them pre-2015, catcher/outfield ones for a season
    with no qualifying catchers/outfielders)."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            return pd.read_sql(f"SELECT * FROM {table} WHERE season = ?", conn, params=(season,))
        except pd.errors.DatabaseError:
            return pd.DataFrame()


@st.cache_data(show_spinner=False, max_entries=4)
def load_batted_ball(season: int, db_mtime_val: float) -> pd.DataFrame:
    return _load_optional_table("batted_ball", season, db_mtime_val)


@st.cache_data(show_spinner=False, max_entries=4)
def load_bat_tracking(season: int, db_mtime_val: float) -> pd.DataFrame:
    return _load_optional_table("bat_tracking", season, db_mtime_val)


@st.cache_data(show_spinner=False, max_entries=4)
def load_pitch_arsenal(season: int, db_mtime_val: float) -> pd.DataFrame:
    """League-wide per-pitcher/per-pitch-type arsenal rows for one season
    (the Pitch Lab page). get_player_pitch_arsenal is the single-player
    variant used on player profiles."""
    return _load_optional_table("pitch_arsenal", season, db_mtime_val)


@st.cache_data(show_spinner=False, max_entries=2)
def load_pitch_arsenal_all_seasons(db_mtime_val: float) -> pd.DataFrame:
    """Every stored season at once — for the Pitch Lab's year-over-year
    arsenal-change views (velocity trends, new pitches, usage shifts)."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            return pd.read_sql("SELECT * FROM pitch_arsenal", conn)
        except pd.errors.DatabaseError:
            return pd.DataFrame()


@st.cache_data(show_spinner=False, max_entries=2)
def load_hr_log(db_mtime_val: float) -> pd.DataFrame:
    """Every stored home run's landing data across all cached seasons
    (ingest/ballparks.py), for the Ballparks tab's 3D museum."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            return pd.read_sql("SELECT * FROM hr_log", conn)
        except pd.errors.DatabaseError:
            return pd.DataFrame()


@st.cache_data(show_spinner=False, max_entries=2)
def load_park_games(db_mtime_val: float) -> pd.DataFrame:
    """Per-game final scores with the hosting park, for park factors."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            return pd.read_sql("SELECT * FROM park_games", conn)
        except pd.errors.DatabaseError:
            return pd.DataFrame()


@st.cache_data(show_spinner=False, max_entries=2)
def park_factors(db_mtime_val: float) -> pd.DataFrame:
    """Our own park factors, one row per team's park: runs and HR per game
    in that team's home games vs. that same team's road games, indexed to
    100 = neutral. Multi-season (everything in park_games), so a single
    weird year doesn't swing a park's number."""
    games = load_park_games(db_mtime_val)
    hr = load_hr_log(db_mtime_val)
    if games.empty:
        return pd.DataFrame()
    games = games.assign(total=games["home_final"] + games["away_final"])
    hr_per_game = hr.groupby("game_pk").size().rename("hr_n") if not hr.empty else pd.Series(dtype=float)
    games = games.merge(hr_per_game, left_on="game_pk", right_index=True, how="left")
    games["hr_n"] = games["hr_n"].fillna(0)

    rows = []
    for team in sorted(games["home_team"].dropna().unique()):
        home = games[games["home_team"] == team]
        road = games[games["away_team"] == team]
        if len(home) < 50 or len(road) < 50:
            continue
        run_factor = (home["total"].mean() / road["total"].mean()) * 100 if road["total"].mean() else None
        hr_factor = (home["hr_n"].mean() / road["hr_n"].mean()) * 100 if road["hr_n"].mean() else None
        rows.append({
            "team": team, "games": len(home),
            "run_factor": run_factor, "hr_factor": hr_factor,
        })
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False, max_entries=4)
def load_catcher_framing(season: int, db_mtime_val: float) -> pd.DataFrame:
    return _load_optional_table("catcher_framing", season, db_mtime_val)


@st.cache_data(show_spinner=False, max_entries=4)
def load_catcher_poptime(season: int, db_mtime_val: float) -> pd.DataFrame:
    return _load_optional_table("catcher_poptime", season, db_mtime_val)


@st.cache_data(show_spinner=False, max_entries=4)
def load_outfield_jump(season: int, db_mtime_val: float) -> pd.DataFrame:
    return _load_optional_table("outfield_jump", season, db_mtime_val)


@st.cache_data(show_spinner=False, max_entries=4)
def load_player_history(mlbID, season: int, db_mtime_val: float) -> pd.DataFrame:
    """Day-over-day OPS/ERA (season-to-date) and day_PA/day_H/day_IP/day_ER
    (that day's single-game line) for one player, from the append-only
    player_history table. Builds up real history from the day this feature
    shipped onward — there's no backfill for past dates."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            df = pd.read_sql(
                "SELECT date, role, PA, OPS, IP, ERA, day_PA, day_H, day_IP, day_ER "
                "FROM player_history WHERE mlbID = ? AND season = ? ORDER BY date",
                conn, params=(int(mlbID), season),
            )
        except pd.errors.DatabaseError:
            return pd.DataFrame()
    return df


def current_hit_streak(history: pd.DataFrame) -> int | None:
    """Consecutive most-recent game days with a hit, walking backward from
    the latest logged date. Days with no game (day_PA is null/0) are skipped
    rather than breaking the streak. Returns None if there's no game data yet."""
    games = history[history["day_PA"].fillna(0) > 0].sort_values("date", ascending=False)
    if games.empty:
        return None
    streak = 0
    for _, row in games.iterrows():
        if row["day_H"] and row["day_H"] > 0:
            streak += 1
        else:
            break
    return streak


def current_scoreless_streak(history: pd.DataFrame) -> int | None:
    """Consecutive most-recent outings with zero earned runs, walking backward
    from the latest logged appearance. Returns None if no outing data yet."""
    outings = history[history["day_IP"].fillna(0) > 0].sort_values("date", ascending=False)
    if outings.empty:
        return None
    streak = 0
    for _, row in outings.iterrows():
        if row["day_ER"] == 0:
            streak += 1
        else:
            break
    return streak


def db_mtime() -> float:
    return DB_PATH.stat().st_mtime if DB_PATH.exists() else 0.0




# ---------------------------------------------------------------------------
# P.R.O.P.+ (ingest/mlb_prop.py) — our pitch-quality model. Like the NHL's
# SLOT, the app only ever reads scored values from SQLite; it never loads
# the trained model, so scikit-learn stays out of the deployed app.
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, max_entries=4)
def load_pitcher_prop(season: int, db_mtime_val: float) -> pd.DataFrame:
    """One usage-weighted PROP+ per pitcher for a season."""
    if not DB_PATH.exists():
        return pd.DataFrame(columns=["mlbID", "prop_plus", "pitches", "pa"])
    with sqlite3.connect(DB_PATH) as conn:
        try:
            return pd.read_sql("SELECT mlbID, prop_plus, pitches, pa FROM pitcher_prop "
                               "WHERE season = ?", conn, params=(season,))
        except (pd.errors.DatabaseError, sqlite3.OperationalError):
            return pd.DataFrame(columns=["mlbID", "prop_plus", "pitches", "pa"])


@st.cache_data(show_spinner=False, max_entries=4)
def load_pitch_prop(season: int, db_mtime_val: float) -> pd.DataFrame:
    """Every individual pitch grade for a season — one row per pitcher per
    pitch type, for the per-arsenal breakdown."""
    if not DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_PATH) as conn:
        try:
            return pd.read_sql("SELECT * FROM pitch_prop WHERE season = ?", conn, params=(season,))
        except (pd.errors.DatabaseError, sqlite3.OperationalError):
            return pd.DataFrame()
