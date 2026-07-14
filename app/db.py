"""Shared helpers for reading the cached stats database."""
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

import teams

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "stats.db"


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
    "hard_hit_pct", "barrel_pct", "xwOBA", "xBA", "xSLG",
    "xBA_diff", "xSLG_diff", "xwOBA_diff", "OPS_plus", "wRC_plus", "WAR",
    "sprint_speed", "hp_to_1b", "baserunning_runs", "season",
]
PITCHING_COLS = [
    "Name", "Age", "Lev", "Tm", "G", "GS", "W", "L", "SV", "IP", "ERA", "WHIP",
    "SO", "BB", "HR", "mlbID", "K_9", "BB_9", "K_BB", "FIP", "xERA", "BAbip", "GB_FB",
    "xBA_against", "xSLG_against", "xwOBA_against", "xERA_diff", "ERA_plus", "WAR",
    "avg_exit_velo_against", "hard_hit_pct_against", "barrel_pct_against", "season",
]
FIELDING_COLS = ["Name", "player_id", "Tm", "Pos", "OAA", "FRP", "success_rate", "arm_strength", "season"]
RECENT_BATTING_COLS = ["mlbID", "Name", "Tm", "Lev", "PA", "H", "2B", "3B", "HR", "RBI", "SB", "OPS", "period", "season"]
RECENT_PITCHING_COLS = ["mlbID", "Name", "Tm", "Lev", "IP", "ERA", "GSc", "SO", "ER", "BB", "HBP", "H", "SV", "period", "season"]


def _select(cols: list[str]) -> str:
    return ", ".join(f'"{c}"' for c in cols)


@st.cache_data(show_spinner=False, max_entries=4)
def load_batting(season: int, _db_mtime: float) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql(
            f"SELECT {_select(BATTING_COLS)} FROM batting WHERE season = ?", conn, params=(season,)
        )
    return _downcast(df)


@st.cache_data(show_spinner=False, max_entries=4)
def load_pitching(season: int, _db_mtime: float) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql(
            f"SELECT {_select(PITCHING_COLS)} FROM pitching WHERE season = ?", conn, params=(season,)
        )
    return _downcast(df)


@st.cache_data(show_spinner=False, max_entries=4)
def load_fielding(season: int, _db_mtime: float) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql(
            f"SELECT {_select(FIELDING_COLS)} FROM fielding WHERE season = ?", conn, params=(season,)
        )
    return _downcast(df)


RECENT_MIN_PA = {"day": 3, "week": 15, "month": 50}
RECENT_MIN_IP = {"day": 1, "week": 8, "month": 20}


@st.cache_data(show_spinner=False, max_entries=4)
def load_recent_batting(season: int, _db_mtime: float) -> pd.DataFrame:
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
def load_recent_pitching(season: int, _db_mtime: float) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        try:
            df = pd.read_sql(
                f"SELECT {_select(RECENT_PITCHING_COLS)} FROM recent_pitching WHERE season = ?",
                conn, params=(season,),
            )
        except pd.errors.DatabaseError:
            return pd.DataFrame()
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
        scores[g.get("gamePk")] = {
            "away_score": away.get("score"),
            "home_score": home.get("score"),
            "status": g.get("status", {}).get("detailedState"),
            "inning": inning_text,
        }
    return scores


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


_DEPTH_CHART_POSITIONS = {"SP", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH", "CP"}


@st.cache_data(show_spinner=False, ttl=3600 * 6, max_entries=30)
def load_depth_chart(team_id: int) -> dict:
    """Current starter at each defensive position (plus the rotation's #1
    starting pitcher and the closer, as "RP") for one team, from the MLB
    Stats API's depth chart roster — a live lookup, not part of the daily
    ingest, since depth charts shift with trades/call-ups more often than
    once a day. Returns {position_code: {"name", "mlbID", "bats"}}, e.g.
    {"SS": {"name": "...", "mlbID": ..., "bats": "L"|"R"|"S"}}; a position
    is simply absent if the API has no one listed there. "bats" (batting
    side) doubles as the lineup-composition input for predict_game()'s
    platoon-split adjustment."""
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


@st.cache_data(show_spinner=False, ttl=3600 * 24, max_entries=10)
def load_pitcher_handedness(mlbIDs: tuple) -> dict:
    """Throwing hand for each mlbID, via a single batched MLB Stats API call
    (handedness never changes, so this is cached for a full day). Returns
    {mlbID: "L"|"R"}; an id the API doesn't recognize is simply absent."""
    ids = [str(int(i)) for i in mlbIDs if i is not None and not pd.isna(i)]
    if not ids:
        return {}
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/people",
            params={"personIds": ",".join(ids)},
            timeout=10,
        )
        resp.raise_for_status()
        people = resp.json().get("people", [])
    except Exception:
        return {}
    return {p["id"]: p["pitchHand"]["code"] for p in people if p.get("pitchHand", {}).get("code")}


_INJURY_STATUS_CODES = {"D7": "7-Day IL", "D10": "10-Day IL", "D15": "15-Day IL", "D60": "60-Day IL"}


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


_COMPOSITE_FIELD_POSITIONS = ["1B", "2B", "3B", "SS", "LF", "CF", "RF"]
_COMPOSITE_MIN_PA = 150
_COMPOSITE_MIN_IP = 20
_COMPOSITE_MIN_RP_IP = 15


@st.cache_data(show_spinner=False, ttl=3600 * 6, max_entries=5)
def load_league_catchers(_db_mtime: float) -> pd.DataFrame:
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


# Round-number career counting-stat milestones — mirrors
# ingest/refresh_data.py's CAREER_MILESTONES (kept as a separate copy
# rather than a shared import since the ingest script and the app are
# deliberately independent processes with no shared module).
CAREER_MILESTONES = {
    "HR": [300, 400, 500, 600, 700, 800],
    "H": [2000, 2500, 3000, 3500, 4000],
    "RBI": [1000, 1500, 2000],
    "SB": [300, 400, 500, 600],
    "W": [150, 200, 250, 300],
    "SO": [2000, 2500, 3000, 3500, 4000],
    "SV": [200, 300, 400, 500],
}


@st.cache_data(show_spinner=False, ttl=3600 * 6)
def milestone_watch(db_mtime_val: float, max_remaining: int = 10) -> pd.DataFrame:
    """Every active player within `max_remaining` of their next uncrossed
    career counting-stat milestone (500 HR, 3000 K, ...), sourced from true
    career totals (see ingest/refresh_data.py's fetch_career_totals()) —
    not just this app's own 2010+ cached seasons, so a player whose
    career started before then is still tracked correctly. One row per
    (player, stat) — a two-way threat like a 400-SB/300-HR player would
    appear twice. Sorted closest-first."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            df = pd.read_sql("SELECT * FROM career_totals", conn)
        except pd.errors.DatabaseError:
            return pd.DataFrame(columns=["mlbID", "Name", "Tm", "Lev", "Stat", "Total", "Milestone", "Remaining"])

    rows = []
    for row in df.itertuples():
        for stat, thresholds in CAREER_MILESTONES.items():
            total = getattr(row, stat, None)
            if total is None or pd.isna(total):
                continue
            total = int(total)
            upcoming = [m for m in thresholds if m > total]
            if not upcoming:
                continue
            milestone = min(upcoming)
            remaining = milestone - total
            if remaining > max_remaining:
                continue
            rows.append({
                "mlbID": int(row.mlbID), "Name": row.Name, "Tm": row.Tm, "Lev": row.Lev,
                "Stat": stat, "Total": total, "Milestone": milestone, "Remaining": remaining,
            })
    watch = pd.DataFrame(rows)
    if watch.empty:
        return watch
    return watch.sort_values("Remaining").reset_index(drop=True)


@st.cache_data(show_spinner=False, ttl=3600)
def recent_milestone_achievers(db_mtime_val: float, days: int = 5) -> pd.DataFrame:
    """Players who crossed a career milestone within the last `days` days —
    see ingest/refresh_data.py's record_milestone_achievements() for how
    "crossed" is detected and logged (only once per player/stat/threshold,
    dated the first day it was noticed). Powers the Milestone Watch page's
    celebratory callout, which stays up for 5 days after the fact."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        try:
            df = pd.read_sql(
                "SELECT mlbID, Name, Tm, Lev, Stat, Milestone, achieved_date FROM milestone_achievements "
                "WHERE achieved_date >= ?",
                conn, params=(cutoff,),
            )
        except pd.errors.DatabaseError:
            return pd.DataFrame(columns=["mlbID", "Name", "Tm", "Lev", "Stat", "Milestone", "achieved_date"])
    return df.sort_values("achieved_date", ascending=False).reset_index(drop=True)


@st.cache_data(show_spinner=False, max_entries=2)
def load_standings(db_mtime_val: float) -> pd.DataFrame:
    """Current MLB standings from the Stats API (current standings only,
    not historical — replaced in full on every ingest run)."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            return pd.read_sql("SELECT * FROM standings", conn)
        except pd.errors.DatabaseError:
            return pd.DataFrame()


# Home teams win ~54% of MLB games historically — this constant folds that
# edge directly into the Log5 probability.
HOME_FIELD_ADVANTAGE = 0.04
# How much a starter's ERA differs from qualified league-average ERA before
# it can move the prediction, and by how much per full run of ERA. Capped so
# a tiny-sample ERA (e.g. a starter's first outing) can't swing things wildly.
STARTER_ERA_PROB_PER_RUN = 0.03
STARTER_ERA_MAX_SHIFT = 0.10
# Same idea, for each team's bullpen (relievers = GS==0, min 5 IP so a single
# mop-up outing can't swing it). Weighted lower than the starter since one
# pitcher (thrown well over half the game) still matters more than the pen.
BULLPEN_ERA_PROB_PER_RUN = 0.02
BULLPEN_ERA_MAX_SHIFT = 0.05
BULLPEN_MIN_IP = 5
# Team lineup strength, by PA-weighted team wOBA (min 20 PA so a September
# call-up's 3-PA sample doesn't skew it). wOBA sits on a ~.300-.340 scale, so
# a typical best-vs-worst-lineup gap (~.020-.030) yields a modest shift.
LINEUP_WOBA_PROB_PER_POINT = 3.0
LINEUP_WOBA_MAX_SHIFT = 0.05
LINEUP_MIN_PA = 20
# Platoon-split adjustment: rather than scraping per-player vs-LHP/vs-RHP
# splits (hundreds of Baseball-Reference requests a day — not viable), this
# uses each team's likely lineup handedness mix (from the depth chart's 9
# position-player slots) against the opposing starter's throwing hand, and
# the well-documented *league-average* same-handed platoon penalty. A lineup
# that's entirely opposite-handed vs. the opposing starter gets the full
# shift; an entirely same-handed lineup gets the full penalty; a 50/50 mix
# is neutral. Switch hitters always bat opposite the pitcher, so they never
# count as a same-handed matchup.
PLATOON_MAX_SHIFT = 0.03


def log5_win_prob(pct_a: float, pct_b: float) -> float:
    """Bill James' Log5 formula: probability team A beats team B, given each
    team's overall winning percentage. Doesn't account for home field,
    starters, injuries, etc. — see predict_game() for those adjustments."""
    denom = pct_a + pct_b - 2 * pct_a * pct_b
    if denom <= 0:
        return 0.5
    return (pct_a - pct_a * pct_b) / denom


def moneyline_odds(prob: float) -> str:
    """Convert a win probability into American moneyline odds (our own
    calculated estimate — not a real sportsbook line)."""
    prob = min(max(prob, 0.01), 0.99)
    if prob >= 0.5:
        return f"{-round(100 * prob / (1 - prob)):d}"
    return f"+{round(100 * (1 - prob) / prob):d}"


def _clamp(value, max_abs):
    return max(-max_abs, min(max_abs, value))


def team_bullpen_era(pitching: pd.DataFrame, team_abbr: str) -> float | None:
    """IP-weighted ERA of a team's relievers (GS==0). `pitching` must already
    have team-abbreviated Tm (see teams.add_team_abbr)."""
    bullpen = pitching[(pitching["Tm"] == team_abbr) & (pitching["GS"] == 0) & (pitching["IP"] >= BULLPEN_MIN_IP)]
    total_ip = bullpen["IP"].sum()
    if total_ip <= 0:
        return None
    return (bullpen["ERA"] * bullpen["IP"]).sum() / total_ip


def team_lineup_woba(batting: pd.DataFrame, team_abbr: str) -> float | None:
    """PA-weighted wOBA of a team's batters. `batting` must already have
    team-abbreviated Tm (see teams.add_team_abbr)."""
    lineup = batting[(batting["Tm"] == team_abbr) & (batting["PA"] >= LINEUP_MIN_PA)]
    total_pa = lineup["PA"].sum()
    if total_pa <= 0 or lineup["wOBA"].isna().all():
        return None
    weighted = lineup.dropna(subset=["wOBA"])
    total_pa = weighted["PA"].sum()
    if total_pa <= 0:
        return None
    return (weighted["wOBA"] * weighted["PA"]).sum() / total_pa


def _platoon_shift(lineup_starters: dict, opposing_pitcher_hand: str | None) -> float:
    if not lineup_starters or opposing_pitcher_hand not in ("L", "R"):
        return 0.0
    bats = [p.get("bats") for p in lineup_starters.values() if p.get("bats") in ("L", "R", "S")]
    if not bats:
        return 0.0
    share_same_handed = sum(1 for b in bats if b == opposing_pitcher_hand) / len(bats)
    return (0.5 - share_same_handed) * 2 * PLATOON_MAX_SHIFT


def predict_game(
    row: pd.Series,
    pitching: pd.DataFrame,
    batting: pd.DataFrame | None = None,
    pitcher_hands: dict | None = None,
) -> dict | None:
    """Predicts a home/away win probability for one row of todays_games,
    using Log5 (team win%) + home-field advantage, then layering on:
      - starting-pitcher ERA vs. qualified league-average ERA
      - bullpen ERA vs. league-average bullpen ERA (team_bullpen_era)
      - lineup wOBA vs. league-average lineup wOBA (team_lineup_woba)
      - a platoon-split estimate from each lineup's handedness mix vs. the
        opposing starter's throwing hand (see PLATOON_MAX_SHIFT)
    `pitching` must be season pitching stats; pass team-abbreviated
    `pitching`/`batting` (teams.add_team_abbr) to get the bullpen/lineup/
    platoon factors — they're skipped (Log5 + home field + starter only) if
    omitted. `pitcher_hands` is {mlbID: "L"|"R"} (see load_pitcher_handedness).
    This is our own sabermetric estimate, not a real betting line, and still
    has no park factors, injuries, or weather — no external odds provider
    involved."""
    away_g, home_g = row["away_wins"] + row["away_losses"], row["home_wins"] + row["home_losses"]
    if not away_g or not home_g:
        return None
    away_pct = row["away_wins"] / away_g
    home_pct = row["home_wins"] / home_g

    home_prob = log5_win_prob(home_pct, away_pct) + HOME_FIELD_ADVANTAGE

    qualified = pitching[pitching["IP"] >= 20]
    league_era = qualified["ERA"].mean() if not qualified.empty else None
    if league_era is not None:
        for side, mlbID_col, sign in [("home", "home_pitcher_mlbID", 1), ("away", "away_pitcher_mlbID", -1)]:
            mlbID = row.get(mlbID_col)
            if mlbID is None or pd.isna(mlbID):
                continue
            match = pitching[pitching["mlbID"] == int(mlbID)]
            if match.empty:
                continue
            era = match.iloc[0]["ERA"]
            if pd.isna(era):
                continue
            shift = _clamp((league_era - era) * STARTER_ERA_PROB_PER_RUN, STARTER_ERA_MAX_SHIFT)
            home_prob += sign * shift

    home_abbr = teams.normalize_mlb_abbr(row.get("home_abbr", ""))
    away_abbr = teams.normalize_mlb_abbr(row.get("away_abbr", ""))

    if batting is not None and "Tm" in pitching.columns:
        home_bullpen, away_bullpen = team_bullpen_era(pitching, home_abbr), team_bullpen_era(pitching, away_abbr)
        if home_bullpen is not None and away_bullpen is not None:
            home_prob += _clamp((away_bullpen - home_bullpen) * BULLPEN_ERA_PROB_PER_RUN, BULLPEN_ERA_MAX_SHIFT)

    if batting is not None and "Tm" in batting.columns:
        home_woba, away_woba = team_lineup_woba(batting, home_abbr), team_lineup_woba(batting, away_abbr)
        if home_woba is not None and away_woba is not None:
            home_prob += _clamp((home_woba - away_woba) * LINEUP_WOBA_PROB_PER_POINT, LINEUP_WOBA_MAX_SHIFT)

    if pitcher_hands is not None:
        home_team_id, away_team_id = teams.team_id_for_abbr(home_abbr), teams.team_id_for_abbr(away_abbr)
        home_starters = load_depth_chart(home_team_id) if home_team_id else {}
        away_starters = load_depth_chart(away_team_id) if away_team_id else {}
        away_pitcher_hand = pitcher_hands.get(int(row["away_pitcher_mlbID"])) if pd.notna(row.get("away_pitcher_mlbID")) else None
        home_pitcher_hand = pitcher_hands.get(int(row["home_pitcher_mlbID"])) if pd.notna(row.get("home_pitcher_mlbID")) else None
        home_prob += _platoon_shift(home_starters, away_pitcher_hand)
        home_prob -= _platoon_shift(away_starters, home_pitcher_hand)

    home_prob = min(max(home_prob, 0.05), 0.95)
    return {
        "home_prob": home_prob,
        "away_prob": 1 - home_prob,
        "home_odds": moneyline_odds(home_prob),
        "away_odds": moneyline_odds(1 - home_prob),
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
    total_pa = row.iloc[0]["total_pa"] or 0
    total_ip = row.iloc[0]["total_ip"] or 0
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

    grouped = matches.groupby(["mlbID", "Name", "Tm"]).size().reset_index(name="_n")
    grouped["roles"] = grouped["mlbID"].map(lambda m: player_roles_label(m, db_mtime_val))
    return grouped.drop(columns="_n").sort_values("Name").reset_index(drop=True)


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

    matches = matches.sort_values("season")
    grouped = (
        matches.groupby("mlbID")
        .agg(Name=("Name", "last"), Tm=("Tm", "last"), season=("season", "max"))
        .reset_index()
    )
    grouped["roles"] = grouped["mlbID"].map(lambda m: player_roles_label(m, db_mtime_val))
    return grouped.sort_values("Name").reset_index(drop=True)


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
STAT_DISPLAY_LABELS = {"OPS_plus": "OPS+", "ERA_plus": "ERA+", "wRC_plus": "wRC+"}


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


@st.cache_data(show_spinner=False, max_entries=1)
def load_player_bio(_db_mtime: float) -> pd.DataFrame:
    """Birthplace (country/state/city) for every player fetch_player_bio has
    covered so far — powers the World Map page. Empty if the ingest hasn't
    populated player_bio yet (older DB snapshot)."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            df = pd.read_sql("SELECT * FROM player_bio", conn)
        except pd.errors.DatabaseError:
            return pd.DataFrame(columns=["mlbID", "Name", "birth_country", "birth_state", "birth_city"])
    return df


def guesser_pool(season: int, _db_mtime: float) -> pd.DataFrame:
    """Eligible player pool for the Player Guesser mini-game: batters with
    at least 50 AB or pitchers with at least 20 IP that season, so nobody
    gets asked to identify someone from a nearly-blank stat line. Two-way
    players who clear both bars appear once."""
    batting = load_batting(season, _db_mtime)
    pitching = load_pitching(season, _db_mtime)
    eligible_batters = batting.loc[batting["AB"] >= 50, ["mlbID", "Name"]]
    eligible_pitchers = pitching.loc[pitching["IP"] >= 20, ["mlbID", "Name"]]
    pool = pd.concat([eligible_batters, eligible_pitchers], ignore_index=True)
    return pool.drop_duplicates(subset="mlbID").reset_index(drop=True)


@st.cache_data(show_spinner=False, max_entries=1)
def grid_pool(_db_mtime: float) -> dict:
    """Category -> eligible-player data for the Diamond Grid mini-game
    (team affiliation + single-season achievements span every cached
    season, 2010+; career milestones come from career_totals — the MLB
    API's true career totals for this season's active players, same
    source Milestone Watch uses). Returns {"categories": {key: {"label",
    "ids"}}, "names": {mlbID: Name}, "current_team": {mlbID: abbr}}."""
    with sqlite3.connect(DB_PATH) as conn:
        batting = pd.read_sql("SELECT mlbID, Name, Tm, Lev, AB, HR, SB, BA, WAR FROM batting", conn)
        pitching = pd.read_sql("SELECT mlbID, Name, Tm, Lev, IP, W, SO, SV, ERA, WAR FROM pitching", conn)
        try:
            career = pd.read_sql("SELECT * FROM career_totals", conn)
        except pd.errors.DatabaseError:
            career = pd.DataFrame()
        try:
            all_stars = pd.read_sql("SELECT DISTINCT mlbID FROM all_star_rosters", conn)
        except pd.errors.DatabaseError:
            all_stars = pd.DataFrame(columns=["mlbID"])

    batting = teams.add_team_abbr(batting)
    pitching = teams.add_team_abbr(pitching)

    names = {}
    for df in (batting, pitching):
        for row in df.itertuples():
            if pd.notna(row.mlbID):
                names[int(row.mlbID)] = row.Name

    categories = {}

    for abbr, nickname in teams.all_teams():
        ids = set(batting.loc[batting["Tm"] == abbr, "mlbID"]) | set(pitching.loc[pitching["Tm"] == abbr, "mlbID"])
        ids = {int(i) for i in ids if pd.notna(i)}
        if ids:
            categories[f"team:{abbr}"] = {"label": f"Played for the {nickname}", "ids": ids}

    season_stats = [
        ("40+ HR in a season", batting.loc[batting["HR"] >= 40, "mlbID"]),
        ("30+ SB in a season", batting.loc[batting["SB"] >= 30, "mlbID"]),
        (".320+ AVG in a season (200+ AB)", batting.loc[(batting["BA"] >= .320) & (batting["AB"] >= 200), "mlbID"]),
        ("30-30 season (30+ HR & 30+ SB)", batting.loc[(batting["HR"] >= 30) & (batting["SB"] >= 30), "mlbID"]),
        ("6+ WAR season (batter)", batting.loc[batting["WAR"] >= 6, "mlbID"]),
        ("20+ Wins in a season", pitching.loc[pitching["W"] >= 20, "mlbID"]),
        ("200+ Strikeouts in a season", pitching.loc[pitching["SO"] >= 200, "mlbID"]),
        ("40+ Saves in a season", pitching.loc[pitching["SV"] >= 40, "mlbID"]),
        ("Sub-3.00 ERA in a season (100+ IP)", pitching.loc[(pitching["ERA"] < 3.00) & (pitching["IP"] >= 100), "mlbID"]),
        ("6+ WAR season (pitcher)", pitching.loc[pitching["WAR"] >= 6, "mlbID"]),
    ]
    for label, id_series in season_stats:
        ids = {int(i) for i in id_series.dropna().unique()}
        if ids:
            categories[f"season:{label}"] = {"label": label, "ids": ids}

    if not all_stars.empty:
        ids = {int(i) for i in all_stars["mlbID"].dropna().unique()}
        if ids:
            categories["career:allstar"] = {"label": "All-Star selection", "ids": ids}

    current_team = {}
    if not career.empty:
        career = teams.add_team_abbr(career)
        for row in career.itertuples():
            if pd.notna(row.mlbID):
                mlbID = int(row.mlbID)
                names.setdefault(mlbID, row.Name)
                if row.Tm:
                    current_team[mlbID] = row.Tm

        career_bars = {
            "HR": ("400+ Career Home Runs", 400), "H": ("2,500+ Career Hits", 2500),
            "RBI": ("1,200+ Career RBI", 1200), "SB": ("300+ Career Stolen Bases", 300),
            "W": ("150+ Career Wins", 150), "SO": ("2,000+ Career Strikeouts", 2000),
            "SV": ("250+ Career Saves", 250),
        }
        for stat, (label, bar) in career_bars.items():
            if stat not in career.columns:
                continue
            ids = {int(i) for i in career.loc[career[stat] >= bar, "mlbID"].dropna().unique()}
            if ids:
                categories[f"career:{stat}"] = {"label": label, "ids": ids}

    return {"categories": categories, "names": names, "current_team": current_team}


@st.cache_data(show_spinner=False, max_entries=1)
def career_paths_pool(_db_mtime: float) -> dict:
    """mlbID -> {"name", "teams"} for the Career Path mini-game: each
    player's team stints in chronological order (season by season,
    consecutive duplicate teams collapsed), spanning every cached season
    (2010+). Only players who changed teams at least once are included —
    a single-team career would give away the answer on the very first
    reveal."""
    with sqlite3.connect(DB_PATH) as conn:
        batting = pd.read_sql("SELECT mlbID, Name, Tm, Lev, season FROM batting", conn)
        pitching = pd.read_sql("SELECT mlbID, Name, Tm, Lev, season FROM pitching", conn)

    batting = teams.add_team_abbr(batting)
    pitching = teams.add_team_abbr(pitching)
    combined = pd.concat([batting, pitching], ignore_index=True)
    combined = combined.dropna(subset=["mlbID", "Tm"]).sort_values(["mlbID", "season"])
    combined = combined.drop_duplicates(subset=["mlbID", "season"], keep="first")

    paths = {}
    for mlbID, group in combined.groupby("mlbID"):
        stints = []
        for tm in group["Tm"]:
            if not stints or stints[-1] != tm:
                stints.append(tm)
        if len(stints) >= 2:
            paths[int(mlbID)] = {"name": group["Name"].iloc[-1], "teams": stints}
    return paths
