"""Shared leaderboard rendering for the NFL position pages.

Passing, Rushing and Receiving are three pages with the same shape — a season
picker, a volume-and-rate board, then the tracking data behind it — so the
scaffolding lives here rather than being copied three times."""
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import style
from nfl import db as fdb
from nfl import style as fstyle
from nfl import teams as fteams

TOP_N = 25


def page_header(title: str):
    """Season and game-type pickers, shared by all three position pages.

    Returns (season, season_type, players, mtime), or stops the page when
    there is nothing to show."""
    st.set_page_config(page_title=f"NFL {title} | Diamond Metrics", layout="wide")
    st.title(title)

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
    return season, season_type, players, mtime


def leaderboard(players, kind, sort_col, columns, precision, note, lower_is_better=()):
    """Volume-and-rate board off the season totals."""
    pool = fdb.qualified(players, kind)
    if pool.empty or sort_col not in pool.columns:
        st.caption("Not enough qualifying players for this season.")
        return
    top = pool.sort_values(sort_col, ascending=False).head(TOP_N)
    display = pd.DataFrame({"Player": top["player_display_name"], "Tm": top["team"]})
    for src, label in columns:
        if src in top.columns:
            display[label] = top[src]
    st.caption(note)
    st.dataframe(
        style.style_stats_table(
            display, team_col="Tm", team_color_fn=fteams.color_for_abbr,
            higher_better=[l for _, l in columns if l not in lower_is_better],
            lower_better=[l for _, l in columns if l in lower_is_better],
            precision=precision,
        ),
        use_container_width=True, hide_index=True, height=520,
    )


def efficiency_scatter(pool, x_col, y_col, x_label, y_label, note):
    """Volume vs. efficiency for the qualified pool — one point per player,
    colored by team, labeled on hover. Placed after the leaderboard table on
    each position page (Passing/Rushing/Receiving) to show who is both a
    high-volume AND high-efficiency player, versus a compiler racking up
    volume at a below-average rate."""
    if pool.empty or x_col not in pool.columns or y_col not in pool.columns:
        return
    plot_df = pool[["player_display_name", "team", x_col, y_col]].dropna()
    if plot_df.empty:
        return
    st.caption(note)
    fig = px.scatter(
        plot_df, x=x_col, y=y_col, color="team",
        color_discrete_map={t: fteams.color_for_abbr(t) for t in plot_df["team"].unique()},
        hover_name="player_display_name",
        hover_data={x_col: True, y_col: ":.3f", "team": True},
        labels={x_col: x_label, y_col: y_label},
    )
    fig.update_traces(marker=dict(size=10, opacity=0.85, line=dict(width=1, color="rgba(255,255,255,0.4)")))
    fig.update_layout(
        showlegend=False, height=430, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=fstyle.CHART_TEXT,
    )
    st.plotly_chart(fig, use_container_width=True)


def tracking_board(frame, sort_col, columns, precision, note, ascending=False, minimum=None):
    """Board over a Next Gen Stats frame, which arrives already aggregated to
    the season by its own source — so there is nothing to sum here, only
    columns to choose and a qualifying floor to apply."""
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
    top = pool.sort_values(sort_col, ascending=ascending).head(TOP_N)
    display = pd.DataFrame()
    for src, label in columns:
        if src in top.columns:
            display[label] = top[src]
    st.caption(note)
    st.dataframe(
        style.style_stats_table(
            display, team_col="Tm" if "Tm" in display.columns else None,
            team_color_fn=fteams.color_for_abbr, precision=precision,
        ),
        use_container_width=True, hide_index=True, height=520,
    )


def nextgen(season, kind, mtime):
    """NGS for one stat type, with its columns renamed to the site's own."""
    frame = fdb.load_nextgen(season, kind, mtime)
    if frame.empty:
        return frame
    return frame.rename(columns={"player_display_name": "Player", "team_abbr": "Tm"})
