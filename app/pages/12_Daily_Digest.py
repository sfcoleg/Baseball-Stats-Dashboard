import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Daily Digest | Diamond Metrics", layout="wide")
st.title("Daily Digest")

yesterday = date.today() - timedelta(days=1)
st.caption(f"Everything that happened in baseball on {yesterday.isoformat()}, in one scroll.")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
season = db.get_seasons("batting")[0]
recent_batting = db.load_recent_batting(season, mtime)
recent_pitching = db.load_recent_pitching(season, mtime)
milestones = db.get_milestones(season, mtime)

txs = db.load_transactions(2)
txs_yesterday = txs[txs["date"] == yesterday.isoformat()] if not txs.empty else txs
il_moves = txs_yesterday[
    (txs_yesterday["type"] == "Status Change")
    & txs_yesterday["description"].str.contains("injured list", case=False, na=False)
    & ~txs_yesterday["description"].str.contains("activated", case=False, na=False)
] if not txs_yesterday.empty else txs_yesterday

style.colored_header("Milestones", "headliners")
if milestones:
    for m in milestones:
        with st.container(border=True):
            abbr, _, color = teams.team_meta_from_city(m["Tm"], m.get("Lev"))
            style.milestone_card(m["mlbID"], m["Name"], abbr, color, m["text"])
else:
    st.caption("Nothing notable yesterday.")

style.colored_header("Top Batting Performances", "batting")
top_batters = db.top_n_recent_batters(recent_batting, "day", 5)
if top_batters.empty:
    st.caption("No batting data yet.")
else:
    for _, row in top_batters.iterrows():
        with st.container(border=True):
            abbr, _, color = teams.team_meta_from_city(row["Tm"], row.get("Lev"))
            tb = int(row["H"] + row["2B"] + 2 * row["3B"] + 3 * row["HR"])
            text = f"{tb} TB, {int(row['H'])} H, {int(row['HR'])} HR, {int(row['RBI'])} RBI"
            style.milestone_card(row["mlbID"], row["Name"], abbr, color, text)

style.colored_header("Top Pitching Performances", "pitching")
top_pitchers = db.top_n_recent_pitchers(recent_pitching, "day", 5)
if top_pitchers.empty:
    st.caption("No pitching data yet.")
else:
    for _, row in top_pitchers.iterrows():
        with st.container(border=True):
            abbr, _, color = teams.team_meta_from_city(row["Tm"], row.get("Lev"))
            if pd.notna(row.get("GSc")):
                text = f"Game Score {int(row['GSc'])}, {row['ERA']:.2f} ERA ({row['IP']:.1f} IP)"
            else:
                text = f"{row['ERA']:.2f} ERA, {int(row['SO'])} SO ({row['IP']:.1f} IP)"
            style.milestone_card(row["mlbID"], row["Name"], abbr, color, text)

style.colored_header("Transactions", "fielding")
if txs_yesterday.empty:
    st.caption("No transactions logged for this date.")
else:
    for _, row in txs_yesterday.iterrows():
        badges = ""
        for tabbr in [row["to_abbr"], row["from_abbr"]]:
            if isinstance(tabbr, str):
                color = teams.color_for_abbr(tabbr)
                badges += (
                    f"<span style='background-color:{color}66;color:#FAFAFA;padding:2px 8px;"
                    f"border-radius:6px;font-weight:700;font-size:0.8rem;margin-right:6px'>{tabbr}</span>"
                )
        st.markdown(
            f"<div style='background-color:#1B243866;border-left:4px solid #3B82F6;padding:8px 14px;"
            f"border-radius:6px;margin:4px 0'>{badges}"
            f"<span style='color:#9AA3B5;font-size:0.85rem'>{row['type']}</span>"
            f"<div style='color:#DCE1EA'>{row['description']}</div></div>",
            unsafe_allow_html=True,
        )

style.colored_header("New Injured List Moves", "pitching")
if il_moves.empty:
    st.caption("No new injured-list placements for this date.")
else:
    for _, row in il_moves.iterrows():
        abbr = row["to_abbr"] if isinstance(row["to_abbr"], str) else row["from_abbr"]
        color = teams.color_for_abbr(abbr) if isinstance(abbr, str) else "#666666"
        st.markdown(
            f"<div style='background-color:#1B243866;border-left:4px solid #D32F2F;padding:8px 14px;"
            f"border-radius:6px;margin:4px 0;color:#DCE1EA'>{row['description']}</div>",
            unsafe_allow_html=True,
        )
