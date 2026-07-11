import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Team | Sabermetrics Dashboard", layout="wide")
st.title("Team")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
season = st.selectbox("Season", db.get_seasons("batting"), index=0)

team_options = teams.all_teams()
labels = [f"{abbr} — {nickname}" for abbr, nickname in team_options]
choice = st.selectbox("Team", labels)
selected_abbr = team_options[labels.index(choice)][0]
color = teams.color_for_abbr(selected_abbr)

batting = teams.add_team_abbr(db.load_batting(season, mtime))
pitching = teams.add_team_abbr(db.load_pitching(season, mtime))
fielding = teams.add_team_abbr_from_nickname(db.load_fielding(season, mtime))

team_batting = batting[batting["Tm"] == selected_abbr].sort_values("OPS", ascending=False)
team_pitching = pitching[pitching["Tm"] == selected_abbr].sort_values("ERA", ascending=True)
team_fielding = fielding[fielding["Tm"] == selected_abbr].sort_values("OAA", ascending=False)

st.markdown(
    f"<h2><span style='background-color:{color}66;color:#FAFAFA;padding:4px 14px;"
    f"border-radius:10px'>{selected_abbr}</span> {choice.split(' — ')[1]}</h2>",
    unsafe_allow_html=True,
)
st.caption(f"{len(team_batting)} batters, {len(team_pitching)} pitchers, {len(team_fielding)} fielders on record for {season}.")

if team_batting.empty and team_pitching.empty and team_fielding.empty:
    st.info("No players found for this team in the selected season.")
    st.stop()

style.colored_header("Batting", "batting")
st.dataframe(
    style.style_stats_table(
        team_batting[["Name", "Age", "G", "PA", "HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS"]],
        higher_better=["HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS"],
        precision={"BA": "{:.3f}", "OBP": "{:.3f}", "SLG": "{:.3f}", "OPS": "{:.3f}"},
    ),
    use_container_width=True,
    hide_index=True,
)

style.colored_header("Pitching", "pitching")
st.dataframe(
    style.style_stats_table(
        team_pitching[["Name", "Age", "G", "GS", "W", "L", "SV", "IP", "ERA", "WHIP", "SO"]],
        higher_better=["W", "SV", "SO"],
        lower_better=["ERA", "WHIP", "L"],
        precision={"ERA": "{:.2f}", "WHIP": "{:.3f}"},
    ),
    use_container_width=True,
    hide_index=True,
)

style.colored_header("Fielding", "fielding")
st.dataframe(
    style.style_stats_table(
        team_fielding[["Name", "Pos", "OAA", "FRP", "success_rate"]].rename(columns={"success_rate": "Success Rate"}),
        higher_better=["OAA", "FRP"],
    ),
    use_container_width=True,
    hide_index=True,
)
