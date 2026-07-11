import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent))
import db
import sidebar
import style
import teams

st.set_page_config(page_title="Sabermetrics Dashboard", layout="wide")
sidebar.render_search()

st.title("Sabermetrics Dashboard")

if not db.DB_PATH.exists():
    st.error(
        "No data found yet. Run `./venv/bin/python ingest/refresh_data.py` "
        "from the project folder first to fetch stats."
    )
    st.stop()

updated = db.last_updated()
st.caption(f"Data last refreshed: {updated}")

seasons = db.get_seasons("batting")
season = st.selectbox("Season", seasons, index=0)

mtime = db.db_mtime()
batting = db.load_batting(season, mtime)
pitching = db.load_pitching(season, mtime)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Batters tracked", len(batting))
col2.metric("Pitchers tracked", len(pitching))
col3.metric("Season", season)
col4.metric("Teams", batting["Tm"].nunique())

st.divider()

qualified_batters = batting[batting["PA"] >= 50].sort_values("OPS", ascending=False)
qualified_pitchers = pitching[pitching["IP"] >= 20].sort_values("ERA", ascending=True)

recent_batting = db.load_recent_batting(season, mtime)
recent_pitching = db.load_recent_pitching(season, mtime)

milestones = db.get_milestones(season, mtime)
if milestones:
    style.colored_header("Milestones", "headliners")
    st.caption("Notable achievements from yesterday's games.")
    milestone_cols = st.columns(min(len(milestones), 3))
    for i, m in enumerate(milestones):
        with milestone_cols[i % 3]:
            with st.container(border=True):
                abbr, _, color = teams.team_meta_from_city(m["Tm"], m.get("Lev"))
                style.milestone_card(m["mlbID"], m["Name"], abbr, color, m["text"])
    st.divider()

if season == date.today().year:
    style.colored_header("Batting Headliners", "batting")
    st.caption("Hottest recent hitting performances, refreshed daily — not just season-long bests.")
    h1, h2, h3 = st.columns(3)
    for col, period, label in [(h1, "day", "Hot Yesterday"), (h2, "week", "Hot This Week"), (h3, "month", "Hot This Month")]:
        with col:
            with st.container(border=True):
                performer = db.top_recent_performer(recent_batting, period)
                if performer is not None:
                    abbr, _, color = teams.team_meta_from_city(performer["Tm"], performer.get("Lev"))
                    if period == "day":
                        tb = int(performer["H"] + performer["2B"] + 2 * performer["3B"] + 3 * performer["HR"])
                        stat_line = f"{tb} TB, {int(performer['H'])} H, {int(performer['HR'])} HR, {int(performer['RBI'])} RBI"
                    else:
                        stat_line = f"{performer['OPS']:.3f} OPS, {int(performer['HR'])} HR ({int(performer['PA'])} PA)"
                    style.headliner_card(label, performer["Name"], abbr, color, stat_line)
                else:
                    st.caption(label)
                    st.markdown("No data yet")

    style.colored_header("Pitching Headliners", "pitching")
    st.caption("Hottest recent pitching performances — Game Score for yesterday, ERA (min IP) for week/month.")
    p1, p2, p3 = st.columns(3)
    for col, period, label in [(p1, "day", "Hot Yesterday"), (p2, "week", "Hot This Week"), (p3, "month", "Hot This Month")]:
        with col:
            with st.container(border=True):
                pitcher = db.top_recent_pitcher(recent_pitching, period)
                if pitcher is not None:
                    abbr, _, color = teams.team_meta_from_city(pitcher["Tm"], pitcher.get("Lev"))
                    if period == "day" and pd.notna(pitcher.get("GSc")):
                        stat_line = f"Game Score {int(pitcher['GSc'])}, {pitcher['ERA']:.2f} ERA ({pitcher['IP']:.1f} IP)"
                    else:
                        stat_line = f"{pitcher['ERA']:.2f} ERA, {int(pitcher['SO'])} SO ({pitcher['IP']:.1f} IP)"
                    style.headliner_card(label, pitcher["Name"], abbr, color, stat_line)
                else:
                    st.caption(label)
                    st.markdown("No data yet")

    st.divider()

style.colored_header("Top 10 Home Run Leaders", "chart")
top10_hr = batting.sort_values("HR", ascending=False).head(10).iloc[::-1]
fig = px.bar(
    top10_hr, x="HR", y="Name", orientation="h",
    color="HR", color_continuous_scale="OrRd",
    text="HR",
)
fig.update_layout(
    showlegend=False, coloraxis_showscale=False,
    height=400, margin=dict(l=0, r=0, t=10, b=0),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font_color="#FAFAFA",
)
st.plotly_chart(fig, use_container_width=True)

st.divider()

style.colored_header("Team Snapshot", "chart")
team_batting = teams.add_team_abbr(qualified_batters)
team_ops = (
    team_batting.groupby("Tm", observed=True)["OPS"].mean().round(3)
    .reset_index().sort_values("OPS", ascending=False)
)
team_pitching = teams.add_team_abbr(qualified_pitchers)
team_era = (
    team_pitching.groupby("Tm", observed=True)["ERA"].mean().round(2)
    .reset_index().sort_values("ERA", ascending=True)
)

tcol1, tcol2 = st.columns(2)
with tcol1:
    st.caption("Average qualified-batter OPS by team")
    fig = px.bar(
        team_ops, x="Tm", y="OPS",
        color="Tm", color_discrete_map={t: teams.color_for_abbr(t) for t in team_ops["Tm"]},
    )
    fig.update_layout(
        showlegend=False, height=380, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color="#FAFAFA", xaxis_title=None,
    )
    st.plotly_chart(fig, use_container_width=True)
with tcol2:
    st.caption("Average qualified-pitcher ERA by team")
    fig = px.bar(
        team_era, x="Tm", y="ERA",
        color="Tm", color_discrete_map={t: teams.color_for_abbr(t) for t in team_era["Tm"]},
    )
    fig.update_layout(
        showlegend=False, height=380, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color="#FAFAFA", xaxis_title=None,
    )
    st.plotly_chart(fig, use_container_width=True)

st.divider()

style.colored_header("Batting Leaders (min 50 PA)", "batting")
st.caption(f"Top 50 of {len(qualified_batters)} qualified batters by OPS — see the Batting page for the full filterable list.")
batting_display = teams.add_team_abbr(qualified_batters.head(50))[
    ["Name", "Age", "Tm", "G", "PA", "HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS"]
].reset_index(drop=True)
st.dataframe(
    style.style_stats_table(
        batting_display,
        higher_better=["HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS"],
        team_col="Tm",
        team_color_fn=teams.color_for_abbr,
        precision={"BA": "{:.3f}", "OBP": "{:.3f}", "SLG": "{:.3f}", "OPS": "{:.3f}"},
    ),
    use_container_width=True,
    height=400,
)

style.colored_header("Pitching Leaders (min 20 IP)", "pitching")
st.caption(f"Top 50 of {len(qualified_pitchers)} qualified pitchers by ERA — see the Pitching page for the full filterable list.")
pitching_display = teams.add_team_abbr(qualified_pitchers.head(50))[
    ["Name", "Age", "Tm", "G", "GS", "W", "L", "SV", "IP", "ERA", "WHIP", "SO"]
].reset_index(drop=True)
st.dataframe(
    style.style_stats_table(
        pitching_display,
        higher_better=["W", "SV", "SO"],
        lower_better=["ERA", "WHIP", "L"],
        team_col="Tm",
        team_color_fn=teams.color_for_abbr,
        precision={"ERA": "{:.2f}", "WHIP": "{:.3f}"},
    ),
    use_container_width=True,
    height=400,
)

st.info("Use the pages in the sidebar for filterable Batting, Pitching, Fielding leaderboards, and Player Search.")
