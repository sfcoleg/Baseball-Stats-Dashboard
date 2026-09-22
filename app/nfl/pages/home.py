"""NFL Home — where the season is right now: this week's games and the
current standings picture at a glance."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import db as fdb
from nfl import style as fstyle
from nfl import teams as fteams

st.set_page_config(page_title="NFL | Diamond Metrics", layout="wide")
st.title("NFL")

mtime = fdb.nfl_db_mtime()
season_list = fdb.seasons(mtime)
if not season_list:
    st.info("No NFL data yet — run `python ingest/nfl_refresh.py` to build it.")
    st.stop()

season = st.selectbox("Season", season_list, index=fdb.season_index(season_list, mtime),
                       format_func=fdb.season_label)
games = fdb.load_games(season, mtime)
standings = fdb.load_standings(season, mtime)

# --- Last game --------------------------------------------------------------
# Not scoped to the selected season: this answers "what was the last football
# played", which through the offseason is last February's Super Bowl.
_last = fdb.last_completed_game(mtime)
if _last is not None:
    style.colored_header("Last Game", "headliners")
    st.markdown(fstyle.LAST_GAME_CSS, unsafe_allow_html=True)
    st.markdown(
        fstyle.last_game_card(_last, fdb.game_round_label(_last), fteams),
        unsafe_allow_html=True,
    )

week = fdb.current_week(games)
if week is not None:
    this_week = games[games["week"] == week]
    game_type = this_week.iloc[0]["game_type"] if not this_week.empty else "REG"
    label = fdb.GAME_TYPE_LABELS.get(game_type, "")
    style.colored_header(f"Week {week}" + (f" · {label}" if label and label != "Regular season" else ""), "headliners")
    st.markdown(fstyle.WEEK_GAMES_CSS, unsafe_allow_html=True)

    # A fragment so live scores can auto-refresh through the afternoon
    # without losing the season/selectbox state above — same idiom as the
    # MLB Today's Games page. Only regular-season weeks get the live fetch:
    # ESPN's `week` numbering for the playoffs doesn't line up with
    # nflverse's, so a postseason week would match the wrong games.
    @st.fragment(run_every="30s")
    def _week_grid():
        fdb.load_live_scores.clear()
        live_by_matchup = fdb.load_live_scores(season, week) if game_type == "REG" else {}
        cards = "".join(
            fstyle.week_game_card(g, live_by_matchup.get((g["away_team"], g["home_team"])), fteams)
            for _, g in this_week.iterrows()
        )
        st.markdown(f"<div class='wk-grid'>{cards}</div>", unsafe_allow_html=True)

    _week_grid()

# --- Standings snapshot -----------------------------------------------------
if not standings.empty:
    style.colored_header("Standings", "batting")
    for conf in ("AFC", "NFC"):
        conf_rows = standings[standings["team_conf"] == conf]
        if conf_rows.empty:
            continue
        st.markdown(f"**{conf}**")
        display = pd.DataFrame({
            "Team": conf_rows["team"],
            "Division": conf_rows["team_division"].str.replace(f"{conf} ", "", regex=False),
            "W": conf_rows["wins"].astype(int),
            "L": conf_rows["losses"].astype(int),
            "T": conf_rows["ties"].astype(int),
            "PCT": conf_rows["win_pct"],
            "PF": conf_rows["points_for"].astype(int),
            "PA": conf_rows["points_against"].astype(int),
            "DIFF": conf_rows["point_diff"].astype(int),
        })
        st.dataframe(
            style.style_stats_table(
                display, team_col="Team", team_color_fn=fteams.color_for_abbr,
                higher_better=["W", "PCT", "PF", "DIFF"], lower_better=["L", "PA"],
                precision={"PCT": "{:.3f}"},
            ),
            use_container_width=True, hide_index=True, height=560,
        )
else:
    style.colored_header("Standings", "batting")
    st.caption(
        f"No games played yet in {fdb.season_label(season)} — standings appear once the season starts."
    )
