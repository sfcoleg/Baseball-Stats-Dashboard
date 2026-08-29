"""Streaks — who is hot right now, at player and team level."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import prefs
import style
import teams

st.set_page_config(page_title="Streaks | Diamond Metrics", layout="wide")
st.title("Streaks")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
seasons = db.get_seasons("batting")
season = st.selectbox("Season", seasons, index=prefs.default_season_index(seasons))

style.colored_header("Active Hitting Streaks", "batting")
streaks = db.active_hitting_streaks(season, mtime)
window = db.history_window(season)
if window:
    # State the ceiling honestly: daily history only goes back as far as the
    # ingest has been collecting it, so a streak genuinely longer than this
    # window would be reported at the window's length, not its true one.
    st.caption(
        f"Games with at least one hit, still running. Rest days don't break a streak — "
        f"only a game he played and went hitless. Daily data begins {window[0]}, so no "
        f"streak here can be reported longer than that."
    )
if streaks.empty:
    st.caption("No active hitting streaks of 5+ games.")
else:
    # player_history stores the Baseball-Reference CITY string ("Tampa Bay"),
    # not a nickname, so this is the city lookup rather than the nickname one.
    show = pd.DataFrame({
        "Player": streaks["Name"],
        "Team": streaks["Tm"].map(lambda city: teams.team_meta_from_city(city)[0]),
        "Games": streaks["Games"],
        "Through": streaks["Last Game"],
    })
    st.dataframe(
        style.style_stats_table(show, higher_better=["Games"], precision={"Games": "{:.0f}"}),
        use_container_width=True, hide_index=True, height=430,
    )

style.colored_header("Team Streaks", "headliners")
team_rows = db.team_streaks(season, mtime)
if team_rows.empty:
    st.caption("No team streak data for this season.")
else:
    won = team_rows[team_rows["kind"] == "W"].sort_values("length", ascending=False)
    lost = team_rows[team_rows["kind"] == "L"].sort_values("length", ascending=False)
    left, right = st.columns(2)
    for col, frame, label in ((left, won, "Winning"), (right, lost, "Losing")):
        with col:
            st.markdown(f"**{label}**")
            if frame.empty:
                st.caption(f"No active {label.lower()} streaks.")
                continue
            show = pd.DataFrame({
                "Team": frame["team_abbr"],
                "Streak": frame["length"].astype(int),
                "W": frame["wins"].astype(int),
                "L": frame["losses"].astype(int),
                "Division": frame["division"],
            })
            st.dataframe(
                style.style_stats_table(
                    show, team_col="Team", team_color_fn=teams.color_for_abbr,
                    higher_better=["Streak"] if label == "Winning" else [],
                    lower_better=["Streak"] if label == "Losing" else [],
                    precision={"Streak": "{:.0f}", "W": "{:.0f}", "L": "{:.0f}"},
                ),
                use_container_width=True, hide_index=True, height=400,
            )
