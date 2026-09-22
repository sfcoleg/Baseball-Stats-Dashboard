"""NBA Player Stats — every qualifying player's season line, filterable and
sortable, per-game rates rather than the raw totals nba_api returns
(confirmed directly: Dončić's 2025-26 row carries 2143 total points, not
33.5 per game — the per-game columns are computed in ingest/nba_refresh.py,
not assumed to already exist). Same shape as the NHL Skaters page: a team
filter, a minimum-games slider and a sort-by picker over the full pool,
rather than a fixed Top 25 per category."""
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

STAT_LABELS = {
    "PLAYER_NAME": "Player", "TEAM_ABBREVIATION": "Tm", "AGE": "Age", "GP": "GP",
    "MIN_PG": "MPG", "PTS_PG": "PPG", "REB_PG": "RPG", "AST_PG": "APG",
    "STL_PG": "SPG", "BLK_PG": "BPG", "TOV_PG": "TOV", "PLUS_MINUS": "+/-",
    "FGM": "FGM", "FGA": "FGA", "FG_PCT": "FG%", "FG3M": "3PM", "FG3A": "3PA",
    "FG3_PCT": "3P%", "FTM": "FTM", "FTA": "FTA", "FT_PCT": "FT%",
}

c1, c2, c3 = st.columns(3)
with c1:
    team = st.selectbox("Team", ["All"] + sorted(players["TEAM_ABBREVIATION"].dropna().unique().tolist()))
with c2:
    min_gp = st.slider("Minimum GP", 0, int(players["GP"].max()), ndb.MIN_GAMES)
with c3:
    sort_options = ["PTS_PG", "REB_PG", "AST_PG", "STL_PG", "BLK_PG", "FG_PCT", "FG3_PCT", "FT_PCT"]
    sort_by = st.selectbox("Sort by", sort_options, format_func=lambda c: STAT_LABELS.get(c, c))

filtered = players[players["GP"] >= min_gp]
if team != "All":
    filtered = filtered[filtered["TEAM_ABBREVIATION"] == team]
filtered = filtered.sort_values(sort_by, ascending=False).reset_index(drop=True)
st.caption(f"{len(filtered)} of {len(players)} players match filters.")


def _table(cols, higher_better=(), lower_better=(), precision=None, height=600):
    present = [c for c in cols if c in filtered.columns]
    display = filtered[present].rename(columns=STAT_LABELS)
    st.dataframe(
        style.style_stats_table(
            display,
            higher_better=[STAT_LABELS.get(c, c) for c in higher_better if c in present],
            lower_better=[STAT_LABELS.get(c, c) for c in lower_better if c in present],
            team_col="Tm", team_color_fn=nteams.color_for_abbr,
            precision={STAT_LABELS.get(k, k): v for k, v in (precision or {}).items()},
        ),
        use_container_width=True, height=height, hide_index=True,
    )


scoring_tab, playmaking_tab, shooting_tab = st.tabs(["Scoring", "Playmaking & Defense", "Shooting"])

with scoring_tab:
    style.colored_header("Scoring", "batting")
    _table(
        ["PLAYER_NAME", "TEAM_ABBREVIATION", "AGE", "GP", "MIN_PG", "PTS_PG", "REB_PG", "AST_PG", "PLUS_MINUS"],
        higher_better=["PTS_PG", "REB_PG", "AST_PG", "PLUS_MINUS"],
        precision={"MIN_PG": "{:.1f}", "PTS_PG": "{:.1f}", "REB_PG": "{:.1f}", "AST_PG": "{:.1f}",
                   "PLUS_MINUS": "{:+.0f}"},
    )

with playmaking_tab:
    style.colored_header("Playmaking & Defense", "batting")
    _table(
        ["PLAYER_NAME", "TEAM_ABBREVIATION", "GP", "AST_PG", "STL_PG", "BLK_PG", "TOV_PG"],
        higher_better=["AST_PG", "STL_PG", "BLK_PG"],
        lower_better=["TOV_PG"],
        precision={"AST_PG": "{:.1f}", "STL_PG": "{:.1f}", "BLK_PG": "{:.1f}", "TOV_PG": "{:.1f}"},
    )

with shooting_tab:
    style.colored_header("Shooting", "batting")
    _table(
        ["PLAYER_NAME", "TEAM_ABBREVIATION", "GP", "FGM", "FGA", "FG_PCT", "FG3M", "FG3A", "FG3_PCT", "FTM", "FTA", "FT_PCT"],
        higher_better=["FG_PCT", "FG3_PCT", "FT_PCT"],
        precision={"FG_PCT": "{:.3f}", "FG3_PCT": "{:.3f}", "FT_PCT": "{:.3f}"},
    )
