"""NFL Standings — by division, which is how the league is actually
organised and how playoff seeding is decided."""
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import db as fdb
from nfl import style as fstyle
from nfl import teams as fteams

# The league seeds 7 teams per conference for the playoffs — used to shade
# the win% bars, not as a fake odds model (there is no playoff-odds model
# for NFL on this site).
PLAYOFF_SEEDS = 7

st.set_page_config(page_title="NFL Standings | Diamond Metrics", layout="wide")
st.title("Standings")

mtime = fdb.nfl_db_mtime()
season_list = fdb.seasons(mtime)
if not season_list:
    st.info("No NFL data yet — run `python ingest/nfl_refresh.py` to build it.")
    st.stop()

season = st.selectbox("Season", season_list, index=fdb.season_index(season_list, mtime),
                       format_func=fdb.season_label)
standings = fdb.load_standings(season, mtime)
if standings.empty:
    st.caption(f"No games played yet in {fdb.season_label(season)}.")
    st.stop()

for conf in ("AFC", "NFC"):
    conf_rows = standings[standings["team_conf"] == conf]
    if conf_rows.empty:
        continue
    style.colored_header(conf, "batting")

    # Win% by team, sorted descending, with the top 7 seeds (the number the
    # league actually takes to the playoffs per conference) drawn at full
    # opacity and the rest dimmed — a shaded cutoff band, not a fabricated
    # playoff-odds percentage.
    conf_sorted = conf_rows.sort_values(["win_pct", "point_diff"], ascending=False).reset_index(drop=True)
    conf_sorted["seed"] = conf_sorted.index + 1
    conf_sorted["opacity"] = conf_sorted["seed"].map(lambda s: 1.0 if s <= PLAYOFF_SEEDS else 0.35)
    plot_df = conf_sorted.iloc[::-1]  # reverse so seed 1 renders at the top of the horizontal bar
    fig = px.bar(
        plot_df, x="win_pct", y="team", orientation="h",
        color="team", color_discrete_map={t: fteams.color_for_abbr(t) for t in plot_df["team"]},
        text="win_pct", labels={"win_pct": "Win%", "team": ""},
    )
    for trace in fig.data:
        team_abbr = trace.name
        trace.marker.opacity = float(plot_df.loc[plot_df["team"] == team_abbr, "opacity"].iloc[0])
        trace.texttemplate = "%{x:.3f}"
    if (conf_sorted["seed"] == PLAYOFF_SEEDS).any():
        cutoff = conf_sorted.loc[conf_sorted["seed"] == PLAYOFF_SEEDS, "win_pct"].iloc[0]
        fig.add_vline(
            x=cutoff, line=dict(color=fstyle.CHART_DIM, width=1, dash="dot"),
            annotation_text="Playoff cutoff (7 seeds)", annotation_position="top",
            annotation_font_size=10, annotation_font_color=fstyle.CHART_DIM,
        )
    fig.update_layout(
        showlegend=False, height=max(320, 26 * len(plot_df)), margin=dict(l=0, r=10, t=30, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=fstyle.CHART_TEXT,
        xaxis=dict(range=[0, 1]),
    )
    st.plotly_chart(fig, use_container_width=True)

    divisions = sorted(conf_rows["team_division"].dropna().unique())
    cols = st.columns(2)
    for i, division in enumerate(divisions):
        div_rows = conf_rows[conf_rows["team_division"] == division].sort_values(
            ["win_pct", "point_diff"], ascending=False
        )
        with cols[i % 2]:
            st.markdown(f"**{division}**")
            display = pd.DataFrame({
                "Team": div_rows["team"],
                "W": div_rows["wins"].astype(int),
                "L": div_rows["losses"].astype(int),
                "T": div_rows["ties"].astype(int),
                "PCT": div_rows["win_pct"],
                "PF": div_rows["points_for"].astype(int),
                "PA": div_rows["points_against"].astype(int),
                "DIFF": div_rows["point_diff"].astype(int),
                "DIV": div_rows["div_wins"].astype(int).astype(str) + "-" + div_rows["div_losses"].astype(int).astype(str),
            })
            st.dataframe(
                style.style_stats_table(
                    display, team_col="Team", team_color_fn=fteams.color_for_abbr,
                    higher_better=["W", "PCT", "PF", "DIFF"], lower_better=["L", "PA"],
                    precision={"PCT": "{:.3f}"},
                ),
                use_container_width=True, hide_index=True,
            )
