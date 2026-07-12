import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Batting | Sabermetrics Dashboard", layout="wide")
st.title("Batting Stats")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

seasons = db.get_seasons("batting")
season = st.selectbox("Season", seasons, index=0)
batting = db.load_batting(season, db.db_mtime())

col1, col2, col3 = st.columns(3)
with col1:
    team_options = ["All"] + sorted(batting["Tm"].dropna().unique().tolist())
    team = st.selectbox("Team", team_options)
with col2:
    min_pa = st.slider("Minimum PA", 0, int(batting["PA"].max()), 50)
with col3:
    sort_by = st.selectbox(
        "Sort by",
        ["OPS", "HR", "RBI", "SB", "BA", "OBP", "SLG", "PA", "wOBA", "xwOBA", "ISO", "barrel_pct"],
        index=0,
    )

filtered = batting[batting["PA"] >= min_pa]
if team != "All":
    filtered = filtered[filtered["Tm"] == team]
filtered = filtered.sort_values(sort_by, ascending=False).reset_index(drop=True)

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
        ["Name", "Age", "Tm", "G", "PA", "AB", "R", "H", "HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS"]
    ]
    st.dataframe(
        style.style_stats_table(
            display,
            higher_better=["HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS"],
            team_col="Tm",
            team_color_fn=teams.color_for_abbr,
            precision={"BA": "{:.3f}", "OBP": "{:.3f}", "SLG": "{:.3f}", "OPS": "{:.3f}"},
        ),
        use_container_width=True,
        height=600,
    )

with advanced_tab:
    st.caption("ISO = isolated power. BABIP = batting avg on balls in play. wOBA = weighted on-base average.")
    display = teams.add_team_abbr(table_rows)[
        ["Name", "Age", "Tm", "PA", "ISO", "BABIP", "K_PCT", "BB_PCT", "wOBA", "xwOBA"]
    ].rename(columns={"K_PCT": "K%", "BB_PCT": "BB%"})
    st.dataframe(
        style.style_stats_table(
            display,
            higher_better=["ISO", "wOBA", "xwOBA", "BB%"],
            lower_better=["K%"],
            team_col="Tm",
            team_color_fn=teams.color_for_abbr,
            precision={"ISO": "{:.3f}", "BABIP": "{:.3f}", "K%": "{:.1f}", "BB%": "{:.1f}", "wOBA": "{:.3f}", "xwOBA": "{:.3f}"},
        ),
        use_container_width=True,
        height=600,
    )

with statcast_tab:
    st.caption("Exit velocity and barrel rate from Statcast. xBA/xSLG = expected stats based on contact quality.")
    display = teams.add_team_abbr(table_rows)[
        ["Name", "Age", "Tm", "avg_exit_velo", "max_exit_velo", "hard_hit_pct", "barrel_pct", "xBA", "xSLG"]
    ].rename(columns={
        "avg_exit_velo": "Avg EV",
        "max_exit_velo": "Max EV",
        "hard_hit_pct": "Hard-Hit%",
        "barrel_pct": "Barrel%",
    })
    st.dataframe(
        style.style_stats_table(
            display,
            higher_better=["Avg EV", "Max EV", "Hard-Hit%", "Barrel%", "xBA", "xSLG"],
            team_col="Tm",
            team_color_fn=teams.color_for_abbr,
            precision={"Avg EV": "{:.1f}", "Max EV": "{:.1f}", "Hard-Hit%": "{:.1f}", "Barrel%": "{:.1f}", "xBA": "{:.3f}", "xSLG": "{:.3f}"},
        ),
        use_container_width=True,
        height=600,
    )

    st.subheader("Exit Velocity vs. Barrel Rate")
    chart_df = filtered.dropna(subset=["avg_exit_velo", "barrel_pct"])
    fig = px.scatter(
        chart_df, x="avg_exit_velo", y="barrel_pct", size="HR", color="OPS",
        hover_name="Name", color_continuous_scale="OrRd",
        labels={"avg_exit_velo": "Avg Exit Velocity (mph)", "barrel_pct": "Barrel %"},
    )
    fig.update_layout(
        height=450, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color="#FAFAFA",
    )
    st.plotly_chart(fig, use_container_width=True)

with explore_tab:
    st.caption("Pick any two stats to plot against each other, sized by PA and colored by OPS.")
    axis_options = [
        "HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS", "ISO", "BABIP", "K_PCT", "BB_PCT",
        "wOBA", "xwOBA", "avg_exit_velo", "max_exit_velo", "hard_hit_pct", "barrel_pct", "xBA", "xSLG",
    ]
    ecol1, ecol2 = st.columns(2)
    with ecol1:
        x_stat = st.selectbox("X axis", axis_options, index=axis_options.index("avg_exit_velo"))
    with ecol2:
        y_stat = st.selectbox("Y axis", axis_options, index=axis_options.index("barrel_pct"))

    chart_df = filtered.dropna(subset=[x_stat, y_stat])
    fig = px.scatter(
        chart_df, x=x_stat, y=y_stat, size="PA", color="OPS",
        hover_name="Name", color_continuous_scale="OrRd",
    )
    fig.update_layout(
        height=500, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color="#FAFAFA",
    )
    st.plotly_chart(fig, use_container_width=True)
