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
    "A stats-only composite score, not real award-voting data. MVP spans both batters and "
    "pitchers: batters score WAR 50% / wRC+ 25% / BsR 12.5% / OAA 12.5%; a two-way player (e.g. "
    "Ohtani) is one combined row with their batting + pitching WAR added together, scored the same "
    "batter formula; every other pitcher scores on WAR alone at half weight — a discount reflecting "
    "that real MVP voting rarely puts even a great pitcher in the top 5. Cy Young (pitchers only) "
    "weights WAR 50% / FIP 30% / ERA+ 20%, with FIP/ERA+ scaled down for pitchers with fewer "
    "innings so a short relief sample can't out-rank a full-workload starter by rate stats alone. "
    "Rookie of the Year uses the same two formulas restricted to players who pass MLB's AB/IP "
    "rookie-eligibility rule — fewer than 130 career AB and fewer than 50 career IP in the majors "
    "before this season (the 45-days-on-active-roster part of the real rule isn't tracked here, so "
    "a small number of players may show as eligible when they weren't). Minimums: "
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
            higher_better=["WAR", "MVP Score"],
            precision={"WAR": "{:.1f}", "MVP Score": "{:.2f}"},
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
            higher_better=["WAR", "ROY Score"],
            precision={"WAR": "{:.1f}", "ROY Score": "{:.2f}"},
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

style.colored_header("Rookie of the Year", "fielding")
al_col3, nl_col3 = st.columns(2)
with al_col3:
    st.markdown("**AL**")
    _roy_table("Maj-AL")
with nl_col3:
    st.markdown("**NL**")
    _roy_table("Maj-NL")
