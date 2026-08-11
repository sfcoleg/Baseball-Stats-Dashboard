"""Client-side (browser localStorage) persistence for the daily prediction
game. Deliberately NOT server-side — this app has no accounts/login, and a
shared store would mean every visitor sees the same picks. Storing them in
each visitor's own browser makes the accuracy tracker genuinely personal
without needing auth, at the cost of not following the visitor across
devices/browsers. Same two-bridge pattern as following.py — see that
module's docstring for why a redirect-based LOAD and an unconditional SAVE
are needed instead of a real two-way JS<->Python channel.
"""
import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

_STORAGE_KEY = "sabermetrics_predictions"


def bootstrap() -> None:
    """Call once, early in main.py (before any page renders). Seeds
    st.session_state["prediction_picks"] — from a ?predictions= query
    param if present (set by the redirect below on a prior run), else []
    with a one-time check for saved localStorage data on a fresh session."""
    if "prediction_picks" in st.session_state:
        st.session_state["_predictions_safe_to_save"] = True
        return

    raw = st.query_params.get("predictions")
    if raw:
        try:
            st.session_state["prediction_picks"] = json.loads(raw)
        except (ValueError, TypeError):
            st.session_state["prediction_picks"] = []
        st.session_state["_predictions_safe_to_save"] = True
        return

    st.session_state["prediction_picks"] = []
    st.session_state["_predictions_safe_to_save"] = False

    components.html(
        f"""
        <script>
        (function() {{
            const saved = localStorage.getItem('{_STORAGE_KEY}');
            if (!saved) return;
            const url = new URL(window.parent.location.href);
            if (url.searchParams.has('predictions')) return;
            url.searchParams.set('predictions', saved);
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
    """Writes the current st.session_state picks into the browser's
    localStorage. No-ops on the very first render of a fresh session (see
    bootstrap()) so it can't clobber real saved data with a placeholder
    empty list while the localStorage-redirect check is still in flight."""
    if not st.session_state.get("_predictions_safe_to_save"):
        return
    payload = json.dumps(st.session_state.get("prediction_picks", []))
    js_literal = json.dumps(payload)  # double-encode: safe JS string literal regardless of quotes/unicode inside
    components.html(f"<script>localStorage.setItem('{_STORAGE_KEY}', {js_literal});</script>", height=0)


def get_picks() -> list[dict]:
    return st.session_state.get("prediction_picks", [])


def add_pick(game_pk: int, date_str: str, pick_abbr: str, away_abbr: str, home_abbr: str) -> None:
    """Upserts by game_pk — resubmitting the same game overwrites the
    earlier pick rather than duplicating it, so changing your mind before
    first pitch is harmless. Doesn't call save() itself; the caller is
    expected to st.rerun() right after, and save() runs again on that
    rerun since Today's Games calls it unconditionally near the top."""
    picks = [p for p in get_picks() if p["game_pk"] != game_pk]
    picks.append({
        "game_pk": game_pk, "date": date_str, "pick_abbr": pick_abbr,
        "away_abbr": away_abbr, "home_abbr": home_abbr,
    })
    st.session_state["prediction_picks"] = picks


def _resolve_winners(date_str: str, schedule_loader) -> dict:
    """{game_pk: winning_abbr} for every FINISHED game on `date_str`."""
    schedule = schedule_loader(date_str)
    if schedule.empty:
        return {}
    winners = {}
    for _, g in schedule.iterrows():
        if g["status"] not in ("Final", "Game Over", "Completed Early"):
            continue
        if pd.isna(g["away_score"]) or pd.isna(g["home_score"]):
            continue
        winners[g["game_pk"]] = g["home_abbr"] if g["home_score"] > g["away_score"] else g["away_abbr"]
    return winners


def compute_accuracy(picks: list[dict], schedule_loader) -> tuple[dict, pd.DataFrame]:
    """Scores every pick whose game has finished (games still in progress
    or not yet played are excluded — not "wrong" yet, just unresolved).
    Returns (overall {correct, total, pct}, per-day breakdown DataFrame
    sorted newest-first) for the "your accuracy through the days" section.
    `schedule_loader` is db.load_schedule_for_date, passed in rather than
    imported to keep this module standalone."""
    empty_overall = {"correct": 0, "total": 0, "pct": None}
    if not picks:
        return empty_overall, pd.DataFrame(columns=["Date", "Correct", "Picks", "Pct"])

    by_date = {}
    for p in picks:
        by_date.setdefault(p["date"], []).append(p)

    day_rows = []
    total_correct, total_picks = 0, 0
    for date_str, day_picks in sorted(by_date.items(), reverse=True):
        winners = _resolve_winners(date_str, schedule_loader)
        correct = sum(1 for p in day_picks if winners.get(p["game_pk"]) == p["pick_abbr"])
        resolved = sum(1 for p in day_picks if p["game_pk"] in winners)
        if resolved == 0:
            continue
        day_rows.append({
            "Date": date_str, "Correct": correct, "Picks": resolved,
            "Pct": round(100 * correct / resolved, 1),
        })
        total_correct += correct
        total_picks += resolved

    overall = {
        "correct": total_correct, "total": total_picks,
        "pct": round(100 * total_correct / total_picks, 1) if total_picks else None,
    }
    return overall, pd.DataFrame(day_rows)
