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

if games.empty:
    st.caption(f"No games today. {ndb.current_season_label()} season status: check Standings.")
else:
    for _, g in games.iterrows():
        away, home = g.get("away_abbr") or "?", g.get("home_abbr") or "?"
        # gameStatus: 1 scheduled (no score yet), 2 live, 3 final.
        status_code = g.get("game_status")
        a_score = g.get("away_score") if status_code != 1 else None
        h_score = g.get("home_score") if status_code != 1 else None
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 1, 2])
            a_line = f"**{nteams.nickname_for_abbr(away)}** ({away})"
            h_line = f"**{nteams.nickname_for_abbr(home)}** ({home})"
            if a_score is not None:
                a_line += f" — {int(a_score)}"
            if h_score is not None:
                h_line += f" — {int(h_score)}"
            c1.markdown(a_line)
            live_chip = " 🔴" if status_code == 2 else ""
            c2.markdown(f"<div style='text-align:center;color:var(--dm-dim)'>"
                       f"{g.get('game_status_text', '')}{live_chip}</div>", unsafe_allow_html=True)
            c3.markdown(h_line)
