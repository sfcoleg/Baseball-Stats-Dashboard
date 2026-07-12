import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Baserunning | Sabermetrics Dashboard", layout="wide")
st.title("Baserunning Stats")
st.caption(
    "SB/CS are from Baseball-Reference. Sprint Speed (feet per second in a player's fastest "
    "one-second window) and Home-to-1st time are from Statcast — not every player has enough "
    "qualifying runs to have a sprint speed on file, especially early in a season."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

seasons = db.get_seasons("batting")
season = st.selectbox("Season", seasons, index=0)
batting = teams.add_team_abbr(db.load_batting(season, db.db_mtime()))

attempts = batting["SB"] + batting["CS"]
batting["SB_PCT"] = (batting["SB"] / attempts.replace(0, float("nan")) * 100).round(1)

col1, col2, col3 = st.columns(3)
with col1:
    team_options = ["All"] + sorted(batting["Tm"].dropna().unique().tolist())
    team = st.selectbox("Team", team_options)
with col2:
    min_pa = st.slider("Minimum PA", 0, int(batting["PA"].max()), 50)
with col3:
    sort_by = st.selectbox(
        "Sort by", ["SB", "SB_PCT", "sprint_speed", "hp_to_1b", "CS", "PA"], index=0,
        format_func=lambda c: {"SB_PCT": "SB%", "sprint_speed": "Sprint Speed", "hp_to_1b": "Home-to-1st"}.get(c, c),
    )

filtered = batting[batting["PA"] >= min_pa]
if team != "All":
    filtered = filtered[filtered["Tm"] == team]
ascending = sort_by == "hp_to_1b"
filtered = filtered.sort_values(sort_by, ascending=ascending, na_position="last").reset_index(drop=True)

max_rows = st.slider(
    "Max rows shown", 25, max(len(filtered), 25), min(75, max(len(filtered), 25)),
    help="Lower this if the dashboard is crashing — rendering large tables is the most memory-intensive thing this app does.",
)
table_rows = filtered.head(max_rows)
st.caption(f"{len(filtered)} players match filters — showing {len(table_rows)}.")

display = table_rows[
    ["Name", "Age", "Tm", "PA", "SB", "CS", "SB_PCT", "sprint_speed", "hp_to_1b"]
].rename(columns={"SB_PCT": "SB%", "sprint_speed": "Sprint Speed", "hp_to_1b": "Home-to-1st"})
st.dataframe(
    style.style_stats_table(
        display,
        higher_better=["SB", "SB%", "Sprint Speed"],
        lower_better=["Home-to-1st"],
        team_col="Tm",
        team_color_fn=teams.color_for_abbr,
        precision={"SB%": "{:.1f}", "Sprint Speed": "{:.1f}", "Home-to-1st": "{:.2f}"},
    ),
    use_container_width=True,
    height=600,
)

st.subheader("Sprint Speed vs. Stolen Bases")
chart_df = filtered.dropna(subset=["sprint_speed", "SB"])
fig = px.scatter(
    chart_df, x="sprint_speed", y="SB", size="PA", color="SB_PCT",
    hover_name="Name", color_continuous_scale="OrRd",
    labels={"sprint_speed": "Sprint Speed (ft/s)", "SB": "Stolen Bases", "SB_PCT": "SB%"},
)
fig.update_layout(
    height=450, margin=dict(l=0, r=0, t=10, b=0),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font_color="#FAFAFA",
)
st.plotly_chart(fig, use_container_width=True)
