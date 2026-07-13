import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Injury Report | Diamond Metrics", layout="wide")
st.title("Injury Report")
st.caption("Every player currently on a major-league injured list.")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

with st.spinner("Loading injury report..."):
    injuries = db.load_injury_report()

if injuries.empty:
    st.info("No injured-list data available right now.")
    st.stop()

team_options = ["All teams"] + sorted(injuries["Tm"].unique().tolist())
team_filter = st.selectbox("Team", team_options)
if team_filter != "All teams":
    injuries = injuries[injuries["Tm"] == team_filter]

st.caption(f"{len(injuries)} players on the injured list" + ("" if team_filter == "All teams" else f" for {team_filter}"))

STATUS_ORDER = ["60-Day IL", "15-Day IL", "10-Day IL", "7-Day IL"]
injuries = injuries.sort_values(
    by="Status", key=lambda s: s.map({v: i for i, v in enumerate(STATUS_ORDER)})
)

for _, row in injuries.iterrows():
    color = teams.color_for_abbr(row["Tm"])
    detail = row["Detail"] if isinstance(row["Detail"], str) and row["Detail"] else "No further detail available"
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:14px;background-color:#1B243866;"
        f"border-left:4px solid {color};padding:10px 14px;border-radius:6px;margin:6px 0'>"
        f"<img src='{style.headshot_url(row['mlbID'], width=100)}' style='width:56px;height:56px;"
        f"border-radius:50%;object-fit:cover;object-position:top;flex-shrink:0'>"
        f"<div style='flex-grow:1'>"
        f"<span style='background-color:{color}66;color:#FAFAFA;padding:2px 8px;border-radius:6px;"
        f"font-weight:700;font-size:0.85rem'>{row['Tm']}</span> "
        f"<span style='font-weight:700;font-size:1.05rem'>{row['Name']}</span> "
        f"<span style='color:#9AA3B5'>({row['Position']})</span>"
        f"<div style='color:#DCE1EA;font-size:0.9rem;margin-top:2px'>{detail}</div>"
        f"</div>"
        f"<span style='background-color:#D32F2F33;color:#FF8A80;padding:4px 10px;border-radius:8px;"
        f"font-weight:700;font-size:0.8rem;white-space:nowrap'>{row['Status']}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
