"""Shared helpers for the Mini Games tab's Player Guesser, Diamond Grid, and
Higher or Lower games.

Streak persistence uses the same browser-localStorage pattern as
following.py (see that file's docstring for the full rationale) — there's
no accounts/login in this app, so "the user's streak" can only mean
per-browser, not server-side.
"""
import hashlib
import json
import random
from datetime import date, timedelta

import streamlit as st
import streamlit.components.v1 as components

import db

_STORAGE_KEY = "sabermetrics_guesser_daily"


def normalize_guess(text: str) -> str:
    return db.normalize_text(text).strip()


def is_correct_guess(guess: str, full_name: str) -> bool:
    """Accepts the full name or just the last name (accent/case-insensitive)
    so a reasonable guess isn't marked wrong over formatting."""
    guess_norm = normalize_guess(guess)
    if not guess_norm:
        return False
    if guess_norm == normalize_guess(full_name):
        return True
    last_name = normalize_guess(full_name.split(" ")[-1])
    return len(last_name) > 2 and guess_norm == last_name


def daily_player_id(pool_ids: list[int], day: date) -> int:
    """Deterministic pick so every visitor gets the same daily player.
    Hashing the date (rather than random.seed) avoids any chance of the
    pick shifting if something else in the process calls random() first."""
    digest = hashlib.sha256(day.isoformat().encode()).hexdigest()
    return pool_ids[int(digest, 16) % len(pool_ids)]


def record_daily_result(daily_state: dict, today: str, correct: bool) -> None:
    """Mutates daily_state in place: bumps the streak on a correct guess,
    resets it on a wrong one, and also resets it if the last play wasn't
    yesterday (a skipped day breaks the streak even before today's guess)."""
    last_played = daily_state.get("last_played")
    if last_played and last_played != today:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        if last_played != yesterday:
            daily_state["streak"] = 0
    daily_state["streak"] = daily_state["streak"] + 1 if correct else 0
    daily_state["last_played"] = today
    daily_state["last_result"] = "correct" if correct else "wrong"


def bootstrap_daily() -> None:
    """Call once per render of the Mini Games page, before reading
    st.session_state['guesser_daily']. Seeds it from a ?guesser_daily=
    query param if present (set by the redirect below on a prior run),
    else a fresh zero state, with a one-time check for saved localStorage
    data on a truly fresh session."""
    if "guesser_daily" in st.session_state:
        st.session_state["_guesser_daily_safe_to_save"] = True
        return

    raw = st.query_params.get("guesser_daily")
    if raw:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = {}
        st.session_state["guesser_daily"] = {
            "streak": data.get("streak", 0),
            "last_played": data.get("last_played"),
            "last_result": data.get("last_result"),
        }
        st.session_state["_guesser_daily_safe_to_save"] = True
        return

    st.session_state["guesser_daily"] = {"streak": 0, "last_played": None, "last_result": None}
    st.session_state["_guesser_daily_safe_to_save"] = False

    components.html(
        f"""
        <script>
        (function() {{
            const saved = localStorage.getItem('{_STORAGE_KEY}');
            if (!saved) return;
            const url = new URL(window.parent.location.href);
            if (url.searchParams.has('guesser_daily')) return;
            url.searchParams.set('guesser_daily', saved);
            const a = window.parent.document.createElement('a');
            a.href = url.toString();
            window.parent.document.body.appendChild(a);
            a.click();
        }})();
        </script>
        """,
        height=0,
    )


def save_daily() -> None:
    """Writes st.session_state['guesser_daily'] into the browser's
    localStorage. No-ops on the very first render of a fresh session (see
    bootstrap_daily()) so it can't clobber real saved data with a
    placeholder zero state while the localStorage-redirect check is still
    in flight."""
    if not st.session_state.get("_guesser_daily_safe_to_save"):
        return
    payload = json.dumps(st.session_state.get("guesser_daily", {}))
    js_literal = json.dumps(payload)  # double-encode: safe JS string literal regardless of quotes/unicode inside
    components.html(f"<script>localStorage.setItem('{_STORAGE_KEY}', {js_literal});</script>", height=0)


# ------------------------------------------------------------ Diamond Grid --

def pick_grid_categories(categories: dict, seed_source: str | None, attempts: int = 300):
    """Randomly picks 3 row + 3 column category keys such that every one of
    the 9 row x column intersections has at least one real answer. Passing
    a seed_source (e.g. today's date) makes the pick reproducible — so a
    daily grid is the same for every visitor — while None gives a fresh
    random grid each time (practice mode). Returns (row_keys, col_keys), or
    None in the astronomically unlikely case no valid combo is found."""
    keys = list(categories.keys())
    rng = random.Random(seed_source) if seed_source is not None else random
    for _ in range(attempts):
        chosen = rng.sample(keys, 6)
        row_keys, col_keys = chosen[:3], chosen[3:]
        if all(categories[r]["ids"] & categories[c]["ids"] for r in row_keys for c in col_keys):
            return row_keys, col_keys
    return None


def check_grid_guess(guess: str, categories: dict, names: dict, row_key: str, col_key: str, used_ids: set) -> dict:
    """Checks a typed guess against a grid cell's eligible players (the
    intersection of its row and column category). Requires a normalized
    full-name match — no last-name leniency here, since a grid's answer
    pool is large enough that last names collide often. Returns a dict
    with at least 'correct'; on a correct guess also 'mlbID' and 'name'."""
    eligible = categories[row_key]["ids"] & categories[col_key]["ids"]
    guess_norm = normalize_guess(guess)
    if not guess_norm:
        return {"correct": False, "reason": "empty"}
    match = next((pid for pid in eligible if normalize_guess(names.get(pid, "")) == guess_norm), None)
    if match is None:
        return {"correct": False, "reason": "not_eligible"}
    if match in used_ids:
        return {"correct": False, "reason": "already_used", "mlbID": match, "name": names[match]}
    return {"correct": True, "mlbID": match, "name": names[match]}


# ------------------------------------------------------------ Higher/Lower --

# Batters only (per the game's design) — a mix of counting stats, rate
# stats, and bio (Age), so the same two players can flip who's "ahead"
# depending which stat comes up next round.
HL_STATS = {
    "WAR": {"label": "WAR", "fmt": "{:.1f}"},
    "HR": {"label": "Home Runs", "fmt": "{:.0f}"},
    "RBI": {"label": "RBI", "fmt": "{:.0f}"},
    "SB": {"label": "Stolen Bases", "fmt": "{:.0f}"},
    "Age": {"label": "Age", "fmt": "{:.0f}"},
    "OPS": {"label": "OPS", "fmt": "{:.3f}"},
    "BA": {"label": "Batting Average", "fmt": "{:.3f}"},
    "H": {"label": "Hits", "fmt": "{:.0f}"},
    "R": {"label": "Runs", "fmt": "{:.0f}"},
}


def hl_format(stat_key: str, value) -> str:
    return HL_STATS[stat_key]["fmt"].format(value)


def hl_check(current_value, next_value, guess_higher: bool) -> bool:
    """A tie always counts as correct (whichever way you guessed) — it's a
    less frustrating rule than an arbitrary tie-break, and standard for
    this style of game."""
    if next_value == current_value:
        return True
    return (next_value > current_value) if guess_higher else (next_value < current_value)


# -------------------------------------------------------------- Career Path --

# Points for guessing correctly after N teams have been revealed (1st entry
# = correct on just the earliest team, the hardest possible clue). Reveals
# beyond the table's length (a long-tenured journeyman) all score the
# floor value — still worth something, since exhausting every clue and
# still landing the right name isn't nothing.
CP_POINTS = [100, 70, 50, 30, 15]


def cp_points(reveals_used: int) -> int:
    idx = min(reveals_used, len(CP_POINTS)) - 1
    return CP_POINTS[idx]
