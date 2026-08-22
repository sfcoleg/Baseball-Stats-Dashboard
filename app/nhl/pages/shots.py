"""NHL Shot Maps — every shot attempt plotted on a normalized rink, by
player or by team (for/against). Data: ingest/nhl_shots.py (play-by-play
backfill)."""
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from nhl import db as ndb
from nhl import style as nstyle
from nhl import teams as nteams

st.set_page_config(page_title="NHL Shot Maps | Diamond Metrics", layout="wide")
st.title("Shot Maps")

mtime = ndb.nhl_db_mtime()
seasons = ndb.shot_seasons(mtime)
if not seasons:
    st.info("No shot location data yet — run `python ingest/nhl_shots.py <season>` to backfill.")
    st.stop()

season = st.selectbox("Season", seasons, format_func=ndb.season_label)
shots = ndb.load_shots(season, mtime)
shots["Tm"] = shots["teamId"].map(nteams.abbr_for_id)
st.caption(
    "Coordinates are normalized so every shot attacks the right-hand goal, regardless of period or "
    "home/away — a player's or team's shots always cluster the same direction."
)

view = st.radio("View", ["Player", "Team"], horizontal=True)

if view == "Player":
    query = st.text_input("Player", placeholder="e.g. McDavid")
    if not query.strip():
        st.info("Search a skater to see their shot chart.")
        st.stop()
    matches = ndb.search_players(query, season, mtime)
    matches = matches[matches["role"] == "Skater"]
    if matches.empty:
        st.warning(f"No skaters found matching '{query}'.")
        st.stop()
    if len(matches) == 1:
        chosen = matches.iloc[0]
    else:
        options = [f"{row.Name} ({nteams._primary(row.Tm)})" for row in matches.itertuples()]
        choice = st.selectbox(f"{len(matches)} matches", options)
        chosen = matches.iloc[options.index(choice)]

    player_shots = shots[shots["shooterId"] == chosen["playerId"]]
    if player_shots.empty:
        st.info(f"No shot data on file for {chosen['Name']} in {ndb.season_label(season)}.")
        st.stop()

    goals = (player_shots["result"] == "goal").sum()
    on_net = player_shots["result"].isin(["goal", "shot-on-goal"]).sum()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Shot Attempts", len(player_shots))
    m2.metric("On Net", on_net)
    m3.metric("Goals", int(goals))
    m4.metric("Shooting %", f"{goals / on_net * 100:.1f}%" if on_net else "—")
    st.plotly_chart(nstyle.shot_map_chart(player_shots, chosen["Name"]), use_container_width=True)

else:
    team = st.selectbox("Team", [abbr for abbr, _ in nteams.all_teams()], format_func=lambda a: f"{a} — {nteams.nickname_for_abbr(a)}")
    side = st.radio("Shots", ["For", "Against"], horizontal=True)
    if side == "For":
        team_shots = shots[shots["Tm"] == team]
        title = f"{team} — Shots For"
    else:
        # "Against" needs the OPPONENT's team id per game, which isn't
        # stored directly — approximate via goalieId instead: shots where
        # this team's goalie was in net are shots this team faced.
        goalies_df = ndb.load_goalies(season, mtime)
        team_goalie_ids = set(goalies_df[goalies_df["teamAbbrevs"].map(nteams._primary) == team]["playerId"])
        team_shots = shots[shots["goalieId"].isin(team_goalie_ids)]
        title = f"{team} — Shots Against"
    if team_shots.empty:
        st.info(f"No shot data on file for {team} in {ndb.season_label(season)}.")
        st.stop()
    goals = (team_shots["result"] == "goal").sum()
    on_net = team_shots["result"].isin(["goal", "shot-on-goal"]).sum()
    m1, m2, m3 = st.columns(3)
    m1.metric("Shot Attempts", len(team_shots))
    m2.metric("On Net", on_net)
    m3.metric("Goals", int(goals))
    st.plotly_chart(nstyle.shot_map_chart(team_shots, title), use_container_width=True)
