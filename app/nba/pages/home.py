"""NBA Home — today's games, or a plain statement that there aren't any.
Confirmed directly against the live scoreboard endpoint rather than
assumed: outside the season it genuinely returns zero rows, not an error,
so an empty slate is a real state to show, not a failure to handle."""
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from nba import db as ndb
from nba import teams as nteams

st.set_page_config(page_title="NBA | Diamond Metrics", layout="wide")
st.title("NBA")

mtime = ndb.nba_db_mtime()
games = ndb.load_todays_games(mtime)
abbr_map = ndb.team_abbr_map(mtime)

if games.empty:
    st.caption(f"No games today. {ndb.current_season_label()} season status: check Standings.")
else:
    for _, g in games.iterrows():
        away = abbr_map.get(g.get("VISITOR_TEAM_ID"), "?")
        home = abbr_map.get(g.get("HOME_TEAM_ID"), "?")
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 1, 2])
            c1.markdown(f"**{nteams.nickname_for_abbr(away)}** ({away})")
            c2.markdown(f"<div style='text-align:center;color:var(--dm-dim)'>"
                       f"{g.get('GAME_STATUS_TEXT', '')}</div>", unsafe_allow_html=True)
            c3.markdown(f"**{nteams.nickname_for_abbr(home)}** ({home})")
            if g.get("ARENA_NAME"):
                st.caption(g["ARENA_NAME"])
