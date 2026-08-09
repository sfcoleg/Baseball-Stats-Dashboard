import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Playoffs | Diamond Metrics", layout="wide")

clicked_team = st.query_params.get("team")
if clicked_team:
    st.session_state["team_page_selected_team"] = clicked_team
    st.switch_page("pages/4_Team.py")

st.title("Playoffs")
st.caption(
    "Playoff and World Series odds are a Monte Carlo simulation of the rest of the season (see the Team "
    "page for the methodology). The bracket below is the actual current seeding if the season ended today — "
    "not a simulated outcome. Click a team to jump to its Team page."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
standings = db.load_standings(mtime)
playoff_odds = db.compute_playoff_odds(mtime)

if standings.empty or playoff_odds.empty:
    st.info("No standings/odds data yet — run the ingest script.")
    st.stop()

style.colored_header("If the Season Ended Today", "headliners")
picture = db.current_playoff_picture(mtime)
bcol1, bcol2 = st.columns(2)
for col, league, label in zip((bcol1, bcol2), ("AL", "NL"), ("AL — American League", "NL — National League")):
    with col:
        st.markdown(f"**{label}**")
        if league in picture:
            st.markdown(style.playoff_bracket_html(picture[league], teams.color_for_abbr), unsafe_allow_html=True)
        else:
            st.caption("No seeding data yet.")

st.divider()

style.colored_header("Playoff & World Series Odds", "batting")
merged = standings.merge(
    playoff_odds[["team_abbr", "playoff_pct", "division_pct", "wildcard_pct", "ws_pct"]],
    on="team_abbr", how="left",
)
for league, header_color in (("AL", "batting"), ("NL", "pitching")):
    league_df = merged[merged["league"] == league].sort_values(
        ["playoff_pct", "ws_pct"], ascending=[False, False],
    )
    if league_df.empty:
        continue
    st.markdown(f"**{league} — {'American' if league == 'AL' else 'National'} League**")
    display = league_df[["team_abbr", "wins", "losses", "playoff_pct", "division_pct", "wildcard_pct", "ws_pct"]].rename(
        columns={
            "team_abbr": "Team", "wins": "W", "losses": "L", "playoff_pct": "Playoff%",
            "division_pct": "Division%", "wildcard_pct": "Wildcard%", "ws_pct": "WS%",
        }
    )
    st.markdown(
        "<div style='overflow-x:auto'>" + style.playoff_odds_table(display, teams.color_for_abbr) + "</div>",
        unsafe_allow_html=True,
    )
