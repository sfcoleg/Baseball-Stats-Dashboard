"""NBA Player Stats — season leaders, per-game rates rather than the raw
totals nba_api returns (confirmed directly: Dončić's 2025-26 row carries
2143 total points, not 33.5 per game — the per-game columns are computed
in ingest/nba_refresh.py, not assumed to already exist)."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nba import db as ndb
from nba import teams as nteams

st.set_page_config(page_title="NBA Player Stats | Diamond Metrics", layout="wide")
st.title("Player Stats")

mtime = ndb.nba_db_mtime()
players = ndb.load_player_stats(mtime)
if players.empty:
    st.info("No NBA player data yet — run `python ingest/nba_refresh.py` to build it.")
    st.stop()

season = ndb.player_stats_season(mtime)
st.caption(f"{season} season" + (" — the most recently completed one; 2026-27 hasn't tipped off yet."
                                 if season and season != ndb.current_season_label() else "."))

pool = ndb.qualified_players(players)
if pool.empty:
    st.caption("Not enough qualifying players yet.")
    st.stop()

TOP_N = 25


def _board(sort_col, columns, precision, note, lower_is_better=()):
    if sort_col not in pool.columns:
        st.caption("Not available for this season.")
        return
    top = pool.sort_values(sort_col, ascending=False).head(TOP_N)
    display = pd.DataFrame({"Player": top["PLAYER_NAME"], "Tm": top["TEAM_ABBREVIATION"]})
    for src, label in columns:
        if src in top.columns:
            display[label] = top[src]
    st.caption(note)
    st.dataframe(
        style.style_stats_table(
            display, team_col="Tm", team_color_fn=nteams.color_for_abbr,
            higher_better=[l for _, l in columns if l not in lower_is_better],
            lower_better=[l for _, l in columns if l in lower_is_better],
            precision=precision,
        ),
        use_container_width=True, hide_index=True, height=560,
    )


scoring_tab, playmaking_tab, shooting_tab = st.tabs(["Scoring", "Playmaking & Defense", "Shooting"])

with scoring_tab:
    style.colored_header("Scoring", "batting")
    _board(
        "PTS_PG",
        [("GP", "GP"), ("MIN_PG", "MPG"), ("PTS_PG", "PPG"), ("REB_PG", "RPG"), ("AST_PG", "APG")],
        {"MPG": "{:.1f}", "PPG": "{:.1f}", "RPG": "{:.1f}", "APG": "{:.1f}"},
        f"Ranked by points per game. Minimum {ndb.MIN_GAMES} games played.",
    )

with playmaking_tab:
    style.colored_header("Playmaking & Defense", "batting")
    _board(
        "AST_PG",
        [("GP", "GP"), ("AST_PG", "APG"), ("STL_PG", "SPG"), ("BLK_PG", "BPG"), ("TOV_PG", "TOV")],
        {"APG": "{:.1f}", "SPG": "{:.1f}", "BPG": "{:.1f}", "TOV": "{:.1f}"},
        f"Ranked by assists per game. Minimum {ndb.MIN_GAMES} games played.",
        lower_is_better=("TOV",),
    )

with shooting_tab:
    style.colored_header("Shooting", "batting")
    _board(
        "FG_PCT",
        [("GP", "GP"), ("FGM", "FGM"), ("FGA", "FGA"), ("FG_PCT", "FG%"),
         ("FG3_PCT", "3P%"), ("FT_PCT", "FT%")],
        {"FG%": "{:.3f}", "3P%": "{:.3f}", "FT%": "{:.3f}"},
        f"Ranked by field-goal percentage. Minimum {ndb.MIN_GAMES} games played — season totals, "
        "not per-game.",
    )
