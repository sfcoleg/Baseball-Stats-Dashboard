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
    "Every active player within 10 of a round-number career milestone (500 HR, 3000 K, ...), plus "
    "anyone who's crossed one in the last 5 days. Uses MLB's own career totals rather than just this "
    "app's 2010+ cached seasons, so a player whose career started earlier is still tracked accurately."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

# (plural, singular) — every CAREER_MILESTONES threshold is a round number
# ending in 0, so "{milestone}th" is always grammatically correct with no
# 1st/2nd/3rd special-casing needed.
STAT_LABELS = {
    "HR": ("home runs", "home run"),
    "H": ("hits", "hit"),
    "RBI": ("RBI", "RBI"),
    "SB": ("stolen bases", "stolen base"),
    "W": ("wins", "win"),
    "SO": ("strikeouts", "strikeout"),
    "SV": ("saves", "save"),
}

mtime = db.db_mtime()
achievers = db.recent_milestone_achievers(mtime)
watch = db.milestone_watch(mtime, max_remaining=10)

if achievers.empty and watch.empty:
    st.info("No milestone data yet — run the ingest script to populate career totals.")
    st.stop()

if not achievers.empty:
    style.colored_header("Just Happened", "headliners")
    for row in achievers.itertuples():
        abbr, _, color = teams.team_meta_from_city(row.Tm, row.Lev)
        _, singular = STAT_LABELS.get(row.Stat, (row.Stat, row.Stat))
        text = f"{row.Milestone}th career {singular}!"
        style.milestone_achieved_card(row.mlbID, row.Name, abbr, color, text)
    if not watch.empty:
        st.divider()

if not watch.empty:
    style.colored_header("On Deck", "chart")
    for row in watch.itertuples():
        abbr, _, color = teams.team_meta_from_city(row.Tm, row.Lev)
        plural, singular = STAT_LABELS.get(row.Stat, (row.Stat, row.Stat))
        label = singular if row.Remaining == 1 else plural
        text = f"{row.Remaining} {label} from {row.Milestone}"
        style.milestone_card(row.mlbID, row.Name, abbr, color, text)
