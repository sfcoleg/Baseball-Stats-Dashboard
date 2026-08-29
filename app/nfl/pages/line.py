"""NFL Offensive Line — a UNIT page, deliberately.

There is no per-lineman performance data here and no honest way to invent
one: individual blocking grades are PFF's product and are not public. So
this measures what the five of them produce together — how often the
quarterback was pressured behind them, and how far backs ran before anyone
touched them. Attributing that to the group is not a compromise; it is what
the numbers actually describe."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import db as fdb
from nfl import teams as fteams

st.set_page_config(page_title="NFL Offensive Line | Diamond Metrics", layout="wide")
st.title("Offensive Line")
st.caption(
    "Unit-level, not per player. Individual blocking grades aren't public, so these "
    "measure what the line produces as a group."
)

mtime = fdb.nfl_db_mtime()
season_list = fdb.seasons(mtime)
if not season_list:
    st.info("No NFL data yet — run `python ingest/nfl_refresh.py` to build it.")
    st.stop()

season = st.selectbox("Season", season_list, index=fdb.season_index(season_list, mtime),
                      format_func=fdb.season_label)

if not fdb.advanced_available(season, "pfr"):
    st.caption(f"The data behind these begins in {fdb.PFR_FIRST_SEASON}.")
    st.stop()

# PFR gives a player who changed teams a combined "2TM" row, which is a real
# player total but not a real team — drop anything that isn't one of the 32.
REAL_TEAMS = {abbr for abbr, _ in fteams.all_teams()}


def _only_real_teams(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["team"].isin(REAL_TEAMS)] if not df.empty else df


protection = _only_real_teams(fdb.team_pass_protection(season, mtime))
blocking = _only_real_teams(fdb.team_run_blocking(season, mtime))

if protection.empty and blocking.empty:
    st.caption(f"No line data for {fdb.season_label(season)} yet.")
    st.stop()

pass_tab, run_tab = st.tabs(["Pass Protection", "Run Blocking"])

with pass_tab:
    style.colored_header("Pass Protection", "fielding")
    st.caption(
        "Ranked by pressure rate allowed — lower is better. Pressure rather than sacks "
        "allowed: a sack is the rare end of a broken protection, while pressures happen "
        "several times a game and describe the same thing with far less noise."
    )
    if protection.empty:
        st.caption("No data for this season.")
    else:
        display = pd.DataFrame({
            "Team": protection["team"],
            "Dropbacks": protection["attempts"],
            "Pressured": protection["pressured"],
            "Pressure%": protection["pressure_rate"],
            "Hurries": protection["hurries"],
            "Hits": protection["hits"],
            "Blitzed": protection["blitzed"],
            "Blitz%": protection["blitz_rate"],
        })
        st.dataframe(
            style.style_stats_table(
                display, team_col="Team", team_color_fn=fteams.color_for_abbr,
                lower_better=["Pressure%", "Pressured", "Hurries", "Hits"],
                precision={"Dropbacks": "{:.0f}", "Pressured": "{:.0f}", "Pressure%": "{:.1f}",
                           "Hurries": "{:.0f}", "Hits": "{:.0f}", "Blitzed": "{:.0f}",
                           "Blitz%": "{:.1f}"},
            ),
            use_container_width=True, hide_index=True, height=560,
        )

with run_tab:
    style.colored_header("Run Blocking", "batting")
    st.caption(
        "Ranked by yards before contact per carry. Yards gained before any defender "
        "touched the back are the ones the line gave him; yards after contact are the "
        "ones he took himself — which is why the two are split here rather than summed."
    )
    if blocking.empty:
        st.caption("No data for this season.")
    else:
        display = pd.DataFrame({
            "Team": blocking["team"],
            "Carries": blocking["carries"],
            "Yds/Carry": blocking["yards_per_carry"],
            "Before Contact": blocking["ybc_per_carry"],
            "After Contact": blocking["yac_per_carry"],
            "Broken Tackles": blocking["broken_tackles"],
        })
        st.dataframe(
            style.style_stats_table(
                display, team_col="Team", team_color_fn=fteams.color_for_abbr,
                higher_better=["Yds/Carry", "Before Contact", "After Contact", "Broken Tackles"],
                precision={"Carries": "{:.0f}", "Yds/Carry": "{:.2f}",
                           "Before Contact": "{:.2f}", "After Contact": "{:.2f}",
                           "Broken Tackles": "{:.0f}"},
            ),
            use_container_width=True, hide_index=True, height=560,
        )
