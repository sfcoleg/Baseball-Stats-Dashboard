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
    min_ip = st.slider("Minimum IP", 0, int(pitching["IP"].max()), db.QUALIFIED_MIN_IP)
with col3:
    sort_by = st.selectbox(
        "Sort by", ["ERA", "FIP", "xFIP", "xERA", "WHIP", "SO", "W", "SV", "IP", "K_9", "dWAR", "WAR", "ERA_plus"], index=0,
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

with st.expander("More filters — league, age, or any stat"):
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
        "Add a stat condition",
        [c for c in numeric_stats if c != "Age"],
        format_func=_stat_label,
        help='Each stat you pick becomes a condition — e.g. pick FIP, choose "At most", '
             "type 3.00 to keep only sub-3 FIP pitchers. Players missing that stat are excluded.",
    )
    conditions = []
    for c in filter_stats:
        # Ratio stats can be legitimately infinite (e.g. K/BB with zero
        # walks) — strip inf as well as NaN so the median default is finite.
        col_vals = pitching[c].replace([float("inf"), float("-inf")], None).dropna()
        if col_vals.empty:
            continue
        ccol1, ccol2 = st.columns([1, 1])
        with ccol1:
            op = st.selectbox(
                _stat_label(c), ["At most (≤)", "At least (≥)"], key=f"pit_cond_op_{c}",
            )
        with ccol2:
            # Defaults to the pool median so adding a condition visibly does
            # something right away, before the exact threshold is typed in.
            if pd.api.types.is_integer_dtype(pitching[c]):
                default = int(col_vals.median())
                value = st.number_input("Value", value=default, step=1, key=f"pit_cond_val_{c}")
            else:
                default = float(round(col_vals.median(), 3))
                value = st.number_input(
                    "Value", value=default, step=0.001, format="%.3f", key=f"pit_cond_val_{c}",
                )
        conditions.append((c, op, value))

filtered = pitching[pitching["IP"] >= min_ip]
if team != "All":
    filtered = filtered[filtered["Tm"] == team]
if league != "All":
    filtered = filtered[filtered["Lev"].str.contains(league, na=False)]
filtered = filtered[filtered["Age"].between(age_range[0], age_range[1])]
for c, op, value in conditions:
    if op.startswith("At least"):
        filtered = filtered[filtered[c] >= value]
    else:
        filtered = filtered[filtered[c] <= value]
ascending = sort_by in ("ERA", "FIP", "xFIP", "xERA", "WHIP")
filtered = filtered.sort_values(sort_by, ascending=ascending).reset_index(drop=True)

table_rows = filtered
st.caption(f"{len(filtered)} players match filters.")

standard_tab, advanced1_tab, advanced2_tab, statcast_tab, custom_tab, explore_tab = st.tabs(
    ["Standard", "Advanced 1", "Advanced 2", "Statcast", "Custom Leaderboard", "Chart Explorer"]
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

# WPA (from our win probability model) and PROP+ (our pitch-quality model,
# ingest/mlb_prop.py) both ride in Advanced rather than Statcast — neither
# is itself a raw Statcast leaderboard number, they're models built on top.
# Shared by both Advanced sub-tabs, so computed once here.
adv_rows = table_rows
wpa = db.load_wpa_pitching(season, db.db_mtime())
if not wpa.empty:
    adv_rows = adv_rows.merge(
        wpa[["mlbID", "wpa", "wpa_plus"]].rename(columns={"wpa": "WPA", "wpa_plus": "WPA+"}),
        on="mlbID", how="left",
    )
else:
    adv_rows = adv_rows.assign(WPA=float("nan"))
    adv_rows = adv_rows.assign(**{"WPA+": float("nan")})
prop = db.load_pitcher_prop(season, db.db_mtime())
if not prop.empty:
    adv_rows = adv_rows.merge(
        prop[["mlbID", "prop_plus"]].astype({"mlbID": adv_rows["mlbID"].dtype})
        .rename(columns={"prop_plus": "PROP+"}),
        on="mlbID", how="left")
    adv_rows["PROP+"] = pd.to_numeric(adv_rows["PROP+"], errors="coerce")
else:
    adv_rows = adv_rows.assign(**{"PROP+": float("nan")})

with advanced1_tab:
    # Run-prevention value: the rate/value stats a pitcher's overall
    # effectiveness boils down to.
    display = teams.add_team_abbr(adv_rows)[
        ["Name", "Age", "Tm", "IP", "FIP", "xFIP", "ERA_plus", "dWAR", "WAR", "PROP+"]
    ].rename(columns={"ERA_plus": "ERA+", "WAR": "bWAR"})
    st.dataframe(
        style.style_stats_table(
            display,
            higher_better=["dWAR", "bWAR", "ERA+", "PROP+"],
            lower_better=["FIP", "xFIP"],
            team_col="Tm",
            team_color_fn=teams.color_for_abbr,
            precision={
                "FIP": "{:.2f}", "xFIP": "{:.2f}", "dWAR": "{:.1f}", "bWAR": "{:.1f}",
                "ERA+": "{:.0f}", "PROP+": "{:.0f}",
            },
        ),
        use_container_width=True,
        height=600,
    )

with advanced2_tab:
    # Peripherals and in-game win value: how a pitcher gets those results,
    # play by play.
    display = teams.add_team_abbr(adv_rows)[
        ["Name", "Age", "Tm", "IP", "K_9", "BB_9", "K_BB", "BAbip", "GB_FB", "WPA", "WPA+"]
    ].rename(columns={"K_9": "K/9", "BB_9": "BB/9", "K_BB": "K/BB", "GB_FB": "GB/FB"})
    st.dataframe(
        style.style_stats_table(
            display,
            higher_better=["K/9", "K/BB", "WPA", "WPA+"],
            lower_better=["BB/9", "BAbip"],
            team_col="Tm",
            team_color_fn=teams.color_for_abbr,
            precision={
                "K/9": "{:.2f}", "BB/9": "{:.2f}", "K/BB": "{:.2f}", "BAbip": "{:.3f}",
                "GB/FB": "{:.2f}", "WPA": "{:+.2f}", "WPA+": "{:+.2f}",
            },
        ),
        use_container_width=True,
        height=600,
    )

with statcast_tab:
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
                "ERA": "{:.2f}", "xERA": "{:.2f}", "ERA diff": "{:+.2f}",
                "xBA Against": "{:.3f}",
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
        hover_name="Name", color_continuous_scale=style.HEAT_SCALE,
        labels={"avg_exit_velo_against": "Avg Exit Velocity Against (mph)"},
    )
    fig.update_layout(
        height=450, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color=style.CHART_TEXT,
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
        hover_name="Name", color_continuous_scale=style.HEAT_SCALE,
    )
    fig.update_layout(
        height=500, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color=style.CHART_TEXT,
    )
    st.plotly_chart(fig, use_container_width=True)
