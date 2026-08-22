import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Box Score Search | Diamond Metrics", layout="wide")
st.title("Box Score Search")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

all_abbrs = sorted(db.load_standings(db.db_mtime())["team_abbr"].dropna().unique().tolist())

col1, col2 = st.columns([2, 1])
with col1:
    picked_date = st.date_input(
        "Date", value=db.today_pacific() - timedelta(days=1),
        min_value=date(2010, 1, 1), max_value=db.today_pacific(),
    )
with col2:
    team_filter = st.selectbox("Team", ["All teams"] + all_abbrs)

with st.spinner("Loading schedule..."):
    games = db.load_schedule_for_date(picked_date.isoformat())

if games.empty:
    st.info("No games found for this date.")
    st.stop()

if team_filter != "All teams":
    games = games[(games["away_abbr"] == team_filter) | (games["home_abbr"] == team_filter)]

if games.empty:
    st.info(f"{team_filter} didn't play on {picked_date.isoformat()}.")
    st.stop()

FINAL_STATUSES = {"Final", "Game Over", "Completed Early"}

for _, row in games.iterrows():
    away_color, home_color = teams.color_for_abbr(row["away_abbr"]), teams.color_for_abbr(row["home_abbr"])
    with st.container(border=True):
        acol, mid, hcol = st.columns([3, 1, 3])
        with acol:
            st.markdown(
                f"<span style='background-color:{away_color}66;color:#FAFAFA;padding:3px 10px;"
                f"border-radius:8px;font-weight:700'>{row['away_abbr']}</span> &nbsp;"
                f"<span style='font-weight:700;font-size:1.1rem'>{row['away_team']}</span>",
                unsafe_allow_html=True,
            )
        with mid:
            if pd.notna(row["away_score"]) and pd.notna(row["home_score"]):
                st.markdown(
                    f"<div style='text-align:center;font-size:1.4rem;font-weight:700'>"
                    f"{int(row['away_score'])} - {int(row['home_score'])}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown("<div style='text-align:center;color:#9AA3B5'>@</div>", unsafe_allow_html=True)
            st.caption(f"<div style='text-align:center'>{row['status']}</div>", unsafe_allow_html=True)
        with hcol:
            st.markdown(
                f"<span style='background-color:{home_color}66;color:#FAFAFA;padding:3px 10px;"
                f"border-radius:8px;font-weight:700'>{row['home_abbr']}</span> &nbsp;"
                f"<span style='font-weight:700;font-size:1.1rem'>{row['home_team']}</span>",
                unsafe_allow_html=True,
            )

        if row["status"] not in FINAL_STATUSES:
            st.caption("This game hasn't finished — no box score yet.")
            continue

        box_key = f"show_box_{row['game_pk']}"
        is_shown = st.session_state.get(box_key, False)
        if st.button("Hide box score" if is_shown else "Show box score", key=f"btn_{row['game_pk']}"):
            st.session_state[box_key] = not is_shown
            st.rerun()

        if is_shown:
            linescore = db.load_linescore(row["game_pk"])
            if not linescore or "innings" not in linescore:
                st.caption("Box score not available.")
            else:
                st.markdown(
                    style.box_score_table(linescore, row["away_abbr"], row["home_abbr"], away_color, home_color),
                    unsafe_allow_html=True,
                )

            player_box = db.load_boxscore_players(row["game_pk"])
            if player_box:
                pbcol1, pbcol2 = st.columns(2)
                for col, side, abbr in ((pbcol1, "away", row["away_abbr"]), (pbcol2, "home", row["home_abbr"])):
                    with col:
                        batters = pd.DataFrame(player_box[side]["batters"])
                        if not batters.empty:
                            st.caption(f"{abbr} Batting")
                            st.dataframe(
                                batters[["Name", "Pos", "AB", "R", "H", "HR", "RBI", "BB", "SO"]],
                                hide_index=True, use_container_width=True,
                            )
                        pitchers = pd.DataFrame(player_box[side]["pitchers"])
                        if not pitchers.empty:
                            st.caption(f"{abbr} Pitching")
                            st.dataframe(pitchers, hide_index=True, use_container_width=True)
