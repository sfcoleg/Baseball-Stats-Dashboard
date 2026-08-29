"""The cross-league Following page, shared by all three sports.

One page rather than three. The six follow lists already live in a single
localStorage payload under one key (see following.py), so the split into an
MLB page, an NHL page and an NFL page was only ever a UI artifact — and a
bad one, since following a hockey player while browsing football meant
navigating to a different sport first.

Rendered from a shared module rather than by pointing three st.Page entries
at one file, so each sport's tab strip keeps its own "Following" entry and
nothing about routing changes."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent))
import following
import style

# (teams key, players key, label, ID FIELD NAME used inside player dicts)
#
# That last field matters and is not cosmetic. The three sports were built at
# different times and each stores its player id under a different name —
# mlbID, playerId, player_id — inside the saved payload. Normalising them to
# a shared "id" here would orphan every follow anyone has already saved, so
# this module reads and writes each sport's existing shape instead.
SPORTS = (
    ("followed_teams", "followed_players", "MLB", "mlbID"),
    ("followed_nhl_teams", "followed_nhl_players", "NHL", "playerId"),
    ("followed_nfl_teams", "followed_nfl_players", "NFL", "player_id"),
)


def _lists():
    """The six lists, created if absent. setdefault rather than assignment so
    this never clobbers what bootstrap() already loaded from localStorage."""
    out = {}
    for team_key, player_key, label, id_field in SPORTS:
        out[label] = {
            "teams": st.session_state.setdefault(team_key, []),
            "players": st.session_state.setdefault(player_key, []),
            "team_key": team_key,
            "player_key": player_key,
            "id_field": id_field,
        }
    return out


def summary_line(lists) -> str:
    """"3 teams and 2 players across MLB and NHL" — or a nudge when empty."""
    teams = sum(len(v["teams"]) for v in lists.values())
    players = sum(len(v["players"]) for v in lists.values())
    active = [label for label, v in lists.items() if v["teams"] or v["players"]]
    if not active:
        return ""
    parts = []
    if teams:
        parts.append(f"{teams} team{'s' if teams != 1 else ''}")
    if players:
        parts.append(f"{players} player{'s' if players != 1 else ''}")
    where = " and ".join(active) if len(active) < 3 else ", ".join(active[:-1]) + " and " + active[-1]
    return f"Following {' and '.join(parts)} across {where}."


def team_chip(abbr: str, label: str, color: str) -> str:
    return (
        f"<span style='background-color:{color}66;color:var(--dm-text);padding:3px 10px;"
        f"border-radius:8px;font-weight:700;margin-right:6px'>{abbr}</span>{label}"
    )


def render_manage(mlb_ctx=None, nhl_ctx=None, nfl_ctx=None):
    """The add/remove UI for all three leagues, in one expander with a tab
    per sport.

    Each sport's context is a dict of the callables that sport needs
    (team list, player search, colour lookup) — passed in rather than
    imported here so this module stays free of all three data layers and
    a sport whose database is missing simply doesn't render a tab."""
    lists = _lists()
    contexts = [("MLB", mlb_ctx), ("NHL", nhl_ctx), ("NFL", nfl_ctx)]
    available = [(label, ctx) for label, ctx in contexts if ctx]
    if not available:
        return

    anything = any(v["teams"] or v["players"] for v in lists.values())
    with st.expander("Manage who you follow", expanded=not anything):
        tabs = st.tabs([label for label, _ in available])
        for tab, (label, ctx) in zip(tabs, available):
            with tab:
                _render_sport_manage(label, ctx, lists[label])


def _render_sport_manage(label, ctx, state):
    col1, col2 = st.columns(2)
    teams, players = state["teams"], state["players"]

    with col1:
        st.markdown("**Follow a team**")
        followed = {t["abbr"] for t in teams}
        options = [f"{abbr} — {name}" for abbr, name in ctx["all_teams"]() if abbr not in followed]
        if options:
            choice = st.selectbox("Team", options, label_visibility="collapsed",
                                  key=f"follow_team_pick_{label}")
            if st.button("Follow team", key=f"follow_team_btn_{label}"):
                abbr, name = choice.split(" — ", 1)
                teams.append({"abbr": abbr, "nickname": name})
                st.rerun()
        else:
            st.caption("You're following every team.")
        if teams:
            st.markdown("**Following**")
            for t in list(teams):
                c1, c2 = st.columns([4, 1])
                c1.markdown(team_chip(t["abbr"], t.get("nickname", ""), ctx["color"](t["abbr"])),
                            unsafe_allow_html=True)
                if c2.button("Unfollow", key=f"unfollow_team_{label}_{t['abbr']}"):
                    teams.remove(t)
                    st.rerun()

    with col2:
        st.markdown("**Follow a player**")
        query = st.text_input("Search players", label_visibility="collapsed",
                              placeholder=ctx.get("placeholder", "Search"),
                              key=f"follow_search_{label}")
        id_field = state["id_field"]
        if query.strip():
            matches = ctx["search"](query)
            followed_ids = {str(p.get(id_field)) for p in players}
            shown = 0
            for row in matches:
                if str(row["id"]) in followed_ids:
                    continue
                c1, c2 = st.columns([4, 1])
                c1.markdown(row["label"])
                if c2.button("Follow", key=f"follow_player_{label}_{row['id']}"):
                    # Written under this sport's OWN id field, and with the
                    # same value type it has always used, so entries stay
                    # readable by the per-sport pages and by anything already
                    # saved in a visitor's browser.
                    entry = {id_field: ctx.get("id_cast", str)(row["id"]), "name": row["name"]}
                    if row.get("role"):
                        entry["role"] = row["role"]
                    players.append(entry)
                    st.rerun()
                shown += 1
                if shown >= 8:
                    break
            if shown == 0:
                st.caption("No matches.")
        if players:
            st.markdown("**Following**")
            for p in list(players):
                c1, c2 = st.columns([4, 1])
                c1.markdown(p.get("name", "—"))
                if c2.button("Unfollow", key=f"unfollow_player_{label}_{p.get(id_field)}"):
                    players.remove(p)
                    st.rerun()


def render_empty_state():
    st.info(
        'You\'re not following any teams or players yet — use "Manage who you follow" '
        "above to get started. Anything you follow here shows up in every sport."
    )
