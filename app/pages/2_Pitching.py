import math
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import prefs
import style
import teams

st.set_page_config(page_title="Pitching | Diamond Metrics", layout="wide")
st.title("Pitching Stats")
style.glossary_link()

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

seasons = db.get_seasons("pitching")
season = st.selectbox("Season", seasons, index=prefs.default_season_index(seasons))
pitching = db.load_pitching(season, db.db_mtime())

col1, col2, col3 = st.columns(3)
with col1:
    team_options = ["All"] + sorted(pitching["Tm"].dropna().unique().tolist())
    team = st.selectbox("Team", team_options)
with col2:
    min_ip = st.slider("Minimum IP", 0, int(pitching["IP"].max()), 20)
with col3:
    sort_by = st.selectbox(
        "Sort by", ["ERA", "FIP", "xERA", "WHIP", "SO", "W", "SV", "IP", "K_9", "WAR", "ERA_plus"], index=0,
        format_func=lambda s: db.STAT_DISPLAY_LABELS.get(s, s),
    )

# Every numeric column is fair game for both the any-stat filters below and
# the Custom Leaderboard tab — no hand-curated list to fall out of date when
# a new stat column gets ingested.
_ID_COLS = {"mlbID", "season"}
numeric_stats = [
    c for c in pitching.columns
    if c not in _ID_COLS and pd.api.types.is_numeric_dtype(pitching[c])
]
numeric_stats.sort(key=lambda c: db.STAT_DISPLAY_LABELS.get(c, c).lower())
_stat_label = lambda c: db.STAT_DISPLAY_LABELS.get(c, c)

with st.expander("🔍 More filters — league, age, or any stat"):
    fcol1, fcol2 = st.columns(2)
    with fcol1:
        # Lev is "Maj-AL"/"Maj-NL"/"Maj-AL,Maj-NL" (the last for a pitcher
        # traded across leagues mid-season) — a plain substring check on the
        # raw column, no team-abbreviation lookup needed.
        league = st.selectbox("League", ["All", "AL", "NL"])
    with fcol2:
        age_lo, age_hi = int(pitching["Age"].min()), int(pitching["Age"].max())
        age_range = st.slider("Age", age_lo, age_hi, (age_lo, age_hi))
    filter_stats = st.multiselect(
        "Filter by any stat",
        [c for c in numeric_stats if c != "Age"],
        format_func=_stat_label,
        help="Each stat you pick gets its own min/max range slider. While a range is "
             "narrowed, players missing that stat are excluded.",
    )
    stat_ranges = {}
    range_cols = st.columns(2)
    for i, c in enumerate(filter_stats):
        col_vals = pitching[c].dropna()
        if col_vals.empty or float(col_vals.min()) == float(col_vals.max()):
            continue
        with range_cols[i % 2]:
            if pd.api.types.is_integer_dtype(pitching[c]):
                lo, hi = int(col_vals.min()), int(col_vals.max())
                picked = st.slider(_stat_label(c), lo, hi, (lo, hi), key=f"pit_filter_{c}")
            else:
                lo = math.floor(float(col_vals.min()) * 1000) / 1000
                hi = math.ceil(float(col_vals.max()) * 1000) / 1000
                picked = st.slider(
                    _stat_label(c), lo, hi, (lo, hi),
                    step=max((hi - lo) / 200, 0.001), key=f"pit_filter_{c}",
                )
        # Only applied when actually narrowed — an untouched full-range
        # slider shouldn't silently drop players who are missing the stat.
        if picked != (lo, hi):
            stat_ranges[c] = picked

filtered = pitching[pitching["IP"] >= min_ip]
if team != "All":
    filtered = filtered[filtered["Tm"] == team]
if league != "All":
    filtered = filtered[filtered["Lev"].str.contains(league, na=False)]
filtered = filtered[filtered["Age"].between(age_range[0], age_range[1])]
for c, (lo, hi) in stat_ranges.items():
    filtered = filtered[filtered[c].between(lo, hi)]
ascending = sort_by in ("ERA", "FIP", "xERA", "WHIP")
filtered = filtered.sort_values(sort_by, ascending=ascending).reset_index(drop=True)

table_rows = filtered
st.caption(f"{len(filtered)} players match filters.")

standard_tab, advanced_tab, statcast_tab, custom_tab, explore_tab = st.tabs(
    ["Standard", "Advanced", "Statcast", "Custom Leaderboard", "Chart Explorer"]
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
    st.caption(
        "FIP = fielding-independent pitching. BAbip = opponent BABIP. GB/FB = groundball/flyball ratio. "
        "WAR = wins above replacement (Baseball-Reference). ERA+ = 100 is league average, higher is better "
        "(park-factor-free approximation)."
    )
    display = teams.add_team_abbr(table_rows)[
        ["Name", "Age", "Tm", "IP", "FIP", "K_9", "BB_9", "K_BB", "BAbip", "GB_FB", "WAR", "ERA_plus"]
    ].rename(columns={"K_9": "K/9", "BB_9": "BB/9", "K_BB": "K/BB", "GB_FB": "GB/FB", "ERA_plus": "ERA+"})
    st.dataframe(
        style.style_stats_table(
            display,
            higher_better=["K/9", "K/BB", "WAR", "ERA+"],
            lower_better=["FIP", "BB/9", "BAbip"],
            team_col="Tm",
            team_color_fn=teams.color_for_abbr,
            precision={
                "FIP": "{:.2f}", "K/9": "{:.2f}", "BB/9": "{:.2f}", "K/BB": "{:.2f}", "BAbip": "{:.3f}",
                "GB/FB": "{:.2f}", "WAR": "{:.1f}", "ERA+": "{:.0f}",
            },
        ),
        use_container_width=True,
        height=600,
    )

with statcast_tab:
    st.caption(
        "Contact quality allowed, from Statcast. xERA/xBA/xSLG against = expected stats based on quality of "
        "contact allowed. \"diff\" is actual ERA minus expected ERA — positive means outperforming the "
        "underlying contact quality, negative means getting unlucky relative to it. Fastball Velo = average "
        "four-seam velocity. Induced Chase% = how often opposing batters swing at this pitcher's pitches "
        "outside the strike zone."
    )
    display = teams.add_team_abbr(table_rows)[
        ["Name", "Age", "Tm", "ERA", "xERA", "xERA_diff", "xBA_against", "xSLG_against",
         "avg_exit_velo_against", "hard_hit_pct_against", "barrel_pct_against",
         "fastball_velo", "induced_chase_pct"]
    ].rename(columns={
        "avg_exit_velo_against": "Avg EV Against",
        "hard_hit_pct_against": "Hard-Hit% Against",
        "barrel_pct_against": "Barrel% Against",
        "xBA_against": "xBA Against",
        "xSLG_against": "xSLG Against",
        "xERA_diff": "ERA diff",
        "fastball_velo": "Fastball Velo",
        "induced_chase_pct": "Induced Chase%",
    })
    st.dataframe(
        style.style_stats_table(
            display,
            higher_better=["ERA diff", "Fastball Velo", "Induced Chase%"],
            lower_better=["ERA", "xERA", "xBA Against", "xSLG Against", "Avg EV Against", "Hard-Hit% Against", "Barrel% Against"],
            team_col="Tm",
            team_color_fn=teams.color_for_abbr,
            precision={
                "ERA": "{:.2f}", "xERA": "{:.2f}", "ERA diff": "{:+.2f}", "xBA Against": "{:.3f}",
                "xSLG Against": "{:.3f}", "Avg EV Against": "{:.1f}", "Hard-Hit% Against": "{:.1f}",
                "Barrel% Against": "{:.1f}", "Fastball Velo": "{:.1f}", "Induced Chase%": "{:.1f}",
            },
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

# Stats where a LOWER number is the good direction — drives the color
# gradient in the Custom Leaderboard. Anything not listed colors high=green.
_PITCHING_LOWER_BETTER = {
    "ERA", "FIP", "xERA", "WHIP", "BB", "BB_9", "HR", "L", "BAbip",
    "xBA_against", "xSLG_against", "xwOBA_against",
    "avg_exit_velo_against", "hard_hit_pct_against", "barrel_pct_against",
}

with custom_tab:
    st.caption(
        "Build your own leaderboard — pick any stats we track, in any combination, sorted however "
        "you like. The team/IP/league/age/stat filters above all apply here too."
    )
    chosen = st.multiselect(
        "Stats to show",
        numeric_stats,
        default=["Age", "IP", "ERA", "WHIP", "SO", "WAR"],
        format_func=_stat_label,
        key="pit_custom_cols",
    )
    if not chosen:
        st.info("Pick at least one stat to build a leaderboard.")
    else:
        ccol1, ccol2 = st.columns(2)
        with ccol1:
            custom_sort = st.selectbox("Sort by", chosen, format_func=_stat_label, key="pit_custom_sort")
        with ccol2:
            custom_order = st.radio(
                "Order", ["High → Low", "Low → High"], horizontal=True, key="pit_custom_order",
            )
        display = teams.add_team_abbr(table_rows)[["Name", "Tm"] + chosen]
        display = display.sort_values(
            custom_sort, ascending=(custom_order == "Low → High"), na_position="last",
        ).reset_index(drop=True)
        st.dataframe(
            style.style_stats_table(
                display.rename(columns=_stat_label),
                higher_better=[_stat_label(c) for c in chosen if c not in _PITCHING_LOWER_BETTER],
                lower_better=[_stat_label(c) for c in chosen if c in _PITCHING_LOWER_BETTER],
                team_col="Tm",
                team_color_fn=teams.color_for_abbr,
            ),
            use_container_width=True,
            height=600,
        )

with explore_tab:
    st.caption("Pick any two stats to plot against each other, sized by IP and colored by ERA.")
    axis_options = [
        "ERA", "FIP", "xERA", "WHIP", "SO", "W", "SV", "K_9", "BB_9", "K_BB", "BAbip", "GB_FB",
        "avg_exit_velo_against", "hard_hit_pct_against", "barrel_pct_against",
        "fastball_velo", "induced_chase_pct",
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
