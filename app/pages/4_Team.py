import sys
from pathlib import Path

import pandas as pd
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
available_seasons = db.get_seasons("batting")
season = st.selectbox("Season", available_seasons, index=0)
current_season = available_seasons[0]  # most recent season = the one recent_batting/recent_pitching cover

_COMPOSITE_COLORS = {"all": "#0C2340", "month": "#E3572A"}
_COMPOSITE_CAPTIONS = {
    "all": f"Best qualified player at each position across all 30 teams, full-season stats "
           f"(min {db._COMPOSITE_MIN_PA} PA / {db._COMPOSITE_MIN_IP} IP for starters, {db._COMPOSITE_MIN_RP_IP} IP for relievers).",
    "month": "Best performer at each position over the trailing 30 days (min PA/IP same as the Home page's \"Hot This Month\" cards).",
}

_COMPOSITE_SCOPES = {"All MLB Team": "all"}
if season == current_season:
    # recent_batting/recent_pitching are current-season-only (never backfilled
    # for historical years — see AGENTS.md), so "All Month Team" only makes
    # sense when the current season is selected.
    _COMPOSITE_SCOPES["All Month Team"] = "month"

team_options = teams.all_teams()
labels = [f"{abbr} — {nickname}" for abbr, nickname in team_options] + list(_COMPOSITE_SCOPES)

# Set by clicking a team's row on the Standings page (st.switch_page) — one-shot,
# so a manual selectbox change afterward isn't overridden on a later visit.
default_abbr = st.session_state.pop("team_page_selected_team", None)
default_index = 0
if default_abbr:
    for i, label in enumerate(labels):
        if label.startswith(f"{default_abbr} —"):
            default_index = i
            break

choice = st.selectbox("Team", labels, index=default_index)

if choice in _COMPOSITE_SCOPES:
    scope = _COMPOSITE_SCOPES[choice]
    style.colored_header(choice, "fielding")
    st.caption(_COMPOSITE_CAPTIONS[scope])
    starters = db.build_composite_team(season, mtime, scope)
    if not starters:
        st.info("Not enough data yet to build this roster.")
        st.stop()
    st.markdown(style.baseball_diamond(starters, _COMPOSITE_COLORS[scope]), unsafe_allow_html=True)

    roster_rows = [
        {"Pos": pos, "Name": player["name"], "Stat": player.get("note", "—")}
        for pos, player in starters.items()
    ]
    st.dataframe(pd.DataFrame(roster_rows), use_container_width=True, hide_index=True)
    st.stop()

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

team_id = teams.team_id_for_abbr(selected_abbr)
starters = db.load_depth_chart(team_id) if team_id else {}
if starters:
    style.colored_header("Starting Lineup", "fielding")
    st.caption("Current depth-chart starter at each position, from the MLB Stats API — not specific to the selected season.")
    st.markdown(style.baseball_diamond(starters, color), unsafe_allow_html=True)

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
