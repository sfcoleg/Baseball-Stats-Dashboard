"""NFL Passing — quarterback leaders, tracking, and dEPA."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import boards
from nfl import db as fdb
from nfl import teams as fteams

season, season_type, players, mtime = boards.page_header("Passing")
std_tab, adv_tab, depa_tab = st.tabs(["Standard", "Tracking", "dEPA"])

with std_tab:
    style.colored_header("Passing", "pitching")
    boards.leaderboard(
        players, "passing", "passing_epa",
        [("games", "G"), ("attempts", "Att"), ("completion_pct", "Cmp%"),
         ("passing_yards", "Yds"), ("yards_per_attempt", "Y/A"), ("passing_tds", "TD"),
         ("passing_interceptions", "INT"), ("sacks_suffered", "Sacks"),
         ("passing_epa", "EPA"), ("passing_epa_per_att", "EPA/Att"), ("passing_cpoe", "CPOE")],
        {"Cmp%": "{:.1f}", "Y/A": "{:.1f}", "EPA": "{:.1f}", "EPA/Att": "{:.2f}", "CPOE": "{:.1f}"},
        f"Ranked by total passing EPA. Minimum {fdb.MIN_ATTEMPTS} attempts.",
        lower_is_better=("INT", "Sacks"),
    )

with adv_tab:
    style.colored_header("Tracking", "pitching")
    if not fdb.advanced_available(season, "ngs"):
        st.caption(f"Next Gen Stats begin in {fdb.NGS_FIRST_SEASON}.")
    else:
        boards.tracking_board(
            boards.nextgen(season, "passing", mtime), "avg_air_yards_to_sticks",
            [("Player", "Player"), ("Tm", "Tm"), ("attempts", "Att"),
             ("avg_time_to_throw", "Time to Throw"),
             ("avg_intended_air_yards", "Intended Air Yds"),
             ("avg_air_yards_to_sticks", "Air Yds to Sticks"),
             ("aggressiveness", "Aggressiveness%"),
             ("completion_percentage_above_expectation", "CPOE"),
             ("avg_completed_air_yards", "Completed Air Yds")],
            {"Att": "{:.0f}", "Time to Throw": "{:.2f}", "Intended Air Yds": "{:.1f}",
             "Air Yds to Sticks": "{:+.1f}", "Aggressiveness%": "{:.1f}",
             "CPOE": "{:+.1f}", "Completed Air Yds": "{:.1f}"},
            "Air yards to sticks is how far past the first-down marker he throws on "
            "average — negative means he is throwing short of the line to gain.",
        )

with depa_tab:
    style.colored_header("dEPA", "pitching")
    st.caption(
        f"Our own quarterback metric, and the football counterpart to this site's pitcher "
        f"dWAR. It blends this season's EPA per attempt with last season's, each weighted "
        f"by its own attempts ({int(fdb.DEPA_THIS_SEASON_WEIGHT * 100)}% this year), because "
        f"one season of quarterback play is a small sample and last year still knows "
        f"something this year's number alone does not. Minimum {fdb.DEPA_MIN_ATTEMPTS} attempts."
    )
    depa = fdb.quarterback_depa(season, mtime)
    if depa.empty:
        st.caption("Not enough qualifying quarterbacks for this season.")
    else:
        board = depa.head(boards.TOP_N)
        display = pd.DataFrame({
            "Player": board["player_display_name"], "Tm": board["team"],
            "Att": board["attempts"], "EPA/Att": board["epa_att"], "dEPA": board["dEPA"],
        })
        # A quarterback with no prior season is shown on this year alone, which
        # is worth flagging rather than hiding.
        display["Basis"] = board["has_prior_season"].map(
            {True: "2 seasons", False: "this season only"})
        st.dataframe(
            style.style_stats_table(
                display, team_col="Tm", team_color_fn=fteams.color_for_abbr,
                higher_better=["EPA/Att", "dEPA"],
                precision={"Att": "{:.0f}", "EPA/Att": "{:+.3f}", "dEPA": "{:+.3f}"},
            ),
            use_container_width=True, hide_index=True, height=520,
        )
        st.caption(
            "Validated the way pitcher dWAR was: across paired quarterback seasons, dEPA "
            "predicts the following season's EPA per attempt at r=+0.414, against +0.381 "
            "for this season's EPA alone and +0.346 for passer rating."
        )
