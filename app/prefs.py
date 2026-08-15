"""Client-side (browser localStorage) persistence for site-wide preferences
(default season, favorite team) set on the Settings page. Same two-bridge
pattern as following.py/predictions.py — see that module's docstring for
why the LOAD redirect has to be fired from a routed page's own script
(here: Home.py and the Settings page itself, since prefs affect nearly
every page and Home is where most sessions start) rather than from main.py,
and why save() no-ops on a session's very first render.
"""
import json

import streamlit as st
import streamlit.components.v1 as components

STORAGE_KEY = "sabermetrics_prefs"


def bootstrap() -> None:
    """Call once, early in main.py (before any page renders). Seeds
    st.session_state["pref_default_season"]/["pref_favorite_team"] — from
    a ?prefs= query param if present (set by the redirect below on a prior
    run), else None/None."""
    if "pref_default_season" in st.session_state:
        st.session_state["_prefs_safe_to_save"] = True
        return

    raw = st.query_params.get("prefs")
    if raw:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = {}
        st.session_state["pref_default_season"] = data.get("default_season")
        st.session_state["pref_favorite_team"] = data.get("favorite_team")
        st.session_state["_prefs_safe_to_save"] = True
        return

    st.session_state["pref_default_season"] = None
    st.session_state["pref_favorite_team"] = None
    # Not safe to save yet — see following.py's identical placeholder-guard
    # for why (the shared redirect may still be in flight).
    st.session_state["_prefs_safe_to_save"] = False


def save() -> None:
    """Writes the current st.session_state prefs into the browser's
    localStorage. No-ops on the very first render of a fresh session (see
    bootstrap())."""
    if not st.session_state.get("_prefs_safe_to_save"):
        return
    payload = json.dumps({
        "default_season": st.session_state.get("pref_default_season"),
        "favorite_team": st.session_state.get("pref_favorite_team"),
    })
    js_literal = json.dumps(payload)  # double-encode: safe JS string literal regardless of quotes/unicode inside
    components.html(f"<script>localStorage.setItem('{STORAGE_KEY}', {js_literal});</script>", height=0)


def default_season_index(seasons: list[int]) -> int:
    """Index into `seasons` to preselect on a `st.selectbox("Season", seasons)`
    — the saved default season if it's a valid option this page offers,
    else 0 (the most recent season, every page's own prior hardcoded
    default)."""
    pref = st.session_state.get("pref_default_season")
    if pref in seasons:
        return seasons.index(pref)
    return 0


def get_favorite_team() -> str | None:
    return st.session_state.get("pref_favorite_team")
