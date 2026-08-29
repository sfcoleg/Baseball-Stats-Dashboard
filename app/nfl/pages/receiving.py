"""NFL Receiving — leaders, separation and yards after catch."""
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import boards
from nfl import db as fdb

season, season_type, players, mtime = boards.page_header("Receiving")
std_tab, adv_tab = st.tabs(["Standard", "Separation & YAC"])

with std_tab:
    style.colored_header("Receiving", "headliners")
    boards.leaderboard(
        players, "receiving", "receiving_yards",
        [("games", "G"), ("targets", "Tgt"), ("receptions", "Rec"),
         ("receiving_yards", "Yds"), ("yards_per_reception", "Y/R"),
         ("receiving_tds", "TD"), ("receiving_yards_after_catch", "YAC"),
         ("receiving_epa", "EPA"), ("receiving_epa_per_target", "EPA/Tgt")],
        {"Y/R": "{:.1f}", "EPA": "{:.1f}", "EPA/Tgt": "{:.2f}"},
        f"Ranked by receiving yards. Minimum {fdb.MIN_TARGETS} targets.",
    )

with adv_tab:
    style.colored_header("Separation & YAC", "headliners")
    if not fdb.advanced_available(season, "ngs"):
        st.caption(f"Next Gen Stats begin in {fdb.NGS_FIRST_SEASON}.")
    else:
        boards.tracking_board(
            boards.nextgen(season, "receiving", mtime), "avg_yac_above_expectation",
            [("Player", "Player"), ("Tm", "Tm"), ("targets", "Tgt"),
             ("receptions", "Rec"), ("avg_separation", "Separation"),
             ("avg_cushion", "Cushion"), ("avg_intended_air_yards", "aDOT"),
             ("avg_yac", "YAC"), ("avg_expected_yac", "Expected YAC"),
             ("avg_yac_above_expectation", "YAC +/-")],
            {"Tgt": "{:.0f}", "Rec": "{:.0f}", "Separation": "{:.2f}", "Cushion": "{:.2f}",
             "aDOT": "{:.1f}", "YAC": "{:.1f}", "Expected YAC": "{:.1f}", "YAC +/-": "{:+.2f}"},
            "Separation is yards from the nearest defender at the catch; YAC +/- is yards "
            "after catch against what the situation was worth.",
        )
