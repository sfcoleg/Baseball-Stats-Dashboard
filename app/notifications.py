"""Computes the small "recent activity for players you follow" list shown
in the header bell — reuses the same yesterday's-performances/milestones
data as the Following page and Daily Digest, just filtered down to
followed players and capped to a handful of items. Not a real unread/seen
tracker (no per-notification read state) — it's a fresh "what happened
recently" snapshot recomputed on every load, same spirit as the rest of
this app's daily-cached data.
"""
import streamlit as st

import db


def get_notifications(mtime: float, max_items: int = 6) -> list[dict]:
    followed_players = st.session_state.get("followed_players", [])
    if not followed_players:
        return []
    followed_ids = {p["mlbID"] for p in followed_players}

    season = db.get_seasons("batting")[0]
    recent_batting = db.load_recent_batting(season, mtime)
    recent_pitching = db.load_recent_pitching(season, mtime)
    if not recent_pitching.empty:
        recent_pitching = recent_pitching.assign(mlbID=recent_pitching["mlbID"].astype(int))

    day_batting = (
        recent_batting[(recent_batting["period"] == "day") & recent_batting["mlbID"].isin(followed_ids)]
        if not recent_batting.empty else recent_batting
    )
    day_pitching = (
        recent_pitching[(recent_pitching["period"] == "day") & recent_pitching["mlbID"].isin(followed_ids)]
        if not recent_pitching.empty else recent_pitching
    )

    items = []
    for _, row in day_batting.iterrows():
        items.append({
            "mlbID": int(row["mlbID"]), "name": row["Name"],
            "text": f"{int(row['H'])} H, {int(row['HR'])} HR, {int(row['RBI'])} RBI yesterday",
        })
    for _, row in day_pitching.iterrows():
        items.append({
            "mlbID": int(row["mlbID"]), "name": row["Name"],
            "text": f"{row['ERA']:.2f} ERA, {int(row['SO'])} SO ({row['IP']:.1f} IP) yesterday",
        })

    for m in db.get_milestones(season, mtime):
        if m["mlbID"] in followed_ids:
            items.append({"mlbID": m["mlbID"], "name": m["Name"], "text": m["text"]})

    return items[:max_items]
