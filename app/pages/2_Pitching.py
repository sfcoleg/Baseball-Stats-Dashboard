import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Pitching | Sabermetrics Dashboard", layout="wide")
st.title("Pitching Stats")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

seasons = db.get_seasons("pitching")
season = st.selectbox("Season", seasons, index=0)
pitching = db.load_pitching(season, db.db_mtime())

col1, col2, col3 = st.columns(3)
with col1:
    team_options = ["All"] + sorted(pitching["Tm"].dropna().unique().tolist())
    team = st.selectbox("Team", team_options)
with col2:
    min_ip = st.slider("Minimum IP", 0, int(pitching["IP"].max()), 20)
with col3:
    sort_by = st.selectbox(
        "Sort by", ["ERA", "FIP", "WHIP", "SO", "W", "SV", "IP", "K_9"], index=0
    )

filtered = pitching[pitching["IP"] >= min_ip]
if team != "All":
    filtered = filtered[filtered["Tm"] == team]
ascending = sort_by in ("ERA", "FIP", "WHIP")
filtered = filtered.sort_values(sort_by, ascending=ascending).reset_index(drop=True)

max_rows = st.slider(
    "Max rows shown in tables below", 25, max(len(filtered), 25), min(75, max(len(filtered), 25)),
    help="Lower this if the dashboard is crashing — rendering large tables is the most memory-intensive thing this app does.",
)
table_rows = filtered.head(max_rows)
st.caption(f"{len(filtered)} players match filters — showing {len(table_rows)} in the tables below.")

standard_tab, advanced_tab, statcast_tab, explore_tab = st.tabs(
    ["Standard", "Advanced (Sabermetrics)", "Statcast", "Chart Explorer"]
)

with standard_tab:
    display = teams.add_team_abbr(table_rows)[
        ["Name", "Age", "Tm", "G", "GS", "W", "L", "SV", "IP", "ERA", "WHIP", "SO", "BB", "HR"]
    ]
    st.dataframe(
        style.style_stats_table(
            display,
            higher_better=["W", "SV", "SO"],
            lower_better=["ERA", "WHIP", "L", "BB"],
            team_col="Tm",
            team_color_fn=teams.color_for_abbr,
            precision={"ERA": "{:.2f}", "WHIP": "{:.3f}"},
        ),
        use_container_width=True,
        height=600,
    )

with advanced_tab:
    st.caption("FIP = fielding-independent pitching (ERA-scale, strips out defense/luck). K/9, BB/9 = per-9-inning rates. K/BB = strikeout-to-walk ratio.")
    display = teams.add_team_abbr(table_rows)[
        ["Name", "Age", "Tm", "IP", "FIP", "K_9", "BB_9", "K_BB"]
    ].rename(columns={"K_9": "K/9", "BB_9": "BB/9", "K_BB": "K/BB"})
    st.dataframe(
        style.style_stats_table(
            display,
            higher_better=["K/9", "K/BB"],
            lower_better=["FIP", "BB/9"],
            team_col="Tm",
            team_color_fn=teams.color_for_abbr,
            precision={"FIP": "{:.2f}", "K/9": "{:.2f}", "BB/9": "{:.2f}", "K/BB": "{:.2f}"},
        ),
        use_container_width=True,
        height=600,
    )

with statcast_tab:
    st.caption("Contact quality allowed, from Statcast (Baseball Savant).")
    display = teams.add_team_abbr(table_rows)[
        ["Name", "Age", "Tm", "avg_exit_velo_against", "hard_hit_pct_against", "barrel_pct_against"]
    ].rename(columns={
        "avg_exit_velo_against": "Avg EV Against",
        "hard_hit_pct_against": "Hard-Hit% Against",
        "barrel_pct_against": "Barrel% Against",
    })
    st.dataframe(
        style.style_stats_table(
            display,
            lower_better=["Avg EV Against", "Hard-Hit% Against", "Barrel% Against"],
            team_col="Tm",
            team_color_fn=teams.color_for_abbr,
            precision={"Avg EV Against": "{:.1f}", "Hard-Hit% Against": "{:.1f}", "Barrel% Against": "{:.1f}"},
        ),
        use_container_width=True,
        height=600,
    )

    st.subheader("Exit Velocity Allowed vs. ERA")
    chart_df = filtered.dropna(subset=["avg_exit_velo_against", "ERA"])
    fig = px.scatter(
        chart_df, x="avg_exit_velo_against", y="ERA", size="IP", color="ERA",
        hover_name="Name", color_continuous_scale="RdYlGn_r",
        labels={"avg_exit_velo_against": "Avg Exit Velocity Against (mph)"},
    )
    fig.update_layout(
        height=450, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color="#FAFAFA",
    )
    st.plotly_chart(fig, use_container_width=True)

with explore_tab:
    st.caption("Pick any two stats to plot against each other, sized by IP and colored by ERA.")
    axis_options = [
        "ERA", "FIP", "WHIP", "SO", "W", "SV", "K_9", "BB_9", "K_BB",
        "avg_exit_velo_against", "hard_hit_pct_against", "barrel_pct_against",
    ]
    ecol1, ecol2 = st.columns(2)
    with ecol1:
        x_stat = st.selectbox("X axis", axis_options, index=axis_options.index("avg_exit_velo_against"))
    with ecol2:
        y_stat = st.selectbox("Y axis", axis_options, index=axis_options.index("ERA"))

    chart_df = filtered.dropna(subset=[x_stat, y_stat])
    fig = px.scatter(
        chart_df, x=x_stat, y=y_stat, size="IP", color="ERA",
        hover_name="Name", color_continuous_scale="RdYlGn_r",
    )
    fig.update_layout(
        height=500, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color="#FAFAFA",
    )
    st.plotly_chart(fig, use_container_width=True)
