"""Client-side (browser localStorage) persistence for the Following feature.
Deliberately NOT server-side — this app has no accounts/login, so a shared
SQLite table would mean every visitor sees (and can edit) the same list.
Storing it in each visitor's own browser makes it genuinely personal without
needing auth, at the cost of not following the visitor across devices/browsers.

Streamlit has no built-in two-way JS<->Python data channel without a full
custom component, so this uses two one-way bridges instead:
  - LOAD (JS -> Python): on a fresh session with no ?following= query param
    yet, a components.html script checks localStorage and, if it finds saved
    data, redirects the browser to include it as a query param — one extra
    page load, then bootstrap() reads it into st.session_state and never
    re-reads it for the rest of that session (session_state becomes
    authoritative; re-reading the query param on every rerun would silently
    undo a just-made change with stale data).
  - SAVE (Python -> JS): the Following page calls save() unconditionally on
    every render, writing the current session_state into localStorage. Cheap
    and idempotent, so it doesn't need to be wired to specific mutations.
"""
import json

import streamlit as st
import streamlit.components.v1 as components

_STORAGE_KEY = "sabermetrics_following"


def bootstrap() -> None:
    """Call once, early in main.py (before any page renders). Seeds
    st.session_state["followed_teams"]/["followed_players"] — from a
    ?following= query param if present (set by the redirect below on a
    prior run), else empty lists, with a one-time check for saved
    localStorage data on a truly fresh session."""
    if "followed_teams" in st.session_state:
        # Already hydrated this session — session_state is authoritative, and
        # any localStorage-redirect from the first run would have already
        # happened by now, so it's safe for save() to persist from here on.
        st.session_state["_following_safe_to_save"] = True
        return

    raw = st.query_params.get("following")
    if raw:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = {}
        st.session_state["followed_teams"] = data.get("teams", [])
        st.session_state["followed_players"] = data.get("players", [])
        st.session_state["_following_safe_to_save"] = True
        return

    st.session_state["followed_teams"] = []
    st.session_state["followed_players"] = []
    # Not safe to save yet: this render's lists are just a placeholder in
    # case localStorage turns out to have real data and the redirect below
    # fires. Saving now would clobber that data with an empty list before
    # the browser gets a chance to run the redirect. save() starts working
    # again from the next rerun onward (see the branch above).
    st.session_state["_following_safe_to_save"] = False

    # No query param yet — check localStorage once and redirect if it has
    # saved data. A genuinely new visitor has nothing saved, so this is a
    # no-op for them (no redirect, no flicker).
    components.html(
        f"""
        <script>
        (function() {{
            const saved = localStorage.getItem('{_STORAGE_KEY}');
            if (!saved) return;
            const url = new URL(window.parent.location.href);
            if (url.searchParams.has('following')) return;
            url.searchParams.set('following', saved);
            // components.html() renders in a sandboxed iframe without
            // allow-top-navigation, so window.parent.location.href = ...
            // is silently blocked by the browser. Workaround: build the
            // link IN the parent document (allowed via allow-same-origin)
            // and click it there, so the navigation is parent-initiated
            // rather than a cross-frame navigation from the sandboxed iframe.
            const a = window.parent.document.createElement('a');
            a.href = url.toString();
            window.parent.document.body.appendChild(a);
            a.click();
        }})();
        </script>
        """,
        height=0,
    )


def save() -> None:
    """Writes the current st.session_state follow lists into the browser's
    localStorage. No-ops on the very first render of a fresh session (see
    bootstrap()) so it can't clobber real saved data with a placeholder
    empty list while the localStorage-redirect check is still in flight."""
    if not st.session_state.get("_following_safe_to_save"):
        return
    payload = json.dumps({
        "teams": st.session_state.get("followed_teams", []),
        "players": st.session_state.get("followed_players", []),
    })
    js_literal = json.dumps(payload)  # double-encode: safe JS string literal regardless of quotes/unicode inside
    components.html(f"<script>localStorage.setItem('{_STORAGE_KEY}', {js_literal});</script>", height=0)
