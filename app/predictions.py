"""Backend for the reader prediction game (pick winners, track a
leaderboard). There's no account system anywhere in this app, so a
"reader" is just whatever display name they type in — the leaderboard
tracks names, not identities, and two people can collide if they pick the
same name.

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


def submit_pick(name: str, game_pk: int, date_str: str, pick_abbr: str, away_abbr: str, home_abbr: str) -> tuple[bool, str]:
    """Upserts (name, game_pk) — resubmitting the same game with the same
    name overwrites the earlier pick rather than duplicating it, so
    changing your mind before first pitch is harmless."""
    if not _configured():
        return False, "Not configured yet — see predictions.py's module docstring for the two secrets it needs."

    picks = load_picks()
    picks = [p for p in picks if not (p["name"] == name and p["game_pk"] == game_pk)]
    picks.append({
        "name": name, "game_pk": game_pk, "date": date_str, "pick_abbr": pick_abbr,
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


def compute_leaderboard(picks: list[dict], schedule_loader) -> pd.DataFrame:
    """Scores every pick whose game has finished (1 point per correct
    winner) and tallies by name. `schedule_loader` is db.load_schedule_for_date
    — passed in rather than imported, since db.py already imports
    plenty and this avoids a circular/duplicate MLB-API-fetch dependency
    for a module that's otherwise standalone. Games still in progress or
    not yet played are excluded from both the numerator and denominator
    (they're not "wrong" yet, just unresolved)."""
    if not picks:
        return pd.DataFrame(columns=["Name", "Correct", "Picks", "Pct"])

    by_date = {}
    for p in picks:
        by_date.setdefault(p["date"], []).append(p)

    tally = {}
    for date_str, day_picks in by_date.items():
        schedule = schedule_loader(date_str)
        if schedule.empty:
            continue
        winners = {}
        for _, g in schedule.iterrows():
            if g["status"] not in ("Final", "Game Over", "Completed Early"):
                continue
            if pd.isna(g["away_score"]) or pd.isna(g["home_score"]):
                continue
            winners[g["game_pk"]] = g["home_abbr"] if g["home_score"] > g["away_score"] else g["away_abbr"]
        for p in day_picks:
            winner = winners.get(p["game_pk"])
            if winner is None:
                continue
            row = tally.setdefault(p["name"], {"correct": 0, "total": 0})
            row["total"] += 1
            if winner == p["pick_abbr"]:
                row["correct"] += 1

    if not tally:
        return pd.DataFrame(columns=["Name", "Correct", "Picks", "Pct"])

    rows = [
        {"Name": name, "Correct": v["correct"], "Picks": v["total"],
         "Pct": round(100 * v["correct"] / v["total"], 1) if v["total"] else 0.0}
        for name, v in tally.items()
    ]
    return pd.DataFrame(rows).sort_values(["Correct", "Pct"], ascending=False).reset_index(drop=True)
