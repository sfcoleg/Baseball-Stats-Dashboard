"""Shared helpers for the Mini Games tab's Player Guesser game.

Streak persistence uses the same browser-localStorage pattern as
following.py (see that file's docstring for the full rationale) — there's
no accounts/login in this app, so "the user's streak" can only mean
per-browser, not server-side.
"""
import hashlib
import json
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
