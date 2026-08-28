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


pass_tab, rush_tab, rec_tab = st.tabs(["Passing", "Rushing", "Receiving"])

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
