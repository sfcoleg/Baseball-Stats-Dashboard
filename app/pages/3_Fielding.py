import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Fielding | Sabermetrics Dashboard", layout="wide")
st.title("Fielding Stats")
st.caption(
    "Outs Above Average (OAA) is Statcast's range-based defensive metric — "
    "how many outs a fielder made above/below what an average fielder at "
    "that position would make. FRP = fielding runs prevented."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

seasons = db.get_seasons("fielding")
season = st.selectbox("Season", seasons, index=0)
fielding = db.load_fielding(season, db.db_mtime())

col1, col2 = st.columns(2)
with col1:
    team_options = ["All"] + sorted(fielding["Tm"].dropna().unique().tolist())
    team = st.selectbox("Team", team_options)
with col2:
    positions = ["All"] + sorted(fielding["Pos"].dropna().unique().tolist())
    position = st.selectbox("Position", positions)

filtered = fielding
if team != "All":
    filtered = filtered[filtered["Tm"] == team]
if position != "All":
    filtered = filtered[filtered["Pos"] == position]
filtered = filtered.sort_values("OAA", ascending=False).reset_index(drop=True)

max_rows = st.slider(
    "Max rows shown", 25, max(len(filtered), 25), min(150, max(len(filtered), 25)),
    help="Lower this if the dashboard is crashing — rendering large tables is the most memory-intensive thing this app does.",
)
table_rows = filtered.head(max_rows)
st.caption(f"{len(filtered)} players match filters — showing {len(table_rows)}.")
display = teams.add_team_abbr_from_nickname(table_rows)[
    ["Name", "Tm", "Pos", "OAA", "FRP", "success_rate"]
].rename(columns={"success_rate": "Success Rate"})
st.dataframe(
    style.style_stats_table(
        display,
        higher_better=["OAA", "FRP"],
        team_col="Tm",
        team_color_fn=teams.color_for_abbr,
    ),
    use_container_width=True,
    height=600,
)
