import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Prospects | Sabermetrics Dashboard", layout="wide")
st.title("Prospects")
st.caption(
    "MLB doesn't expose proprietary Top-100-style prospect rankings through its free public API, so "
    "this tracks the real thing instead: every player making their MLB debut this season, recent "
    "call-ups from the minors, and how each rookie is actually performing so far."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
season = db.get_seasons("batting")[0]
batting = teams.add_team_abbr(db.load_batting(season, mtime))
pitching = teams.add_team_abbr(db.load_pitching(season, mtime))

style.colored_header("Recent Call-Ups", "batting")
call_up_window = st.selectbox("Call-up lookback window", ["Last 7 days", "Last 14 days", "Last 30 days"], index=1)
call_up_days = {"Last 7 days": 7, "Last 14 days": 14, "Last 30 days": 30}[call_up_window]

with st.spinner("Loading recent transactions..."):
    txs = db.load_transactions(call_up_days)
call_ups = txs[txs["type"].isin(["Recalled", "Selected"])] if not txs.empty else txs

if call_ups.empty:
    st.caption("No call-ups in this window.")
else:
    st.markdown("<br>".join(
        f"<div style='background-color:#1B243866;border-left:4px solid #4C9F70;padding:8px 14px;"
        f"border-radius:6px;margin:4px 0'><span style='color:#9AA3B5;font-size:0.85rem'>{row['date']}</span>"
        f" &mdash; {row['description']}</div>"
        for _, row in call_ups.iterrows()
    ), unsafe_allow_html=True)

style.colored_header(f"{season} Rookie Debuts", "pitching")
st.caption(
    "Every player in this season's batting/pitching data whose official MLB debut fell within "
    f"{season} — sorted so the freshest debuts and best performers surface first."
)

all_ids = tuple(pd.concat([batting["mlbID"], pitching["mlbID"]]).dropna().unique().tolist())
with st.spinner("Loading player bios..."):
    bio = db.load_player_bio(all_ids)

rookie_ids = {
    mlbID for mlbID, info in bio.items()
    if info.get("debut") and info["debut"].startswith(str(season))
}

rookie_batting = batting[batting["mlbID"].isin(rookie_ids)].copy()
rookie_pitching = pitching[pitching["mlbID"].isin(rookie_ids)].copy()

tab1, tab2 = st.tabs(["Batters", "Pitchers"])

with tab1:
    if rookie_batting.empty:
        st.caption("No rookie batters found for this season.")
    else:
        rookie_batting["Debut"] = rookie_batting["mlbID"].map(lambda m: bio.get(m, {}).get("debut"))
        rookie_batting = rookie_batting.sort_values("Debut", ascending=False)
        display = rookie_batting[["Name", "Tm", "Debut", "Age", "PA", "BA", "OBP", "SLG", "OPS", "HR", "wOBA"]]
        st.dataframe(
            style.style_stats_table(
                display, higher_better=["OPS", "wOBA", "HR"], team_col="Tm", team_color_fn=teams.color_for_abbr,
                precision={"BA": "{:.3f}", "OBP": "{:.3f}", "SLG": "{:.3f}", "OPS": "{:.3f}", "wOBA": "{:.3f}"},
            ),
            use_container_width=True, height=560, hide_index=True,
        )

with tab2:
    if rookie_pitching.empty:
        st.caption("No rookie pitchers found for this season.")
    else:
        rookie_pitching["Debut"] = rookie_pitching["mlbID"].map(lambda m: bio.get(m, {}).get("debut"))
        rookie_pitching = rookie_pitching.sort_values("Debut", ascending=False)
        display = rookie_pitching[["Name", "Tm", "Debut", "Age", "G", "GS", "IP", "ERA", "WHIP", "SO", "FIP"]]
        st.dataframe(
            style.style_stats_table(
                display, lower_better=["ERA", "WHIP", "FIP"], team_col="Tm", team_color_fn=teams.color_for_abbr,
                precision={"ERA": "{:.2f}", "WHIP": "{:.2f}", "FIP": "{:.2f}"},
            ),
            use_container_width=True, height=560, hide_index=True,
        )
