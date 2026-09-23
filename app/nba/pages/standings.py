"""NBA Standings — by conference, matching how the league actually seeds
its playoffs (PlayoffRank is already conference-relative, not global)."""
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nba import db as ndb
from nba import style as nstyle
from nba import teams as nteams

PLAYOFF_SEEDS = 8  # clean NBA playoff-line cutoff (excludes the 9/10 play-in-only teams)

st.set_page_config(page_title="NBA Standings | Diamond Metrics", layout="wide")
st.title("Standings")

mtime = ndb.nba_db_mtime()
standings = ndb.load_standings(mtime)
if standings.empty:
    st.info("No NBA data yet — run `python ingest/nba_refresh.py` to build it.")
    st.stop()

if ndb.standings_are_preseason(mtime):
    st.caption(
        f"The {ndb.current_season_label()} season hasn't tipped off yet — every team "
        "is 0-0. This is the real standings table, just before any games count."
    )

abbr_map = ndb.team_abbr_map(mtime)
standings = standings.assign(Team=standings["TeamID"].map(abbr_map).fillna(standings["TeamCity"]))

for conf in sorted(standings["Conference"].dropna().unique()):
    conf_rows = standings[standings["Conference"] == conf].sort_values("PlayoffRank")
    style.colored_header(conf, "batting")

    # --- Win% chart: every team, sorted, playoff seeds (top 8) at full
    # opacity and the rest of the conference dimmed. No playoff-odds/
    # probability model exists for NBA (unlike MLB/NHL), so this sticks to
    # the one thing that's real right now: current win percentage.
    gp = conf_rows["WINS"] + conf_rows["LOSSES"]
    win_pct = (conf_rows["WINS"] / gp.replace(0, pd.NA)).fillna(0.0)
    chart_df = pd.DataFrame({
        "Team": conf_rows["Team"], "WinPct": win_pct, "Seed": conf_rows["PlayoffRank"],
    }).sort_values("WinPct", ascending=True)
    opacities = [1.0 if seed <= PLAYOFF_SEEDS else 0.35 for seed in chart_df["Seed"]]
    fig = px.bar(
        chart_df, x="WinPct", y="Team", orientation="h", color="Team",
        color_discrete_map={t: nteams.color_for_abbr(t) for t in chart_df["Team"]},
        text=chart_df["WinPct"].map(lambda v: f"{v:.3f}"),
        labels={"WinPct": "Win %"},
    )
    fig.update_traces(marker=dict(opacity=opacities))
    fig.update_layout(
        showlegend=False, height=380, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=nstyle.CHART_TEXT,
        yaxis_title=None, xaxis=dict(range=[0, 1]),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Top {PLAYOFF_SEEDS} seeds (playoff line) shown at full opacity; the rest of the conference dimmed.")

    display = pd.DataFrame({
        "Team": conf_rows["Team"],
        "W": conf_rows["WINS"].astype(int),
        "L": conf_rows["LOSSES"].astype(int),
        "Conf": conf_rows.get("ConferenceRecord", ""),
        "Div": conf_rows.get("DivisionRecord", ""),
    })
    st.dataframe(
        style.style_stats_table(
            display, team_col="Team", team_color_fn=nteams.color_for_abbr,
            higher_better=["W"], lower_better=["L"],
        ),
        use_container_width=True, hide_index=True,
    )
