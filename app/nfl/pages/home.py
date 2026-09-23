"""NFL Home — where the season is right now: this week's games and the
current standings picture at a glance."""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import db as fdb
from nfl import style as fstyle
from nfl import teams as fteams


def _live_score_bar(g: dict, live: dict):
    """A small horizontal stacked bar for one live game: away score vs home
    score, each segment colored by that team's own color. This is a live
    score visualization, not a prediction — there's no NFL win-probability
    model on this site (unlike MLB's Log5-based one), so we don't fake one."""
    away, home = g["away_team"], g["home_team"]
    away_score = live.get("away_score") or 0
    home_score = live.get("home_score") or 0
    total = away_score + home_score
    if total <= 0:
        return  # nothing to show yet (0-0)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=["Score"], x=[away_score], name=away, orientation="h",
        marker_color=fteams.color_for_abbr(away),
        text=f"{away} {away_score}", textposition="inside", insidetextanchor="start",
        hoverinfo="skip",
    ))
    fig.add_trace(go.Bar(
        y=["Score"], x=[home_score], name=home, orientation="h",
        marker_color=fteams.color_for_abbr(home),
        text=f"{home_score} {home}", textposition="inside", insidetextanchor="end",
        hoverinfo="skip",
    ))
    fig.update_layout(
        barmode="stack", showlegend=False, height=54,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color=fstyle.CHART_TEXT,
        xaxis=dict(visible=False, range=[0, total]),
        yaxis=dict(visible=False),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False},
                     key=f"live_bar_{away}_{home}")

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

        # Live games get a small current-score bar right below the grid —
        # a plain visual of the score margin, not a prediction (there's no
        # win-probability model for NFL on this site). Lives inside the
        # same 30s-refresh fragment as the grid so the bar tracks the score.
        live_games = [
            (g, live_by_matchup.get((g["away_team"], g["home_team"])))
            for _, g in this_week.iterrows()
            if (live_by_matchup.get((g["away_team"], g["home_team"])) or {}).get("state") == "in"
        ]
        if live_games:
            st.caption("Live score margin")
            lcols = st.columns(min(len(live_games), 3))
            for i, (g, live) in enumerate(live_games):
                with lcols[i % len(lcols)]:
                    _live_score_bar(g, live)

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
