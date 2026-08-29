"""NFL data layer — readers over data/nfl.db (built by ingest/nfl_refresh.py).

Mirrors app/nhl/db.py in shape: cache on the database's mtime so a refresh
invalidates everything at once, and return plain DataFrames the pages can
style with the shared helpers in app/style.py."""
import sqlite3
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

NFL_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "nfl.db"

GAME_TYPE_LABELS = {
    "REG": "Regular season", "WC": "Wild Card", "DIV": "Divisional",
    "CON": "Conference Championship", "SB": "Super Bowl",
}


def nfl_db_mtime() -> float:
    return NFL_DB_PATH.stat().st_mtime if NFL_DB_PATH.exists() else 0.0


def today_pacific() -> date:
    """Same single source of truth for "what day is it" as the other sports —
    see db.today_pacific for why Pacific rather than the server's UTC."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).date()


def season_label(season: int) -> str:
    """An NFL season spans two calendar years and is named for the first."""
    return f"{season}-{str(season + 1)[-2:]}"


def _read(query: str, params: tuple = ()) -> pd.DataFrame:
    if not NFL_DB_PATH.exists():
        return pd.DataFrame()
    try:
        with sqlite3.connect(NFL_DB_PATH) as conn:
            return pd.read_sql(query, conn, params=params)
    except (sqlite3.Error, pd.errors.DatabaseError):
        return pd.DataFrame()


@st.cache_data(show_spinner=False, max_entries=2)
def seasons(db_mtime_val: float) -> list[int]:
    """Newest first, so a season picker defaults to the current one."""
    df = _read("SELECT DISTINCT season FROM games ORDER BY season DESC")
    return df["season"].astype(int).tolist() if not df.empty else []


@st.cache_data(show_spinner=False, max_entries=2)
def default_season(db_mtime_val: float) -> int | None:
    """The season a picker should open on: the newest one with a played game.

    The NFL schedule is published in May, so from spring until September the
    newest season exists but is entirely unplayed — opening there shows an
    empty page on every tab. This falls forward to the last season with
    results, and switches to the new one as soon as it kicks off."""
    played = _read(
        "SELECT MAX(season) FROM games WHERE home_score IS NOT NULL"
    )
    if not played.empty and pd.notna(played.iloc[0, 0]):
        return int(played.iloc[0, 0])
    latest = _read("SELECT MAX(season) FROM games")
    if not latest.empty and pd.notna(latest.iloc[0, 0]):
        return int(latest.iloc[0, 0])
    return None


def season_index(season_list: list[int], db_mtime_val: float) -> int:
    """Index of default_season within `season_list`, for selectbox(index=)."""
    target = default_season(db_mtime_val)
    return season_list.index(target) if target in season_list else 0


@st.cache_data(show_spinner=False, max_entries=8)
def load_standings(season: int, db_mtime_val: float) -> pd.DataFrame:
    """Regular-season records for one season, already ordered the way a
    standings table reads: best first."""
    df = _read("SELECT * FROM standings WHERE season = ?", (int(season),))
    if df.empty:
        return df
    return df.sort_values(["win_pct", "point_diff"], ascending=False).reset_index(drop=True)


@st.cache_data(show_spinner=False, max_entries=8)
def load_games(season: int, db_mtime_val: float) -> pd.DataFrame:
    df = _read("SELECT * FROM games WHERE season = ? ORDER BY week, gameday, gametime", (int(season),))
    if df.empty:
        return df
    df["played"] = df["home_score"].notna() & df["away_score"].notna()
    return df


@st.cache_data(show_spinner=False, max_entries=8)
def load_team_weeks(season: int, db_mtime_val: float) -> pd.DataFrame:
    """Per-team, per-week totals including EPA — empty for a season whose
    stats file nflverse has not published yet (the upcoming one, all
    summer)."""
    return _read("SELECT * FROM team_week_stats WHERE season = ?", (int(season),))


def current_week(games: pd.DataFrame) -> int | None:
    """The week the season is actually on: the earliest week with an unplayed
    game, or the last week once everything has been played. Derived from
    results rather than from the calendar, so a postponed game keeps the site
    on the right week."""
    if games.empty:
        return None
    pending = games[~games["played"]]
    if not pending.empty:
        return int(pending["week"].min())
    return int(games["week"].max())


def team_schedule(games: pd.DataFrame, abbr: str) -> pd.DataFrame:
    """One team's season, with the view flipped to that team: who they played,
    whether it was home, and the result from their side."""
    own = games[(games["home_team"] == abbr) | (games["away_team"] == abbr)].copy()
    if own.empty:
        return own
    at_home = own["home_team"] == abbr
    own["is_home"] = at_home
    own["opponent"] = own["away_team"].where(at_home, own["home_team"])
    own["points_for"] = own["home_score"].where(at_home, own["away_score"])
    own["points_against"] = own["away_score"].where(at_home, own["home_score"])
    own["result"] = pd.NA
    decided = own["played"]
    own.loc[decided & (own["points_for"] > own["points_against"]), "result"] = "W"
    own.loc[decided & (own["points_for"] < own["points_against"]), "result"] = "L"
    own.loc[decided & (own["points_for"] == own["points_against"]), "result"] = "T"
    return own


def record_string(row) -> str:
    """"12-5" or "12-4-1" — ties are only shown when there are any, which is
    how the NFL writes it."""
    ties = int(row.get("ties") or 0)
    base = f"{int(row['wins'])}-{int(row['losses'])}"
    return f"{base}-{ties}" if ties else base


# --- Players ----------------------------------------------------------------
# Qualifying thresholds for leaderboards, per season. Without them a leader
# board sorted by a RATE is just whoever attempted the fewest plays.
MIN_ATTEMPTS = 100      # passing
MIN_CARRIES = 50        # rushing
MIN_TARGETS = 30        # receiving


# Columns that must be numeric to render. SQLite has no fixed column types,
# so anything written as text once stays text — and formatting a string as a
# float raises. Coercing on read means a bad write degrades to blanks rather
# than to a stack trace on the page.
_NUMERIC_PLAYER_COLS = (
    "passing_epa_per_att", "rushing_epa_per_carry", "receiving_epa_per_target",
    "completion_pct", "yards_per_attempt", "yards_per_carry",
    "yards_per_reception", "passing_cpoe", "target_share",
)


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    for column in _NUMERIC_PLAYER_COLS:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


@st.cache_data(show_spinner=False, max_entries=8)
def load_player_seasons(season: int, db_mtime_val: float, season_type: str = "REG") -> pd.DataFrame:
    """Season totals for every player in one season.

    season_type is separate on purpose — a leaderboard means the regular
    season, and folding playoff games in would flatter whoever went deepest."""
    return _coerce_numeric(_read(
        "SELECT * FROM player_season_stats WHERE season = ? AND season_type = ?",
        (int(season), season_type),
    ))


@st.cache_data(show_spinner=False, max_entries=8)
def load_player_career(player_id: str, db_mtime_val: float) -> pd.DataFrame:
    """Every season we hold for one player, newest first."""
    return _coerce_numeric(_read(
        "SELECT * FROM player_season_stats WHERE player_id = ? ORDER BY season DESC",
        (str(player_id),),
    ))


@st.cache_data(show_spinner=False, max_entries=8)
def load_player_weeks(player_id: str, season: int, db_mtime_val: float) -> pd.DataFrame:
    """One player's game log for a season — only the recent seasons kept by
    the ingest have weekly rows (see WEEKLY_SEASONS there)."""
    return _coerce_numeric(_read(
        "SELECT * FROM player_week_stats WHERE player_id = ? AND season = ? ORDER BY week",
        (str(player_id), int(season)),
    ))


@st.cache_data(show_spinner=False, max_entries=4)
def search_players(query: str, db_mtime_val: float) -> pd.DataFrame:
    """Name search across every season, newest first.

    Returns one row per player rather than one per season — the same player
    appearing eleven times would push everyone else off a short results
    list."""
    if not query.strip():
        return pd.DataFrame()
    df = _read(
        "SELECT player_id, player_display_name, position, team, MAX(season) AS season "
        "FROM player_season_stats WHERE player_display_name LIKE ? COLLATE NOCASE "
        "GROUP BY player_id ORDER BY season DESC, player_display_name",
        (f"%{query.strip()}%",),
    )
    return df


def qualified(players: pd.DataFrame, kind: str) -> pd.DataFrame:
    """The pool for a rate leaderboard: enough volume to mean something."""
    if players.empty:
        return players
    column, minimum = {
        "passing": ("attempts", MIN_ATTEMPTS),
        "rushing": ("carries", MIN_CARRIES),
        "receiving": ("targets", MIN_TARGETS),
    }[kind]
    if column not in players.columns:
        return players
    return players[pd.to_numeric(players[column], errors="coerce").fillna(0) >= minimum]


@st.cache_data(show_spinner=False, max_entries=2)
def last_completed_game(db_mtime_val: float) -> dict | None:
    """The most recently finished game, across every season we hold.

    Not scoped to the selected season on purpose: this answers "what was the
    last football played", which during the long offseason is last
    February's Super Bowl rather than anything in the season a picker
    happens to be showing."""
    df = _read(
        "SELECT * FROM games WHERE home_score IS NOT NULL "
        "ORDER BY gameday DESC, game_id DESC LIMIT 1"
    )
    return None if df.empty else df.iloc[0].to_dict()


def super_bowl_numeral(season: int) -> str:
    """Super Bowl number in Roman numerals for a season year.

    The first Super Bowl followed the 1966 season, so the numeral is
    season - 1965. Worth spelling out because the league brands them this
    way and "Super Bowl 60" reads as a typo."""
    number = int(season) - 1965
    if number < 1:
        return ""
    numerals = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
                (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
                (5, "V"), (4, "IV"), (1, "I"))
    out = ""
    for value, letter in numerals:
        while number >= value:
            out += letter
            number -= value
    return out


def game_round_label(game: dict) -> str:
    """How to name the game: "Super Bowl LX", "Divisional", "Week 8"."""
    kind = game.get("game_type") or "REG"
    if kind == "SB":
        numeral = super_bowl_numeral(game.get("season") or 0)
        return f"Super Bowl {numeral}".strip()
    if kind in GAME_TYPE_LABELS and kind != "REG":
        return GAME_TYPE_LABELS[kind]
    return f"Week {int(game['week'])}" if game.get("week") else "Regular season"


# --- Advanced stats ---------------------------------------------------------
# Next Gen Stats begins in 2016; Pro-Football-Reference's advanced tables begin
# in 2018. Pages state the earlier limit rather than showing an empty board for
# a season the data simply doesn't cover.
NGS_FIRST_SEASON = 2016
PFR_FIRST_SEASON = 2018

MIN_DEF_TARGETS = 40    # coverage boards
MIN_PASS_RUSH_SNAPS = 8  # measured in pressures, not snaps — see defense page


@st.cache_data(show_spinner=False, max_entries=8)
def load_nextgen(season: int, kind: str, db_mtime_val: float) -> pd.DataFrame:
    """Next Gen Stats season totals for one season and stat type.

    Only week=0 rows were stored, which ARE the season totals — NGS averages
    like separation and time to throw cannot be re-derived by summing weeks,
    so taking the league's own season figure is both correct and simpler."""
    return _read(
        "SELECT * FROM nextgen_stats WHERE season = ? AND ngs_type = ?",
        (int(season), kind),
    )


@st.cache_data(show_spinner=False, max_entries=8)
def load_pfr_advanced(season: int, kind: str, db_mtime_val: float) -> pd.DataFrame:
    """Pro-Football-Reference advanced season stats for one stat type.

    kind="def" is the only per-player defensive data on the site: coverage
    (targets, completions and passer rating allowed) and pass rush (hurries,
    knockdowns, sacks)."""
    return _read(
        "SELECT * FROM pfr_advanced WHERE season = ? AND pfr_type = ?",
        (int(season), kind),
    )


def advanced_available(season: int, source: str) -> bool:
    """Whether a season predates the source, so a page can say so instead of
    rendering an empty table."""
    first = NGS_FIRST_SEASON if source == "ngs" else PFR_FIRST_SEASON
    return int(season) >= first


@st.cache_data(show_spinner=False, max_entries=16)
def player_nextgen(player_id: str, kind: str, db_mtime_val: float) -> pd.DataFrame:
    """One player's Next Gen Stats season lines, newest first."""
    return _read(
        "SELECT * FROM nextgen_stats WHERE player_id = ? AND ngs_type = ? "
        "ORDER BY season DESC",
        (str(player_id), kind),
    )


@st.cache_data(show_spinner=False, max_entries=16)
def player_pfr(player_id: str, kind: str, db_mtime_val: float) -> pd.DataFrame:
    """One player's PFR advanced season lines, newest first."""
    return _read(
        "SELECT * FROM pfr_advanced WHERE player_id = ? AND pfr_type = ? "
        "ORDER BY season DESC",
        (str(player_id), kind),
    )


# Which advanced sections belong on a profile, by the position PFR records.
# A cornerback's page should open on who threw at him, not on an empty
# passing table — so the position drives the sections rather than the other
# way round.
DEFENSIVE_POSITIONS = {
    "CB", "S", "FS", "SS", "DB", "LB", "OLB", "ILB", "MLB",
    "DE", "DT", "DL", "NT", "EDGE",
}


def is_defensive(position: str | None) -> bool:
    return str(position or "").upper() in DEFENSIVE_POSITIONS


@st.cache_data(show_spinner=False, max_entries=8)
def player_position(player_id: str, db_mtime_val: float) -> str:
    """The player's position, preferring what PFR recorded most recently.

    player_season_stats carries a position too, but it comes from the
    offensive stats feed and is blank or wrong for defenders — the very
    players whose sections depend on getting this right."""
    pfr = _read(
        "SELECT pos FROM pfr_advanced WHERE player_id = ? AND pos IS NOT NULL "
        "ORDER BY season DESC LIMIT 1",
        (str(player_id),),
    )
    if not pfr.empty:
        return str(pfr.iloc[0]["pos"])
    seasons_df = _read(
        "SELECT position FROM player_season_stats WHERE player_id = ? "
        "AND position IS NOT NULL ORDER BY season DESC LIMIT 1",
        (str(player_id),),
    )
    return str(seasons_df.iloc[0]["position"]) if not seasons_df.empty else ""


# --- Offensive line (unit level only) ---------------------------------------
# There is no per-lineman performance data here, and there is no honest way to
# invent one: individual blocking grades are PFF's product and are not public.
# What IS measurable is the unit's output — how often the quarterback was
# pressured behind it, and how far backs ran before anyone touched them. Both
# are attributed to the line as a group, which is what they actually are.
def _pfr_team_column(df: pd.DataFrame) -> str | None:
    """PFR's passing tables name the team column `team`; its rushing,
    receiving and defensive tables name it `tm`. The ingest concatenates all
    four, so both spellings exist and only one is populated per row type."""
    for candidate in ("team", "tm"):
        if candidate in df.columns and df[candidate].notna().any():
            return candidate
    return None


@st.cache_data(show_spinner=False, max_entries=8)
def team_pass_protection(season: int, db_mtime_val: float) -> pd.DataFrame:
    """Pressure allowed per team, from the quarterback rows.

    Pressure rate rather than sacks allowed: a sack is the rare end of a
    broken protection, while pressures happen several times a game and
    describe the same thing with far less noise."""
    passing = load_pfr_advanced(season, "pass", db_mtime_val)
    if passing.empty:
        return pd.DataFrame()
    team_col = _pfr_team_column(passing)
    if team_col is None:
        return pd.DataFrame()
    numeric = ["pass_attempts", "times_pressured", "times_hit", "times_hurried",
               "times_blitzed", "pocket_time"]
    for col in numeric:
        if col in passing.columns:
            passing[col] = pd.to_numeric(passing[col], errors="coerce")
    grouped = passing.groupby(team_col, as_index=False).agg(
        attempts=("pass_attempts", "sum"),
        pressured=("times_pressured", "sum"),
        hits=("times_hit", "sum"),
        hurries=("times_hurried", "sum"),
        blitzed=("times_blitzed", "sum"),
    ).rename(columns={team_col: "team"})
    grouped = grouped[grouped["attempts"] > 0]
    grouped["pressure_rate"] = 100 * grouped["pressured"] / grouped["attempts"]
    grouped["blitz_rate"] = 100 * grouped["blitzed"] / grouped["attempts"]
    return grouped.sort_values("pressure_rate").reset_index(drop=True)


@st.cache_data(show_spinner=False, max_entries=8)
def team_run_blocking(season: int, db_mtime_val: float) -> pd.DataFrame:
    """Yards before contact per carry, per team.

    The cleanest public proxy for run blocking there is: yards gained before
    any defender touched the back are the ones the line gave him, and yards
    after contact are the ones he took himself."""
    rushing = load_pfr_advanced(season, "rush", db_mtime_val)
    if rushing.empty:
        return pd.DataFrame()
    team_col = _pfr_team_column(rushing)
    if team_col is None:
        return pd.DataFrame()
    for col in ("att", "yds", "ybc", "yac", "brk_tkl"):
        if col in rushing.columns:
            rushing[col] = pd.to_numeric(rushing[col], errors="coerce")
    grouped = rushing.groupby(team_col, as_index=False).agg(
        carries=("att", "sum"), yards=("yds", "sum"),
        before_contact=("ybc", "sum"), after_contact=("yac", "sum"),
        broken_tackles=("brk_tkl", "sum"),
    ).rename(columns={team_col: "team"})
    grouped = grouped[grouped["carries"] > 0]
    grouped["ybc_per_carry"] = grouped["before_contact"] / grouped["carries"]
    grouped["yac_per_carry"] = grouped["after_contact"] / grouped["carries"]
    grouped["yards_per_carry"] = grouped["yards"] / grouped["carries"]
    return grouped.sort_values("ybc_per_carry", ascending=False).reset_index(drop=True)


# --- dEPA: an in-house quarterback metric -----------------------------------
# The same idea as this site's pitcher dWAR, and held to the same bar: it only
# earns a place if it out-predicts the conventional stat on next-season data.
#
# What was tested, over paired quarterback seasons of 200+ attempts:
#
#   passer rating .................. r=+0.3463
#   EPA per attempt, this season ... r=+0.3813
#   dEPA (below) ................... r=+0.4136
#
# So it beats passer rating by +0.067 and raw EPA by +0.032 — the same order
# of improvement pitcher dWAR showed over FIP (+0.050).
#
# What did NOT work, recorded because the negative results are the useful
# part: blending CPOE in was worth +0.0002 over EPA alone (nothing — CPOE
# already lives inside EPA), and weighting sack avoidance actively HURT,
# taking r down to +0.3846. The signal that mattered was none of the fancy
# inputs. It was simply using the PRIOR season too: one year of quarterback
# play is a small sample, and last year still knows something about this
# player that this year's number alone does not.
DEPA_THIS_SEASON_WEIGHT = 0.7
DEPA_MIN_ATTEMPTS = 200


@st.cache_data(show_spinner=False, max_entries=8)
def quarterback_depa(season: int, db_mtime_val: float) -> pd.DataFrame:
    """dEPA for every qualifying quarterback in `season`.

    Blends this season's EPA per attempt with the previous season's, each
    weighted by its own attempts so a 600-attempt year counts for more than
    a 220-attempt one. A quarterback with no prior season on file simply
    gets this season's rate, which is the honest answer rather than a
    regression toward a mean he has no history in."""
    frame = _read(
        "SELECT player_id, player_display_name, team, season, attempts, passing_epa, "
        "passing_cpoe, passing_yards, passing_tds, passing_interceptions "
        "FROM player_season_stats WHERE season_type = 'REG' AND season IN (?, ?)",
        (int(season), int(season) - 1),
    )
    if frame.empty:
        return pd.DataFrame()
    frame["attempts"] = pd.to_numeric(frame["attempts"], errors="coerce")
    frame["passing_epa"] = pd.to_numeric(frame["passing_epa"], errors="coerce")
    frame = frame[frame["attempts"] > 0]
    frame["epa_att"] = frame["passing_epa"] / frame["attempts"]

    current = frame[frame["season"] == int(season)]
    current = current[current["attempts"] >= DEPA_MIN_ATTEMPTS].copy()
    if current.empty:
        return current
    prior = frame[frame["season"] == int(season) - 1][["player_id", "attempts", "epa_att"]]
    prior = prior.rename(columns={"attempts": "prev_attempts", "epa_att": "prev_epa_att"})
    merged = current.merge(prior, on="player_id", how="left")

    w = DEPA_THIS_SEASON_WEIGHT
    has_prior = merged["prev_epa_att"].notna()
    numerator = w * merged["attempts"] * merged["epa_att"]
    denominator = w * merged["attempts"]
    numerator = numerator.where(~has_prior,
                                numerator + (1 - w) * merged["prev_attempts"] * merged["prev_epa_att"])
    denominator = denominator.where(~has_prior,
                                    denominator + (1 - w) * merged["prev_attempts"])
    merged["dEPA"] = numerator / denominator
    merged["has_prior_season"] = has_prior
    return merged.sort_values("dEPA", ascending=False).reset_index(drop=True)
