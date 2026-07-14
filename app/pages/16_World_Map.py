import sys
from pathlib import Path

import numpy as np
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style

st.set_page_config(page_title="World Map | Diamond Metrics", layout="wide")
st.title("World Map")
st.caption(
    "Every MLB player we have birthplace data for. Click a country or state to see who's from there — "
    "click a player to jump to their profile."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

bio = db.load_player_bio(db.db_mtime())
if bio.empty:
    st.info("No birthplace data yet — run the ingest script to populate it.")
    st.stop()

# Plotly's locationmode="country names" matches a fixed reference list that
# doesn't recognize every alias the MLB Stats API uses — most notably "USA"
# itself, by far the largest cohort. Only remapping known mismatches rather
# than guessing at every country keeps this honest about what's covered.
COUNTRY_NAME_FIXES = {
    "USA": "United States",
    "South Korea": "South Korea",
    "Republic of Korea": "South Korea",
    "Netherlands Antilles": "Curacao",
}


def _player_list(players):
    for _, row in players.sort_values("Name").iterrows():
        if st.button(row["Name"], key=f"worldmap_{row['mlbID']}", use_container_width=True):
            st.session_state["selected_mlbID"] = int(row["mlbID"])
            st.session_state["selected_name"] = row["Name"]
            st.switch_page("pages/_Player.py")


tab_world, tab_usa = st.tabs(["World", "United States"])

with tab_world:
    by_country = bio.dropna(subset=["birth_country"]).copy()
    by_country["map_country"] = by_country["birth_country"].replace(COUNTRY_NAME_FIXES)
    counts = by_country.groupby("map_country").size().reset_index(name="Players")
    # The US alone outnumbers every other country combined, so a linear
    # color scale washes every other country out to near-white. Coloring by
    # log(count) instead keeps smaller countries visually distinguishable;
    # the hover label still shows the real player count via customdata.
    counts["log_players"] = np.log1p(counts["Players"])

    fig = px.choropleth(
        counts, locations="map_country", locationmode="country names", color="log_players",
        color_continuous_scale="Blues", hover_name="map_country", custom_data=["Players"],
    )
    fig.update_traces(hovertemplate="%{hovertext}<br>%{customdata[0]} players<extra></extra>")
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0), height=480,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA",
        geo=dict(bgcolor="rgba(0,0,0,0)", showframe=False, showcountries=True, countrycolor="#33405F"),
        coloraxis_showscale=False,
    )
    event = st.plotly_chart(fig, on_select="rerun", key="world_map_country", use_container_width=True)

    points = event.selection.get("points", []) if event and event.selection else []
    if points:
        clicked = points[0].get("location")
        players = by_country[by_country["map_country"] == clicked]
        style.colored_header(f"{clicked} ({len(players)})", "chart")
        _player_list(players)
    else:
        st.caption("Click a country on the map to see its players.")

with tab_usa:
    by_state = bio[(bio["birth_country"] == "USA") & bio["birth_state"].notna()].copy()
    counts = by_state.groupby("birth_state").size().reset_index(name="Players")
    counts["log_players"] = np.log1p(counts["Players"])

    fig = px.choropleth(
        counts, locations="birth_state", locationmode="USA-states", scope="usa", color="log_players",
        color_continuous_scale="Blues", hover_name="birth_state", custom_data=["Players"],
    )
    fig.update_traces(hovertemplate="%{hovertext}<br>%{customdata[0]} players<extra></extra>")
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0), height=420,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA",
        geo=dict(bgcolor="rgba(0,0,0,0)"),
        coloraxis_showscale=False,
    )
    event = st.plotly_chart(fig, on_select="rerun", key="world_map_state", use_container_width=True)

    points = event.selection.get("points", []) if event and event.selection else []
    if points:
        clicked = points[0].get("location")
        players = by_state[by_state["birth_state"] == clicked]
        style.colored_header(f"{clicked} ({len(players)})", "chart")
        _player_list(players)
    else:
        st.caption("Click a state on the map to see its players.")
