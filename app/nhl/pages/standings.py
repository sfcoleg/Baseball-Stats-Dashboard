"""NHL Standings — live from the NHL's own standings API (no ingest needed;
see nhl/db.py's load_standings docstring)."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from nhl import db as ndb
from nhl import style as nstyle
from nhl import teams as nteams

st.set_page_config(page_title="NHL Standings | Diamond Metrics", layout="wide")

clicked_team = st.query_params.get("team")
if clicked_team:
    st.session_state["nhl_team_page_selected_team"] = clicked_team
    st.switch_page("nhl/pages/team.py")

st.title("Standings")
elo_model = ndb.load_elo_model()

standings = ndb.load_standings()
if standings.empty:
    st.info("Standings unavailable right now — the NHL's API may be temporarily down. Try again shortly.")
    st.stop()

display = pd.DataFrame({
    "Team": standings["teamAbbrev"],
    "conference": standings["conferenceName"],
    "division": standings["divisionName"],
    "div_seq": standings["divisionSequence"],
    "GP": standings["gamesPlayed"],
    "W": standings["wins"],
    "L": standings["losses"],
    "OTL": standings["otLosses"],
    "PTS": standings["points"],
    "ROW": standings["regulationPlusOtWins"],
    "GD": standings["goalDifferential"],
    "Streak": standings["streakCode"].fillna("") + standings["streakCount"].fillna(0).astype(int).astype(str),
    "L10": (
        standings["l10Wins"].astype(int).astype(str) + "-" + standings["l10Losses"].astype(int).astype(str)
        + "-" + standings["l10OtLosses"].astype(int).astype(str)
    ),
    "Clinch": standings["clinchIndicator"],
})

for conference in sorted(display["conference"].dropna().unique()):
    st.subheader(conference)
    conf_divs = sorted(display[display["conference"] == conference]["division"].dropna().unique())
    cols = st.columns(len(conf_divs)) if len(conf_divs) <= 2 else [st.container() for _ in conf_divs]
    for col, division in zip(cols, conf_divs):
        with col:
            st.markdown(f"**{division}**")
            div_standings = display[display["division"] == division].sort_values("div_seq")
            elo_fn = (lambda abbr: elo_model["ratings"].get(abbr)) if elo_model else None
            st.markdown(
                "<div style='overflow-x:auto'>"
                + nstyle.standings_table(div_standings, nteams.color_for_abbr, elo_fn) + "</div>",
                unsafe_allow_html=True,
            )
