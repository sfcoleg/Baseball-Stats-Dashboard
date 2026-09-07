"""NBA Standings — by conference, matching how the league actually seeds
its playoffs (PlayoffRank is already conference-relative, not global)."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nba import db as ndb
from nba import teams as nteams

st.set_page_config(page_title="NBA Standings | Diamond Metrics", layout="wide")
st.title("Standings")

mtime = ndb.nba_db_mtime()
standings = ndb.load_standings(mtime)
if standings.empty:
    st.info("No NBA data yet — run `python ingest/nba_refresh.py` to build it.")
    st.stop()

if ndb.standings_are_preseason(mtime):
    st.caption(
        f"The {ndb.current_season_label()} season hasn't tipped off yet — every team "
        "is 0-0. This is the real standings table, just before any games count."
    )

abbr_map = ndb.team_abbr_map(mtime)
standings = standings.assign(Team=standings["TeamID"].map(abbr_map).fillna(standings["TeamCity"]))

for conf in sorted(standings["Conference"].dropna().unique()):
    conf_rows = standings[standings["Conference"] == conf].sort_values("PlayoffRank")
    style.colored_header(conf, "batting")
    display = pd.DataFrame({
        "Team": conf_rows["Team"],
        "W": conf_rows["WINS"].astype(int),
        "L": conf_rows["LOSSES"].astype(int),
        "Conf": conf_rows.get("ConferenceRecord", ""),
        "Div": conf_rows.get("DivisionRecord", ""),
    })
    st.dataframe(
        style.style_stats_table(
            display, team_col="Team", team_color_fn=nteams.color_for_abbr,
            higher_better=["W"], lower_better=["L"],
        ),
        use_container_width=True, hide_index=True,
    )
