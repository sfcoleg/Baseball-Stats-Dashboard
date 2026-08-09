import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Awards Race | Diamond Metrics", layout="wide")
st.title("Awards Race")
st.caption(
    "A stats-only composite score, not real award-voting data — MVP weights WAR 50% / wRC+ 25% / "
    "BsR 12.5% / OAA 12.5%; Cy Young weights WAR 50% / FIP 30% / ERA+ 20%. Minimums: "
    f"{db.MVP_MIN_PA}+ PA for MVP, {db.CY_YOUNG_MIN_IP}+ IP for Cy Young."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
seasons = db.get_seasons("batting")
season = st.selectbox("Season", seasons, index=0)


def _mvp_table(league: str):
    race = db.mvp_race(season, league, mtime)
    if race.empty:
        st.caption(f"Not enough qualifying batters for {league} MVP this season.")
        return
    display = teams.add_team_abbr(race.head(5))
    cols = ["Name", "Tm", "WAR", "wRC_plus", "baserunning_runs", "OAA", "MVP Score"]
    display = display[cols].rename(columns={"wRC_plus": "wRC+", "baserunning_runs": "BsR"})
    st.dataframe(
        style.style_stats_table(
            display, team_col="Tm", team_color_fn=teams.color_for_abbr,
            higher_better=["WAR", "wRC+", "BsR", "OAA", "MVP Score"],
            precision={"WAR": "{:.1f}", "wRC+": "{:.0f}", "BsR": "{:+.1f}", "OAA": "{:+.0f}", "MVP Score": "{:.2f}"},
        ),
        use_container_width=True, hide_index=True,
    )


def _cy_young_table(league: str):
    race = db.cy_young_race(season, league, mtime)
    if race.empty:
        st.caption(f"Not enough qualifying pitchers for {league} Cy Young this season.")
        return
    display = teams.add_team_abbr(race.head(5))
    cols = ["Name", "Tm", "WAR", "FIP", "ERA_plus", "IP", "Cy Young Score"]
    display = display[cols].rename(columns={"ERA_plus": "ERA+"})
    st.dataframe(
        style.style_stats_table(
            display, team_col="Tm", team_color_fn=teams.color_for_abbr,
            higher_better=["WAR", "ERA+", "Cy Young Score"], lower_better=["FIP"],
            precision={"WAR": "{:.1f}", "FIP": "{:.2f}", "ERA+": "{:.0f}", "IP": "{:.1f}", "Cy Young Score": "{:.2f}"},
        ),
        use_container_width=True, hide_index=True,
    )


style.colored_header("MVP", "batting")
al_col, nl_col = st.columns(2)
with al_col:
    st.markdown("**AL**")
    _mvp_table("Maj-AL")
with nl_col:
    st.markdown("**NL**")
    _mvp_table("Maj-NL")

style.colored_header("Cy Young", "pitching")
al_col2, nl_col2 = st.columns(2)
with al_col2:
    st.markdown("**AL**")
    _cy_young_table("Maj-AL")
with nl_col2:
    st.markdown("**NL**")
    _cy_young_table("Maj-NL")
