"""NFL Following — the teams and players you follow.

Persistence rides the same browser-localStorage bridge as the MLB and NHL
Following pages (see app/following.py): one storage key, one payload, now six
lists. Sport-specific lists because a team abbreviation and a player id mean
different things in each sport, but they save and load together."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import following
import style
from nfl import db as fdb
from nfl import teams as fteams

st.set_page_config(page_title="NFL Following | Diamond Metrics", layout="wide")
st.title("Following")

mtime = fdb.nfl_db_mtime()
season_list = fdb.seasons(mtime)
if not season_list:
    st.info("No NFL data yet — run `python ingest/nfl_refresh.py` to build it.")
    st.stop()
season = fdb.default_season(mtime) or season_list[0]

followed_teams = st.session_state.setdefault("followed_nfl_teams", [])
followed_players = st.session_state.setdefault("followed_nfl_players", [])

with st.expander("Manage who you follow", expanded=not (followed_teams or followed_players)):
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Follow a team**")
        followed_abbrs = {t["abbr"] for t in followed_teams}
        labels = [f"{a} — {n}" for a, n in fteams.all_teams() if a not in followed_abbrs]
        if labels:
            choice = st.selectbox("Team", labels, label_visibility="collapsed", key="nfl_follow_team_pick")
            if st.button("Follow team", key="nfl_follow_team_btn"):
                abbr, nickname = choice.split(" — ")
                followed_teams.append({"abbr": abbr, "nickname": nickname})
                st.rerun()
        else:
            st.caption("You're following every team.")

        if followed_teams:
            st.markdown("**Following**")
            for t in list(followed_teams):
                c1, c2 = st.columns([4, 1])
                c1.markdown(
                    f"<span style='background-color:{fteams.color_for_abbr(t['abbr'])}66;"
                    f"color:var(--dm-text);padding:3px 10px;border-radius:8px;font-weight:700'>"
                    f"{t['abbr']}</span> {t['nickname']}",
                    unsafe_allow_html=True,
                )
                if c2.button("Unfollow", key=f"nfl_unfollow_team_{t['abbr']}"):
                    followed_teams.remove(t)
                    st.rerun()

    with col2:
        st.markdown("**Follow a player**")
        query = st.text_input(
            "Search players", label_visibility="collapsed",
            placeholder="e.g. Mahomes, Jefferson", key="nfl_follow_search",
        )
        followed_ids = {p["player_id"] for p in followed_players}
        if query.strip():
            matches = fdb.search_players(query, mtime)
            if not matches.empty:
                matches = matches[~matches["player_id"].isin(followed_ids)]
            for _, row in matches.head(8).iterrows():
                c1, c2 = st.columns([4, 1])
                c1.markdown(f"{row['player_display_name']} ({row['team']}) — {row['position']}")
                if c2.button("Follow", key=f"nfl_follow_player_{row['player_id']}"):
                    followed_players.append({
                        "player_id": str(row["player_id"]),
                        "name": row["player_display_name"],
                        "position": row["position"],
                    })
                    st.rerun()
            if matches.empty:
                st.caption("No matches.")

        if followed_players:
            st.markdown("**Following**")
            for p in list(followed_players):
                c1, c2 = st.columns([4, 1])
                c1.markdown(p["name"])
                if c2.button("Unfollow", key=f"nfl_unfollow_player_{p['player_id']}"):
                    followed_players.remove(p)
                    st.rerun()

following.save()

if not followed_teams and not followed_players:
    st.info("You're not following any teams or players yet - use \"Manage who you follow\" above to get started.")
    st.stop()

# --- Followed teams --------------------------------------------------------
if followed_teams:
    style.colored_header("Your Teams", "batting")
    standings = fdb.load_standings(season, mtime)
    games = fdb.load_games(season, mtime)
    for t in followed_teams:
        with st.container(border=True):
            row = standings[standings["team"] == t["abbr"]] if not standings.empty else pd.DataFrame()
            header = (
                f"<span style='background-color:{fteams.color_for_abbr(t['abbr'])}66;"
                f"color:var(--dm-text);padding:3px 10px;border-radius:8px;font-weight:700'>"
                f"{t['abbr']}</span> <span style='font-weight:700'>{t['nickname']}</span>"
            )
            if not row.empty:
                r = row.iloc[0]
                header += (
                    f" <span style='color:var(--dm-dim)'>· {fdb.record_string(r)}, "
                    f"{int(r['points_for'])} PF / {int(r['points_against'])} PA · "
                    f"{r['team_division']}</span>"
                )
            st.markdown(header, unsafe_allow_html=True)

            own = fdb.team_schedule(games, t["abbr"]) if not games.empty else pd.DataFrame()
            if own.empty:
                st.caption("No games on file for this season.")
                continue
            upcoming = own[~own["played"]].head(3)
            played = own[own["played"]].tail(3)
            if not upcoming.empty:
                st.caption("Next up: " + " · ".join(
                    f"{'vs' if g['is_home'] else '@'} {g['opponent']} {g.get('gameday', '')}"
                    for _, g in upcoming.iterrows()
                ))
            elif not played.empty:
                st.caption("Last games: " + " · ".join(
                    f"{'vs' if g['is_home'] else '@'} {g['opponent']} "
                    f"{g['result']} {int(g['points_for'])}-{int(g['points_against'])}"
                    for _, g in played.iterrows()
                ))

# --- Followed players ------------------------------------------------------
if followed_players:
    style.colored_header("Your Players", "pitching")
    seasons_frame = fdb.load_player_seasons(season, mtime)
    rows = []
    for p in followed_players:
        match = seasons_frame[seasons_frame["player_id"] == p["player_id"]] if not seasons_frame.empty else pd.DataFrame()
        if match.empty:
            continue
        s = match.iloc[0]
        # Show the line that fits what he actually does, rather than a fixed
        # set of columns that would be blank for two thirds of the roster.
        if (s.get("attempts") or 0) >= 50:
            line = f"{int(s['passing_yards'])} yds, {int(s['passing_tds'])} TD, {int(s['passing_interceptions'])} INT"
        elif (s.get("carries") or 0) >= 25:
            line = f"{int(s['rushing_yards'])} yds, {int(s['rushing_tds'])} TD ({int(s['carries'])} car)"
        elif (s.get("targets") or 0) >= 15:
            line = f"{int(s['receptions'])} rec, {int(s['receiving_yards'])} yds, {int(s['receiving_tds'])} TD"
        else:
            line = "—"
        rows.append({
            "Name": p["name"], "Tm": s.get("team") or "", "Pos": p.get("position") or "",
            "G": s.get("games"), "Line": line,
        })
    if rows:
        st.caption(f"{fdb.season_label(season)} season totals.")
        st.dataframe(
            style.style_stats_table(
                pd.DataFrame(rows), team_col="Tm", team_color_fn=fteams.color_for_abbr,
                precision={"G": "{:.0f}"},
            ),
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("No season stats on file for the players you follow.")
