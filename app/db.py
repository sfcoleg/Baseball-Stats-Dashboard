"""Shared helpers for reading the cached stats database."""
import sqlite3
import unicodedata
from datetime import datetime, timedelta
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
    "hard_hit_pct", "barrel_pct", "xwOBA", "xBA", "xSLG", "season",
]
PITCHING_COLS = [
    "Name", "Age", "Lev", "Tm", "G", "GS", "W", "L", "SV", "IP", "ERA", "WHIP",
    "SO", "BB", "HR", "mlbID", "K_9", "BB_9", "K_BB", "FIP", "xERA", "BAbip", "GB_FB",
    "avg_exit_velo_against", "hard_hit_pct_against", "barrel_pct_against", "season",
]
FIELDING_COLS = ["Name", "player_id", "Tm", "Pos", "OAA", "FRP", "success_rate", "season"]
RECENT_BATTING_COLS = ["mlbID", "Name", "Tm", "Lev", "PA", "H", "2B", "3B", "HR", "RBI", "OPS", "period", "season"]
RECENT_PITCHING_COLS = ["mlbID", "Name", "Tm", "Lev", "IP", "ERA", "GSc", "SO", "BB", "HBP", "H", "period", "season"]


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


# Season home-run totals worth calling out when a player's most recent game
# pushed them past one. Deliberately limited to "notable" round numbers
# (not 20/25) so this doesn't fire constantly — the whole point is that it's
# rare enough to be worth a special callout, not just another leaderboard.
HR_MILESTONE_THRESHOLDS = [30, 40, 50, 60, 70]

# Sort priority for display when multiple milestones happen on the same day
# (rarer first).
_MILESTONE_PRIORITY = {"Perfect Game": 0, "No-Hitter": 1, "Cycle": 2, "HR Milestone": 3}


def get_milestones(season: int, db_mtime_val: float) -> list[dict]:
    """Detects notable single-day achievements from yesterday's games:
    hitting for the cycle, throwing a no-hitter or perfect game, and crossing
    a season home-run milestone. Built entirely from data already fetched
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
    - HR milestones are season totals only, not career totals (this app
      only caches the current season's cumulative stats)."""
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
        day_pitching = recent_pitching[recent_pitching["period"] == "day"]
        no_hit_bids = day_pitching[(day_pitching["IP"] >= 9) & (day_pitching["H"] == 0)]
        for _, row in no_hit_bids.iterrows():
            is_perfect = row.get("BB") == 0 and row.get("HBP") == 0
            milestones.append({
                "mlbID": row["mlbID"], "Name": row["Name"], "Tm": row["Tm"], "Lev": row.get("Lev"),
                "category": "Perfect Game" if is_perfect else "No-Hitter",
                "text": "Threw a perfect game" if is_perfect else "Threw a no-hitter",
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
        return pd.DataFrame(columns=["date", "type", "to_abbr", "from_abbr", "description"])

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
        })
    if not rows:
        return pd.DataFrame(columns=["date", "type", "to_abbr", "from_abbr", "description"])
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
    Returns one row per player with a combined list of roles (Batter/Pitcher)."""
    query_norm = normalize_text(query.strip())
    if not query_norm:
        return pd.DataFrame(columns=["mlbID", "Name", "Tm", "roles"])

    index = _player_name_index(season, db_mtime_val)
    matches = index[index["name_norm"].str.contains(query_norm, na=False, regex=False)]
    if matches.empty:
        return pd.DataFrame(columns=["mlbID", "Name", "Tm", "roles"])

    grouped = (
        matches.groupby(["mlbID", "Name", "Tm"])["role"]
        .apply(lambda roles: " / ".join(sorted(set(roles))))
        .reset_index()
        .rename(columns={"role": "roles"})
    )
    return grouped.sort_values("Name").reset_index(drop=True)


SEASON_GAMES = 162


def project_rest_of_season(row: pd.Series, count_cols: list[str], games_played) -> dict | None:
    """Naive rest-of-season projection: holds the player's current per-team-
    game rate constant and extrapolates counting stats out to a 162-game
    season. This is NOT a real projection system (no aging curve, regression
    to the mean, or matchup context like ZiPS/Steamer) — just a simple what-if
    based on the pace they're currently on.

    `games_played` must be TEAM games played so far, not the player's own `G` —
    a pitcher's own G (starts/appearances) is a small fraction of the team's
    schedule (5-man rotation, bullpen usage), so using it directly as the
    denominator wildly overprojects innings/strikeouts. For batters, who play
    in most team games, their own G is a fine stand-in for team games.
    Returns None once/if games_played is already at or past 162."""
    if games_played is None or pd.isna(games_played) or games_played <= 0:
        return None
    games_played = float(games_played)
    remaining_games = SEASON_GAMES - games_played
    if remaining_games <= 0:
        return None
    projected = {}
    for col in count_cols:
        val = row.get(col)
        if val is None or pd.isna(val):
            continue
        per_team_game = val / games_played
        projected[col] = val + per_team_game * remaining_games
    return projected


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


# Percentile -> scouting grade word. Template-generated, not AI — just
# threshold buckets mapped onto percentile_rank() output.
_GRADE_WORDS = [
    (85, "elite"),
    (70, "plus"),
    (55, "above-average"),
    (45, "average"),
    (30, "below-average"),
    (15, "well below-average"),
    (0, "poor"),
]


def _grade_word(pct: float) -> str:
    for threshold, word in _GRADE_WORDS:
        if pct >= threshold:
            return word
    return "poor"


def _top_traits(trait_pcts: list[tuple[str, float]], n: int) -> list[tuple[str, float]]:
    """The `n` traits whose percentile is furthest from average (50) — a
    player's most defining tools this season, not just the first N checked."""
    return sorted(trait_pcts, key=lambda t: abs(t[1] - 50), reverse=True)[:n]


def batter_scouting_report(row: pd.Series, qualified: pd.DataFrame, brief: bool = False) -> str | None:
    """Template-generated scouting blurb from a batter's percentile ranks
    vs. `qualified` (other batters at the same min-PA bar this season).
    `brief=True` returns a short comma-separated tool list (for tight
    spaces like a milestone card); otherwise a couple of full sentences."""
    ops_pct = percentile_rank(qualified["OPS"], row["OPS"])
    if ops_pct is None:
        return None

    traits = []
    power_pct = percentile_rank(qualified["ISO"], row["ISO"])
    if power_pct is not None:
        traits.append(("power", power_pct))
    contact_pct = percentile_rank(qualified["K_PCT"], row["K_PCT"], lower_is_better=True)
    if contact_pct is not None:
        traits.append(("contact", contact_pct))
    eye_pct = percentile_rank(qualified["BB_PCT"], row["BB_PCT"])
    if eye_pct is not None:
        traits.append(("eye", eye_pct))
    if pd.notna(row.get("SB")) and row["SB"] > 0:
        speed_pct = percentile_rank(qualified["SB"], row["SB"])
        if speed_pct is not None:
            traits.append(("speed", speed_pct))

    labels = {
        "power": lambda p: f"{_grade_word(p)} power",
        "contact": lambda p: f"{_grade_word(p)} contact skills",
        "eye": lambda p: f"{_grade_word(p)} plate discipline",
        "speed": lambda p: f"{_grade_word(p)} speed",
    }
    top = _top_traits(traits, 2 if brief else 3)
    phrases = [labels[key](pct) for key, pct in top]

    if brief:
        return ", ".join(p[0].upper() + p[1:] for p in phrases) if phrases else None

    tier = (
        "an elite, middle-of-the-order caliber bat" if ops_pct >= 85 else
        "a strong everyday regular" if ops_pct >= 65 else
        "an average, roster-caliber bat" if ops_pct >= 35 else
        "a bat that has struggled to produce" if ops_pct >= 15 else
        "a bat producing well below replacement level"
    )
    report = f"{row['Name']} profiles as {tier} this season"
    if phrases:
        joined = phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + f" and {phrases[-1]}"
        report += f", carrying {joined}."
    else:
        report += "."
    return report


def pitcher_scouting_report(row: pd.Series, qualified: pd.DataFrame, brief: bool = False) -> str | None:
    """Same idea as batter_scouting_report(), for pitchers. When xERA is
    available and diverges meaningfully from actual ERA, adds a one-line
    regression note (the full-report version only) — xERA is a contact-
    quality-based expected outcome, so a big gap flags likely good/bad luck."""
    era_pct = percentile_rank(qualified["ERA"], row["ERA"], lower_is_better=True)
    if era_pct is None:
        return None

    traits = []
    k_pct = percentile_rank(qualified["K_9"], row["K_9"])
    if k_pct is not None:
        traits.append(("stuff", k_pct))
    bb_pct = percentile_rank(qualified["BB_9"], row["BB_9"], lower_is_better=True)
    if bb_pct is not None:
        traits.append(("control", bb_pct))

    labels = {
        "stuff": lambda p: f"{_grade_word(p)} strikeout stuff",
        "control": lambda p: f"{_grade_word(p)} control",
    }
    top = _top_traits(traits, 2)
    phrases = [labels[key](pct) for key, pct in top]

    if brief:
        return ", ".join(p[0].upper() + p[1:] for p in phrases) if phrases else None

    tier = (
        "an elite, front-of-the-rotation caliber arm" if era_pct >= 85 else
        "a solid, reliable arm" if era_pct >= 65 else
        "an average, roster-caliber arm" if era_pct >= 35 else
        "an arm that has struggled to prevent runs" if era_pct >= 15 else
        "an arm producing well below replacement level"
    )
    report = f"{row['Name']} profiles as {tier} this season"
    if phrases:
        joined = phrases[0] if len(phrases) == 1 else f"{phrases[0]} and {phrases[1]}"
        report += f", showing {joined}."
    else:
        report += "."

    if "xERA" in row.index and pd.notna(row.get("xERA")):
        gap = row["ERA"] - row["xERA"]
        if gap >= 0.75:
            report += (
                f" His {row['xERA']:.2f} xERA is well below his {row['ERA']:.2f} ERA — the underlying "
                f"contact quality suggests better results may be coming."
            )
        elif gap <= -0.75:
            report += (
                f" His {row['xERA']:.2f} xERA is well above his {row['ERA']:.2f} ERA — some regression "
                f"may be coming."
            )
    return report


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


def last_updated() -> str | None:
    import datetime

    if not DB_PATH.exists():
        return None
    return datetime.datetime.fromtimestamp(db_mtime()).strftime("%Y-%m-%d %H:%M")
