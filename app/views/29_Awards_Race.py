"""Awards Race — MVP, Cy Young and Rookie of the Year composites for
both leagues. Split out of the old combined Around the League page."""
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import prefs
import style
import teams

st.set_page_config(page_title="Awards Race | Diamond Metrics", layout="wide")
st.title("Awards Race")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()

seasons = db.get_seasons("batting")
season = st.selectbox("Season", seasons, index=prefs.default_season_index(seasons))

def _mvp_table(league: str):
    race = db.mvp_race(season, league, mtime)
    if race.empty:
        st.caption(f"Not enough qualifying batters or pitchers for {league} MVP this season.")
        return
    display = teams.add_team_abbr(race.head(5))
    # Batters and pitchers are scored differently (see mvp_race), so a
    # shared wRC+/BsR/OAA column would be blank for every pitcher row —
    # Streamlit's dataframe grid renders those blanks as the literal text
    # "None" rather than the Styler's na_rep, so those columns are left out
    # of this combined view entirely. Role + WAR + MVP Score is enough to
    # see why each candidate ranks where they do; the batting-only detail
    # is still on that player's own page.
    cols = ["Name", "Tm", "Role", "WAR", "MVP Score"]
    display = display[cols]
    st.dataframe(
        style.style_stats_table(
            display, team_col="Tm", team_color_fn=teams.color_for_abbr,
            precision={"WAR": "{:.1f}", "MVP Score": "{:.2f}"},
        ),
        use_container_width=True, hide_index=True,
    )
    st.caption("WAR is dWAR for pitchers and bWAR for batters — the two are ranked together here.")

def _cy_young_table(league: str):
    race = db.cy_young_race(season, league, mtime)
    if race.empty:
        st.caption(f"Not enough qualifying pitchers for {league} Cy Young this season.")
        return
    display = teams.add_team_abbr(race.head(5))
    cols = ["Name", "Tm", "WAR", "FIP", "ERA_plus", "IP", "Cy Young Score"]
    display = display[cols].rename(columns={"ERA_plus": "ERA+", "WAR": "dWAR"})
    st.dataframe(
        style.style_stats_table(
            display, team_col="Tm", team_color_fn=teams.color_for_abbr,
            precision={"dWAR": "{:.1f}", "FIP": "{:.2f}", "ERA+": "{:.0f}", "IP": "{:.1f}", "Cy Young Score": "{:.2f}"},
        ),
        use_container_width=True, hide_index=True,
    )

def _roy_table(league: str):
    race = db.rookie_of_the_year_race(season, league, mtime)
    if race.empty:
        st.caption(f"Not enough rookie-eligible candidates for {league} Rookie of the Year this season.")
        return
    display = teams.add_team_abbr(race.head(5))
    cols = ["Name", "Tm", "Role", "WAR", "ROY Score"]
    st.dataframe(
        style.style_stats_table(
            display[cols], team_col="Tm", team_color_fn=teams.color_for_abbr,
            precision={"WAR": "{:.1f}", "ROY Score": "{:.2f}"},
        ),
        use_container_width=True, hide_index=True,
    )
    st.caption("WAR is dWAR for pitchers and bWAR for batters — the two are ranked together here.")

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

style.colored_header("Rookie of the Year", "fielding")
al_col3, nl_col3 = st.columns(2)
with al_col3:
    st.markdown("**AL**")
    _roy_table("Maj-AL")
with nl_col3:
    st.markdown("**NL**")
    _roy_table("Maj-NL")
