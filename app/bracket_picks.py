"""URL-based persistence for the playoff bracket predictor — picks live in
the page's own ?bracket= query param, not a server-side account, so a
bookmarked/shared link reopens with the same picks. This is simpler and
more reliable here than a localStorage/JS bridge (the pattern following.py
uses): every pick mutation already happens inside a Python button-click
handler, so there's no need to round-trip through client-side JS/iframes at
all — st.query_params is a plain server-side read/write."""
import json

import streamlit as st


def bootstrap() -> None:
    """Call once, near the top of the Playoffs page — seeds
    st.session_state["bracket_picks"] (node_id -> picked team_abbr) from a
    ?bracket= query param if present, else empty. No-ops if already
    hydrated this session."""
    if "bracket_picks" in st.session_state:
        return
    raw = st.query_params.get("bracket")
    data = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                data = parsed
        except (ValueError, TypeError):
            pass
    st.session_state["bracket_picks"] = data


def save() -> None:
    """Writes the current st.session_state["bracket_picks"] into the
    ?bracket= query param, so the page's own URL becomes a link back to
    this exact bracket."""
    st.query_params["bracket"] = json.dumps(st.session_state.get("bracket_picks", {}))
