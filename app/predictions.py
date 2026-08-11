"""Backend for the daily prediction game — pick winners each day, track
your own accuracy over time. Single-user (no accounts, no leaderboard):
whoever's using the site is "the user," so picks are just keyed by
game_pk/date, nothing else.

Persistence is the real wrinkle: Streamlit Community Cloud's filesystem
is ephemeral, wiped on every redeploy, and this app redeploys
automatically whenever the daily stats-refresh workflow pushes to GitHub
— i.e. daily. A normal sqlite write here would get wiped within a day.
Instead picks live in a private GitHub Gist, read/written via the GitHub
API — a Gist isn't part of this repo, so writing to it doesn't trigger a
redeploy and isn't wiped by one either.

Requires two Streamlit secrets, DIFFERENT from articles.py's
github_token/github_repo (gists need a classic PAT with the "gist"
scope — fine-grained repo-scoped PATs don't grant Gist access):
  predictions_gist_token — a classic personal access token
    (github.com/settings/tokens/new) with the "gist" scope checked
  predictions_gist_id — the id of a private gist you create yourself
    (gist.github.com/new -> filename "predictions.json", content "{}",
    Create secret gist) — the id is the last path segment of its URL.
Set both in the app's Settings -> Secrets on share.streamlit.io (and,
for local testing, in .streamlit/secrets.toml — gitignored).
"""
import json
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

GIST_FILENAME = "predictions.json"


def _secret(key):
    """st.secrets.get() raises StreamlitSecretNotFoundError rather than
    returning None when no secrets.toml exists at all (as opposed to one
    that exists but lacks this key) — a real gap when this whole feature
    is meant to degrade gracefully, not crash, on a fresh checkout with no
    secrets configured yet."""
    try:
        return st.secrets.get(key)
    except Exception:
        return None


def _configured() -> bool:
    return bool(_secret("predictions_gist_token")) and bool(_secret("predictions_gist_id"))


def _headers():
    return {
        "Authorization": f"token {_secret('predictions_gist_token')}",
        "Accept": "application/vnd.github+json",
    }


@st.cache_data(show_spinner=False, ttl=30, max_entries=1)
def load_picks() -> list[dict]:
    """Every pick ever submitted, oldest first. Returns [] if not
    configured or the gist is empty/unreachable — callers treat that the
    same as "no picks yet" rather than erroring."""
    if not _configured():
        return []
    try:
        resp = requests.get(
            f"https://api.github.com/gists/{_secret('predictions_gist_id')}",
            headers=_headers(), timeout=15,
        )
        resp.raise_for_status()
        content = resp.json()["files"].get(GIST_FILENAME, {}).get("content", "{}")
        return json.loads(content).get("picks", [])
    except Exception:
        return []


def submit_pick(game_pk: int, date_str: str, pick_abbr: str, away_abbr: str, home_abbr: str) -> tuple[bool, str]:
    """Upserts by game_pk — resubmitting the same game overwrites the
    earlier pick rather than duplicating it, so changing your mind before
    first pitch is harmless."""
    if not _configured():
        return False, "Not configured yet — see predictions.py's module docstring for the two secrets it needs."

    picks = load_picks()
    picks = [p for p in picks if p["game_pk"] != game_pk]
    picks.append({
        "game_pk": game_pk, "date": date_str, "pick_abbr": pick_abbr,
        "away_abbr": away_abbr, "home_abbr": home_abbr,
        "made_at": datetime.now(timezone.utc).isoformat(),
    })

    try:
        resp = requests.patch(
            f"https://api.github.com/gists/{_secret('predictions_gist_id')}",
            headers=_headers(),
            json={"files": {GIST_FILENAME: {"content": json.dumps({"picks": picks}, indent=2)}}},
            timeout=15,
        )
    except requests.RequestException as e:
        return False, f"Couldn't reach GitHub ({e})."

    if resp.status_code == 200:
        load_picks.clear()
        return True, "Pick saved!"
    return False, f"GitHub API error ({resp.status_code}): {resp.text[:300]}"


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
