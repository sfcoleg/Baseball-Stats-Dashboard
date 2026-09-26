"""Diamond Assistant — ask a stat question in plain language ("who leads
the league in wRC+, and what's their ISO?") and get an answer generated
over THIS SITE'S OWN MLB data, not the model's training-data memory.

Claude (via the Anthropic tool runner) decides which tool(s) below to
call — leaders, one player's stat line — and every number in its final
answer traces back to a real db.py query against data/stats.db, the same
tables every other MLB page on the site reads. The model never invents a
number; it can only report what a tool actually returned.

Scoped to MLB for this first version, matching db.py's own data. NFL/NBA/
NHL each have their own db module (app/nfl/db.py etc.) — extending this
to them later just means adding a matching set of tools per sport."""
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent))
import db

try:
    import anthropic
    from anthropic import beta_tool
except ImportError:  # the app must still run before `pip install -r requirements.txt`
    anthropic = None

    def beta_tool(fn):  # no-op decorator so the module still imports
        return fn

MODEL = "claude-opus-5"

SYSTEM_PROMPT = (
    "You are the Diamond Assistant, a stat-lookup helper embedded in a baseball "
    "stats site (Diamond Metrics). Answer using ONLY the tools provided — they "
    "query this site's own database directly. Never state a stat value you did "
    "not get from a tool call, and never fall back on your own memory of a "
    "player's career numbers. If a question needs something these tools don't "
    "expose (a different sport, a stat this site doesn't track), say so plainly "
    "instead of guessing. Keep answers concise: a short lead-in sentence plus "
    "the relevant numbers in a compact list or table, not a wall of prose."
)


def _api_key() -> str | None:
    """Prefer Streamlit secrets — how the deployed app should hold it (Settings
    → Secrets on Streamlit Community Cloud) — over an environment variable
    (local dev via .streamlit/secrets.toml or an exported env var). Never
    hardcoded, never logged, never echoed back into a response."""
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_API_KEY")


def available() -> bool:
    return anthropic is not None and bool(_api_key())


def _current_season() -> int:
    seasons = db.get_seasons("batting")
    return seasons[0] if seasons else 0


def _frame_to_text(df: pd.DataFrame) -> str:
    if df.empty:
        return "No qualifying rows."
    return df.round(3).to_string(index=False)


@beta_tool
def batting_leaders(stat: str, season: int | None = None, min_pa: int = 200,
                     top_n: int = 10, also_show: list[str] | None = None,
                     ascending: bool = False) -> str:
    """Top batters by one stat this season, from this site's own database.

    Args:
        stat: Exact column name to sort by — e.g. "wRC_plus", "ISO", "HR",
            "OBP", "SLG", "BA", "OPS", "WAR", "wOBA", "BB_PCT", "K_PCT",
            "hard_hit_pct", "barrel_pct", "avg_exit_velo", "sprint_speed".
            Stats normally written with a symbol use an underscore form:
            wRC+ -> "wRC_plus", OPS+ -> "OPS_plus", K% -> "K_PCT", BB% ->
            "BB_PCT".
        season: Year, e.g. 2026. Defaults to the current/most recent season.
        min_pa: Minimum plate appearances to qualify (default 200, a real
            regular — lower it for part-time players or small samples).
        top_n: How many leaders to return (default 10).
        also_show: Extra stat columns to include alongside the sort stat,
            for cross-referencing — e.g. ["ISO"] when asked to also show
            ISO next to the wRC+ leaders.
        ascending: True when LOWER is better for this stat (rare to want
            for a leaderboard, but available — e.g. a lowest-K% board).
    """
    season = season or _current_season()
    mtime = db.db_mtime()
    frame = db.load_batting(season, mtime)
    if frame.empty:
        return f"No batting data on file for {season}."
    if stat not in frame.columns:
        return f"Unknown stat '{stat}'. Valid batting columns: {', '.join(db.BATTING_COLS)}"
    pool = frame[pd.to_numeric(frame["PA"], errors="coerce") >= min_pa].copy()
    pool[stat] = pd.to_numeric(pool[stat], errors="coerce")
    pool = pool.dropna(subset=[stat]).sort_values(stat, ascending=ascending).head(top_n)
    cols = ["Name", "Tm", "PA", stat] + [c for c in (also_show or []) if c in pool.columns and c != stat]
    return _frame_to_text(pool[cols])


@beta_tool
def pitching_leaders(stat: str, season: int | None = None, min_ip: int = 50,
                      top_n: int = 10, also_show: list[str] | None = None,
                      ascending: bool = False) -> str:
    """Top pitchers by one stat this season, from this site's own database.

    Args:
        stat: Exact column name to sort by — e.g. "ERA", "WHIP", "SO", "W",
            "SV", "FIP", "xFIP", "K_9", "BB_9", "K_BB", "ERA_plus", "WAR",
            "fastball_velo". ERA+ -> "ERA_plus".
        season: Year, e.g. 2026. Defaults to the current/most recent season.
        min_ip: Minimum innings pitched to qualify (default 50).
        top_n: How many leaders to return (default 10).
        also_show: Extra stat columns to include alongside the sort stat.
        ascending: True when LOWER is better — ERA, WHIP, FIP, xFIP, BB_9
            all want ascending=True for a "best" leaderboard.
    """
    season = season or _current_season()
    mtime = db.db_mtime()
    frame = db.load_pitching(season, mtime)
    if frame.empty:
        return f"No pitching data on file for {season}."
    if stat not in frame.columns:
        return f"Unknown stat '{stat}'. Valid pitching columns: {', '.join(db.PITCHING_COLS)}"
    pool = frame[pd.to_numeric(frame["IP"], errors="coerce") >= min_ip].copy()
    pool[stat] = pd.to_numeric(pool[stat], errors="coerce")
    pool = pool.dropna(subset=[stat]).sort_values(stat, ascending=ascending).head(top_n)
    cols = ["Name", "Tm", "IP", stat] + [c for c in (also_show or []) if c in pool.columns and c != stat]
    return _frame_to_text(pool[cols])


@beta_tool
def player_stat_line(name: str, season: int | None = None) -> str:
    """One player's full batting and/or pitching stat line for a season,
    looked up by name (partial match is fine — "ohtani" finds Shohei Ohtani).

    Args:
        name: Player name or partial name to search for.
        season: Year. Defaults to the current/most recent season.
    """
    season = season or _current_season()
    mtime = db.db_mtime()
    matches = db.search_players(name, season, mtime)
    if matches.empty:
        return f"No player matching '{name}' found in {season} — try a different spelling or season."
    if len(matches) > 1:
        names = ", ".join(matches["Name"].tolist())
        return f"Multiple players match '{name}': {names}. Ask which one, or call again with a fuller name."
    mlb_id = matches.iloc[0]["mlbID"]
    sections = []
    batting = db.load_batting(season, mtime)
    brow = batting[batting["mlbID"] == mlb_id]
    if not brow.empty:
        sections.append("Batting:\n" + brow.iloc[0].round(3).to_string())
    pitching = db.load_pitching(season, mtime)
    prow = pitching[pitching["mlbID"] == mlb_id]
    if not prow.empty:
        sections.append("Pitching:\n" + prow.iloc[0].round(3).to_string())
    if not sections:
        return f"{matches.iloc[0]['Name']} has no {season} stats on file."
    return "\n\n".join(sections)


TOOLS = [batting_leaders, pitching_leaders, player_stat_line]


def ask(question: str, history: list[dict]) -> str:
    """One turn of the assistant: `history` is the prior turns as plain
    {"role": "user"|"assistant", "content": <str>} dicts (Streamlit's own
    session_state shape), `question` is the new user message. Runs the
    tool-calling loop to completion and returns the final text answer."""
    if not available():
        return ("The Diamond Assistant needs an Anthropic API key — see the "
                "setup note above this chat.")
    client = anthropic.Anthropic(api_key=_api_key())
    messages = history + [{"role": "user", "content": question}]
    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        output_config={"effort": "medium"},
        tools=TOOLS,
        messages=messages,
    )
    final = None
    for message in runner:
        final = message
    if final is None:
        return "Something went wrong — no response came back."
    if final.stop_reason == "refusal":
        return "I can't help with that request."
    return next((b.text for b in final.content if b.type == "text"), "").strip() or \
        "I looked that up but didn't come back with a clear answer — try rephrasing."
