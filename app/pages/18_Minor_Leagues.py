import sys
from datetime import date
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db

st.set_page_config(page_title="Minor Leagues | Diamond Metrics", layout="wide")
st.title("Minor Leagues")
st.caption(
    "A lighter version of the main site for the minors — real per-player stats from the MLB "
    "Stats API, fetched live rather than backfilled across seasons like the MLB pages. Levels: "
    "Triple-A, Double-A, High-A, Single-A, Rookie."
)

CURRENT_SEASON = date.today().year
SEASONS = list(range(CURRENT_SEASON, CURRENT_SEASON - 3, -1))
LEVELS = list(db.MILB_LEVELS.keys())

bat_tab, pit_tab = st.tabs(["Batting", "Pitching"])

with bat_tab:
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        level = st.selectbox("Level", LEVELS, key="milb_bat_level")
    with c2:
        season = st.selectbox("Season", SEASONS, key="milb_bat_season")
    with c3:
        min_pa = st.number_input("Min PA", min_value=0, value=50, step=10, key="milb_bat_min_pa")

    with st.spinner("Loading..."):
        bat_df = db.load_milb_stats(db.MILB_LEVELS[level], "hitting", season)
    if bat_df.empty:
        st.info("No data available for this level/season yet.")
    else:
        bat_df = bat_df[bat_df["PA"].fillna(0) >= min_pa].sort_values("OPS", ascending=False)
        st.caption(f"{len(bat_df)} players")
        st.dataframe(
            bat_df[[
                "Name", "Tm", "League", "Age", "G", "PA", "AB", "R", "H", "2B", "3B",
                "HR", "RBI", "BB", "SO", "SB", "AVG", "OBP", "SLG", "OPS",
            ]],
            use_container_width=True, hide_index=True, height=600,
        )

with pit_tab:
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        level = st.selectbox("Level", LEVELS, key="milb_pit_level")
    with c2:
        season = st.selectbox("Season", SEASONS, key="milb_pit_season")
    with c3:
        min_ip = st.number_input("Min IP", min_value=0, value=10, step=5, key="milb_pit_min_ip")

    with st.spinner("Loading..."):
        pit_df = db.load_milb_stats(db.MILB_LEVELS[level], "pitching", season)
    if pit_df.empty:
        st.info("No data available for this level/season yet.")
    else:
        pit_df = pit_df[pit_df["IP"].fillna(0) >= min_ip].sort_values("ERA", ascending=True)
        st.caption(f"{len(pit_df)} players")
        st.dataframe(
            pit_df[["Name", "Tm", "League", "Age", "G", "GS", "W", "L", "SV", "IP", "ERA", "WHIP", "SO", "BB", "HR"]],
            use_container_width=True, hide_index=True, height=600,
        )
