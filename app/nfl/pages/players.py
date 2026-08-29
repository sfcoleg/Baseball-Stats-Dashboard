"""NFL Players — passing, rushing and receiving leaders.

Rate columns sit next to volume ones on purpose: yards tell you who got the
most opportunity, EPA per play tells you who did the most with it, and the
two disagreeing is usually the interesting part."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import db as fdb
from nfl import teams as fteams

st.set_page_config(page_title="NFL Players | Diamond Metrics", layout="wide")
st.title("Players")

mtime = fdb.nfl_db_mtime()
season_list = fdb.seasons(mtime)
if not season_list:
    st.info("No NFL data yet — run `python ingest/nfl_refresh.py` to build it.")
    st.stop()

c1, c2 = st.columns(2)
season = c1.selectbox("Season", season_list, index=fdb.season_index(season_list, mtime),
                      format_func=fdb.season_label)
season_type = c2.selectbox(
    "Games", ["REG", "POST"],
    format_func=lambda t: "Regular season" if t == "REG" else "Playoffs",
)

players = fdb.load_player_seasons(season, mtime, season_type)
if players.empty:
    st.caption(f"No player data for {fdb.season_label(season)} yet.")
    st.stop()


def _leaderboard(kind: str, sort_col: str, columns: list[tuple[str, str]], precision: dict, minimum_note: str):
    pool = fdb.qualified(players, kind)
    if pool.empty or sort_col not in pool.columns:
        st.caption("Not enough qualifying players for this season.")
        return
    top = pool.sort_values(sort_col, ascending=False).head(25).copy()
    display = pd.DataFrame({"Player": top["player_display_name"], "Tm": top["team"]})
    for src, label in columns:
        if src in top.columns:
            display[label] = top[src]
    st.caption(minimum_note)
    st.dataframe(
        style.style_stats_table(
            display, team_col="Tm", team_color_fn=fteams.color_for_abbr,
            higher_better=[label for _, label in columns if label not in ("INT", "Sacks")],
            lower_better=[label for _, label in columns if label in ("INT", "Sacks")],
            precision=precision,
        ),
        use_container_width=True, hide_index=True, height=520,
    )


def _advanced(frame, sort_col, columns, precision, note, ascending=False, minimum=None):
    """Leaderboard over a Next Gen Stats or PFR frame.

    These arrive already aggregated to the season by their own source, so
    unlike the boards above there is nothing to sum — the work is picking the
    columns worth showing and giving the sort a sensible qualifying floor."""
    if frame is None or frame.empty or sort_col not in frame.columns:
        st.caption("No data for this season.")
        return
    pool = frame
    if minimum:
        col, floor = minimum
        if col in pool.columns:
            pool = pool[pd.to_numeric(pool[col], errors="coerce").fillna(0) >= floor]
    if pool.empty:
        st.caption("No qualifying players for this season.")
        return
    top = pool.sort_values(sort_col, ascending=ascending).head(25)
    display = pd.DataFrame()
    for src, label in columns:
        if src in top.columns:
            display[label] = top[src]
    st.caption(note)
    st.dataframe(
        style.style_stats_table(
            display, team_col="Tm" if "Tm" in display.columns else None,
            team_color_fn=fteams.color_for_abbr,
            precision=precision,
        ),
        use_container_width=True, hide_index=True, height=520,
    )


pass_tab, rush_tab, rec_tab, adv_tab = st.tabs(
    ["Passing", "Rushing", "Receiving", "Advanced"]
)

with pass_tab:
    style.colored_header("Passing", "pitching")
    _leaderboard(
        "passing", "passing_epa",
        [("games", "G"), ("attempts", "Att"), ("completion_pct", "Cmp%"),
         ("passing_yards", "Yds"), ("yards_per_attempt", "Y/A"), ("passing_tds", "TD"),
         ("passing_interceptions", "INT"), ("sacks_suffered", "Sacks"),
         ("passing_epa", "EPA"), ("passing_epa_per_att", "EPA/Att"), ("passing_cpoe", "CPOE")],
        {"Cmp%": "{:.1f}", "Y/A": "{:.1f}", "EPA": "{:.1f}", "EPA/Att": "{:.2f}", "CPOE": "{:.1f}"},
        f"Ranked by total passing EPA. Minimum {fdb.MIN_ATTEMPTS} attempts.",
    )

with rush_tab:
    style.colored_header("Rushing", "batting")
    _leaderboard(
        "rushing", "rushing_yards",
        [("games", "G"), ("carries", "Att"), ("rushing_yards", "Yds"),
         ("yards_per_carry", "Y/C"), ("rushing_tds", "TD"),
         ("rushing_first_downs", "1D"), ("rushing_epa", "EPA"),
         ("rushing_epa_per_carry", "EPA/Att")],
        {"Y/C": "{:.1f}", "EPA": "{:.1f}", "EPA/Att": "{:.2f}"},
        f"Ranked by rushing yards. Minimum {fdb.MIN_CARRIES} carries.",
    )

with rec_tab:
    style.colored_header("Receiving", "headliners")
    _leaderboard(
        "receiving", "receiving_yards",
        [("games", "G"), ("targets", "Tgt"), ("receptions", "Rec"),
         ("receiving_yards", "Yds"), ("yards_per_reception", "Y/R"),
         ("receiving_tds", "TD"), ("receiving_yards_after_catch", "YAC"),
         ("receiving_epa", "EPA"), ("receiving_epa_per_target", "EPA/Tgt")],
        {"Y/R": "{:.1f}", "EPA": "{:.1f}", "EPA/Tgt": "{:.2f}"},
        f"Ranked by receiving yards. Minimum {fdb.MIN_TARGETS} targets.",
    )


with adv_tab:
    # Next Gen Stats is player tracking — where the ball and the players
    # actually were — so it answers questions the box score cannot: how long
    # a quarterback held it, how open a receiver got, how much a back gained
    # beyond what the blocking gave him.
    if not fdb.advanced_available(season, "ngs"):
        st.caption(f"Next Gen Stats begin in {fdb.NGS_FIRST_SEASON}.")
    else:
        qb_tab, rb_tab, wr_tab = st.tabs(["Quarterbacks", "Rushers", "Receivers"])

        with qb_tab:
            style.colored_header("Quarterback Tracking", "pitching")
            ngs = fdb.load_nextgen(season, "passing", mtime)
            if not ngs.empty:
                ngs = ngs.rename(columns={"player_display_name": "Player", "team_abbr": "Tm"})
            _advanced(
                ngs, "avg_air_yards_to_sticks",
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

        with rb_tab:
            style.colored_header("Rushing Over Expected", "batting")
            ngs = fdb.load_nextgen(season, "rushing", mtime)
            if not ngs.empty:
                ngs = ngs.rename(columns={"player_display_name": "Player", "team_abbr": "Tm"})
            _advanced(
                ngs, "rush_yards_over_expected",
                [("Player", "Player"), ("Tm", "Tm"), ("rush_attempts", "Att"),
                 ("rush_yards", "Yds"), ("expected_rush_yards", "Expected"),
                 ("rush_yards_over_expected", "RYOE"),
                 ("rush_yards_over_expected_per_att", "RYOE/Att"),
                 ("percent_attempts_gte_eight_defenders", "8+ Box%"),
                 ("avg_time_to_los", "Time to LOS")],
                {"Att": "{:.0f}", "Yds": "{:.0f}", "Expected": "{:.0f}",
                 "RYOE": "{:+.0f}", "RYOE/Att": "{:+.2f}",
                 "8+ Box%": "{:.1f}", "Time to LOS": "{:.2f}"},
                "Rush yards over expected: what he gained against what a league-average "
                "back would have, given the blocking and the defenders in the box.",
            )

        with wr_tab:
            style.colored_header("Separation & YAC", "headliners")
            ngs = fdb.load_nextgen(season, "receiving", mtime)
            if not ngs.empty:
                ngs = ngs.rename(columns={"player_display_name": "Player", "team_abbr": "Tm"})
            _advanced(
                ngs, "avg_yac_above_expectation",
                [("Player", "Player"), ("Tm", "Tm"), ("targets", "Tgt"),
                 ("receptions", "Rec"), ("avg_separation", "Separation"),
                 ("avg_cushion", "Cushion"), ("avg_intended_air_yards", "aDOT"),
                 ("avg_yac", "YAC"), ("avg_expected_yac", "Expected YAC"),
                 ("avg_yac_above_expectation", "YAC +/-")],
                {"Tgt": "{:.0f}", "Rec": "{:.0f}", "Separation": "{:.2f}",
                 "Cushion": "{:.2f}", "aDOT": "{:.1f}",
                 "YAC": "{:.1f}", "Expected YAC": "{:.1f}", "YAC +/-": "{:+.2f}"},
                "Separation is yards from the nearest defender at the catch; YAC +/- is "
                "yards after catch against what the situation was worth.",
            )
