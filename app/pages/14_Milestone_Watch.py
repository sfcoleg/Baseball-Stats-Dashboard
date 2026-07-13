import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Milestone Watch | Diamond Metrics", layout="wide")
st.title("Milestone Watch")
st.caption(
    "Every active player within reach of a round-number career milestone (500 HR, 3000 K, ...). "
    "Uses MLB's own career totals rather than just this app's 2010+ cached seasons, so a player "
    "whose career started earlier is still tracked accurately."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
watch = db.milestone_watch(mtime, limit=40)

if watch.empty:
    st.info("No milestone data yet — run the ingest script to populate career totals.")
    st.stop()

display = watch.copy()
display["Team"] = display.apply(lambda r: teams.team_meta_from_city(r["Tm"], r["Lev"])[0], axis=1)
display = display[["Name", "Team", "Stat", "Total", "Milestone", "Remaining"]]

st.dataframe(
    style.style_stats_table(display, lower_better=["Remaining"]),
    use_container_width=True,
    hide_index=True,
    height=600,
)
