"""NFL Standings — by division, which is how the league is actually
organised and how playoff seeding is decided."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import db as fdb
from nfl import teams as fteams

st.set_page_config(page_title="NFL Standings | Diamond Metrics", layout="wide")
st.title("Standings")

mtime = fdb.nfl_db_mtime()
season_list = fdb.seasons(mtime)
if not season_list:
    st.info("No NFL data yet — run `python ingest/nfl_refresh.py` to build it.")
    st.stop()

season = st.selectbox("Season", season_list, index=fdb.season_index(season_list, mtime),
                       format_func=fdb.season_label)
standings = fdb.load_standings(season, mtime)
if standings.empty:
    st.caption(f"No games played yet in {fdb.season_label(season)}.")
    st.stop()

for conf in ("AFC", "NFC"):
    conf_rows = standings[standings["team_conf"] == conf]
    if conf_rows.empty:
        continue
    style.colored_header(conf, "batting")
    divisions = sorted(conf_rows["team_division"].dropna().unique())
    cols = st.columns(2)
    for i, division in enumerate(divisions):
        div_rows = conf_rows[conf_rows["team_division"] == division].sort_values(
            ["win_pct", "point_diff"], ascending=False
        )
        with cols[i % 2]:
            st.markdown(f"**{division}**")
            display = pd.DataFrame({
                "Team": div_rows["team"],
                "W": div_rows["wins"].astype(int),
                "L": div_rows["losses"].astype(int),
                "T": div_rows["ties"].astype(int),
                "PCT": div_rows["win_pct"],
                "PF": div_rows["points_for"].astype(int),
                "PA": div_rows["points_against"].astype(int),
                "DIFF": div_rows["point_diff"].astype(int),
                "DIV": div_rows["div_wins"].astype(int).astype(str) + "-" + div_rows["div_losses"].astype(int).astype(str),
            })
            st.dataframe(
                style.style_stats_table(
                    display, team_col="Team", team_color_fn=fteams.color_for_abbr,
                    higher_better=["W", "PCT", "PF", "DIFF"], lower_better=["L", "PA"],
                    precision={"PCT": "{:.3f}"},
                ),
                use_container_width=True, hide_index=True,
            )
