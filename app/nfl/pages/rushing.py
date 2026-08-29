"""NFL Rushing — leaders and yards over expected."""
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import boards
from nfl import db as fdb

season, season_type, players, mtime = boards.page_header("Rushing")
std_tab, adv_tab = st.tabs(["Standard", "Over Expected"])

with std_tab:
    style.colored_header("Rushing", "batting")
    boards.leaderboard(
        players, "rushing", "rushing_yards",
        [("games", "G"), ("carries", "Att"), ("rushing_yards", "Yds"),
         ("yards_per_carry", "Y/C"), ("rushing_tds", "TD"),
         ("rushing_first_downs", "1D"), ("rushing_epa", "EPA"),
         ("rushing_epa_per_carry", "EPA/Att")],
        {"Y/C": "{:.1f}", "EPA": "{:.1f}", "EPA/Att": "{:.2f}"},
        f"Ranked by rushing yards. Minimum {fdb.MIN_CARRIES} carries.",
    )

with adv_tab:
    style.colored_header("Over Expected", "batting")
    if not fdb.advanced_available(season, "ngs"):
        st.caption(f"Next Gen Stats begin in {fdb.NGS_FIRST_SEASON}.")
    else:
        boards.tracking_board(
            boards.nextgen(season, "rushing", mtime), "rush_yards_over_expected",
            [("Player", "Player"), ("Tm", "Tm"), ("rush_attempts", "Att"),
             ("rush_yards", "Yds"), ("expected_rush_yards", "Expected"),
             ("rush_yards_over_expected", "RYOE"),
             ("rush_yards_over_expected_per_att", "RYOE/Att"),
             ("percent_attempts_gte_eight_defenders", "8+ Box%"),
             ("avg_time_to_los", "Time to LOS")],
            {"Att": "{:.0f}", "Yds": "{:.0f}", "Expected": "{:.0f}", "RYOE": "{:+.0f}",
             "RYOE/Att": "{:+.2f}", "8+ Box%": "{:.1f}", "Time to LOS": "{:.2f}"},
            "Rush yards over expected: what he gained against what a league-average back "
            "would have, given the blocking and the defenders in the box.",
        )
