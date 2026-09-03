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

st.set_page_config(page_title="Batting | Diamond Metrics", layout="wide")
st.title("Batting Stats")
style.glossary_link()

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

seasons = db.get_seasons("batting")
season = st.selectbox("Season", seasons, index=prefs.default_season_index(seasons))
batting = db.load_batting(season, db.db_mtime())
# Computed on the FULL season table, before any team/PA filtering below —
# HVS is scaled against the whole season's qualified-player distribution,
# so its meaning shouldn't shift depending on what subset of rows the
# user currently has the page filtered down to.
batting["HVS"] = db.hitting_value_score(batting)

# Batted-ball direction/type lives in its own table (see db.load_batted_ball),
# not `batting` — merge it in here so the whole page (Custom Leaderboard's
# any-stat picker included, since that works off batting.columns) can see
# it, not just a dedicated tab below.
_bb = db.load_batted_ball(season, db.db_mtime())
if not _bb.empty:
    batting = batting.merge(
        _bb.drop(columns="season", errors="ignore"), on="mlbID", how="left",
    )

col1, col2, col3 = st.columns(3)
with col1:
    team_options = ["All"] + sorted(batting["Tm"].dropna().unique().tolist())
    team = st.selectbox("Team", team_options)
with col2:
    min_pa = st.slider("Minimum PA", 0, int(batting["PA"].max()), db.QUALIFIED_MIN_PA)
with col3:
    sort_by = st.selectbox(
        "Sort by",
        ["OPS", "HR", "RBI", "SB", "BA", "OBP", "SLG", "PA", "wOBA", "xwOBA", "ISO", "barrel_pct", "WAR", "OPS_plus", "wRC_plus"],
        index=0,
        format_func=lambda s: db.STAT_DISPLAY_LABELS.get(s, s),
    )

# Every numeric column is fair game for both the any-stat filters below and
# the Custom Leaderboard tab — no hand-curated list to fall out of date when
# a new stat column gets ingested.
_ID_COLS = {"mlbID", "season"}
numeric_stats = [
    c for c in batting.columns
    if c not in _ID_COLS and pd.api.types.is_numeric_dtype(batting[c])
]
numeric_stats.sort(key=lambda c: db.STAT_DISPLAY_LABELS.get(c, c).lower())
_stat_label = lambda c: db.STAT_DISPLAY_LABELS.get(c, c)

with st.expander("More filters — league, age, or any stat"):
    fcol1, fcol2 = st.columns(2)
    with fcol1:
        # Lev is "Maj-AL"/"Maj-NL"/"Maj-AL,Maj-NL" (the last for a player
        # traded across leagues mid-season) — a plain substring check on the
        # raw column, no team-abbreviation lookup needed.
        league = st.selectbox("League", ["All", "AL", "NL"])
    with fcol2:
        age_lo, age_hi = int(batting["Age"].min()), int(batting["Age"].max())
        age_range = st.slider("Age", age_lo, age_hi, (age_lo, age_hi))
    filter_stats = st.multiselect(
        "Add a stat condition",
        [c for c in numeric_stats if c != "Age"],
        format_func=_stat_label,
        help='Each stat you pick becomes a condition — e.g. pick OPS, choose "At least", '
             "type 0.800 to keep only .800+ OPS hitters. Players missing that stat are excluded.",
    )
    conditions = []
    for c in filter_stats:
        # Ratio stats can be legitimately infinite (e.g. K/BB with zero
        # walks) — strip inf as well as NaN so the median default is finite.
        col_vals = batting[c].replace([float("inf"), float("-inf")], None).dropna()
        if col_vals.empty:
            continue
        ccol1, ccol2 = st.columns([1, 1])
        with ccol1:
            op = st.selectbox(
                _stat_label(c), ["At least (≥)", "At most (≤)"], key=f"bat_cond_op_{c}",
            )
        with ccol2:
            # Defaults to the pool median so adding a condition visibly does
            # something right away, before the exact threshold is typed in.
            if pd.api.types.is_integer_dtype(batting[c]):
                default = int(col_vals.median())
                value = st.number_input("Value", value=default, step=1, key=f"bat_cond_val_{c}")
            else:
                default = float(round(col_vals.median(), 3))
                value = st.number_input(
                    "Value", value=default, step=0.001, format="%.3f", key=f"bat_cond_val_{c}",
                )
        conditions.append((c, op, value))

filtered = batting[batting["PA"] >= min_pa]
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
filtered = filtered.sort_values(sort_by, ascending=False).reset_index(drop=True)

table_rows = filtered
st.caption(f"{len(filtered)} players match filters.")

standard_tab, advanced_tab, statcast_tab, discipline_tab, bb_tab, custom_tab, explore_tab = st.tabs(
    ["Standard", "Advanced", "Statcast", "Plate Discipline", "Batted Ball", "Custom Leaderboard", "Chart Explorer"]
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
        column_config=style.pin_first_column(display),
        use_container_width=True,
        height=600,
    )

with advanced_tab:
    # WPA (from our win probability model) rides at the end of Advanced
    # rather than in a tab of its own — merged by mlbID, blank for players
    # without graded plate appearances (pre-2025 seasons).
    adv_rows = table_rows
    wpa = db.load_wpa_batting(season, db.db_mtime())
    if not wpa.empty:
        adv_rows = adv_rows.merge(
            wpa[["mlbID", "wpa", "wpa_plus"]].rename(columns={"wpa": "WPA", "wpa_plus": "WPA+"}),
            on="mlbID", how="left",
        )
    else:
        adv_rows = adv_rows.assign(WPA=float("nan"))
        adv_rows = adv_rows.assign(**{"WPA+": float("nan")})
    display = teams.add_team_abbr(adv_rows)[
        ["Name", "Age", "Tm", "PA", "ISO", "BABIP", "K_PCT", "BB_PCT", "contact_pct", "wOBA", "xwOBA",
         "WAR", "OPS_plus", "wRC_plus", "wRAA", "HVS", "WPA", "WPA+"]
    ].rename(columns={"K_PCT": "K%", "BB_PCT": "BB%", "contact_pct": "Contact%", "OPS_plus": "OPS+", "wRC_plus": "wRC+", "WAR": "bWAR"})
    st.dataframe(
        style.style_stats_table(
            display,
            higher_better=["ISO", "wOBA", "xwOBA", "BB%", "Contact%", "bWAR", "OPS+", "wRC+", "wRAA", "HVS", "WPA", "WPA+"],
            lower_better=["K%"],
            team_col="Tm",
            team_color_fn=teams.color_for_abbr,
            precision={
                "ISO": "{:.3f}", "BABIP": "{:.3f}", "K%": "{:.1f}", "BB%": "{:.1f}", "Contact%": "{:.1f}",
                "wOBA": "{:.3f}", "xwOBA": "{:.3f}", "bWAR": "{:.1f}", "OPS+": "{:.0f}", "wRC+": "{:.0f}",
                "wRAA": "{:+.1f}", "HVS": "{:.0f}",
                "WPA": "{:+.2f}", "WPA+": "{:+.2f}",
            },
        ),
        column_config=style.pin_first_column(display),
        use_container_width=True,
        height=600,
    )

with statcast_tab:
    display = teams.add_team_abbr(table_rows)[
        ["Name", "Age", "Tm", "avg_exit_velo", "max_exit_velo", "hard_hit_pct", "barrel_pct",
         "xBA", "xSLG", "xwOBA_diff"]
    ].rename(columns={
        "avg_exit_velo": "Avg EV",
        "max_exit_velo": "Max EV",
        "hard_hit_pct": "Hard-Hit%",
        "barrel_pct": "Barrel%",
        "xwOBA_diff": "wOBA diff",
    })
    st.dataframe(
        style.style_stats_table(
            display,
            higher_better=["Avg EV", "Max EV", "Hard-Hit%", "Barrel%", "xBA", "xSLG", "wOBA diff"],
            team_col="Tm",
            team_color_fn=teams.color_for_abbr,
            precision={
                "Avg EV": "{:.1f}", "Max EV": "{:.1f}", "Hard-Hit%": "{:.1f}", "Barrel%": "{:.1f}",
                "xBA": "{:.3f}", "xSLG": "{:.3f}", "wOBA diff": "{:+.3f}",
            },
        ),
        column_config=style.pin_first_column(display),
        use_container_width=True,
        height=600,
    )

    st.subheader("Exit Velocity vs. Barrel Rate")
    chart_df = filtered.dropna(subset=["avg_exit_velo", "barrel_pct"])
    fig = px.scatter(
        chart_df, x="avg_exit_velo", y="barrel_pct", size="HR", color="OPS",
        hover_name="Name", color_continuous_scale=style.BLUE_SCALE,
        labels={"avg_exit_velo": "Avg Exit Velocity (mph)", "barrel_pct": "Barrel %"},
    )
    fig.update_layout(
        height=450, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color=style.CHART_TEXT,
    )
    st.plotly_chart(fig, use_container_width=True)

with bb_tab:
    st.caption(
        "Pull/straight/oppo crossed with ground vs. air, plus a line-drive-only cut. Pulling the ball "
        "in the AIR is how a hitter gets to his power (the pull-side pole, the gap); pulling on the "
        "GROUND is mostly weak rollover contact. The Air and Ground columns come straight from Statcast; "
        "the Line-Drive columns are our own estimate from raw Statcast spray angle (not an official "
        "Statcast stat, since Statcast's own leaderboard has no line-drive-specific cross at all), "
        "typically accurate to within a few percentage points — see ingest/line_drive_direction.py."
    )
    # Each trio has its own presence gate and its own backfill schedule —
    # air/gb comes from fetch_batted_ball_profile (nightly-eligible), LD
    # from the separate occasional line_drive_direction.py backfill — so
    # build the column list from whichever are actually in the DB right
    # now rather than requiring all 9, which would blank the whole tab
    # over one trio not having run yet.
    _bb_groups = [
        ("Air", ["pull_air_rate", "straight_air_rate", "oppo_air_rate"]),
        ("GB", ["pull_gb_rate", "straight_gb_rate", "oppo_gb_rate"]),
        ("LD", ["pull_ld_rate", "straight_ld_rate", "oppo_ld_rate"]),
    ]
    _bb_cols = [c for _, cols in _bb_groups for c in cols if c in table_rows.columns]
    if not _bb_cols:
        st.caption("Batted-ball direction data isn't in the database yet for this season — it fills in on the next data refresh.")
    else:
        _bb_rows = table_rows.dropna(subset=_bb_cols, how="all")
        display = teams.add_team_abbr(_bb_rows)[["Name", "Age", "Tm", "PA"] + _bb_cols].copy()
        display[_bb_cols] = display[_bb_cols] * 100  # stored as fractions, not percentages
        display = display.rename(columns={
            "pull_air_rate": "Pull-Air%", "straight_air_rate": "Straight-Air%", "oppo_air_rate": "Oppo-Air%",
            "pull_gb_rate": "Pull-GB%", "straight_gb_rate": "Straight-GB%", "oppo_gb_rate": "Oppo-GB%",
            "pull_ld_rate": "Pull-LD%", "straight_ld_rate": "Straight-LD%", "oppo_ld_rate": "Oppo-LD%",
        })
        st.dataframe(
            style.style_stats_table(
                display,
                higher_better=[c for c in ("Pull-Air%", "Pull-LD%") if c in display.columns],
                lower_better=[c for c in ("Pull-GB%",) if c in display.columns],
                team_col="Tm",
                team_color_fn=teams.color_for_abbr,
                precision={c: "{:.1f}" for c in display.columns if c.endswith("%")},
            ),
            column_config=style.pin_first_column(display),
            use_container_width=True,
            height=600,
        )

with discipline_tab:
    display = teams.add_team_abbr(table_rows)[
        ["Name", "Age", "Tm", "PA", "chase_pct", "bat_speed", "xISO", "xOBP"]
    ].rename(columns={"chase_pct": "Chase%", "bat_speed": "Bat Speed"})
    st.dataframe(
        style.style_stats_table(
            display,
            higher_better=["Bat Speed", "xISO", "xOBP"],
            lower_better=["Chase%"],
            team_col="Tm",
            team_color_fn=teams.color_for_abbr,
            precision={
                "Chase%": "{:.1f}", "Bat Speed": "{:.1f}", "xISO": "{:.3f}", "xOBP": "{:.3f}",
            },
        ),
        column_config=style.pin_first_column(display),
        use_container_width=True,
        height=600,
    )

# Stats where a LOWER number is the good direction — drives the color
# gradient in the Custom Leaderboard. Anything not listed colors high=green.
_BATTING_LOWER_BETTER = {"K_PCT", "SO", "CS", "chase_pct", "hp_to_1b"}

with custom_tab:
    st.caption(
        "Build your own leaderboard — pick any stats we track, in any combination, sorted however "
        "you like. The team/PA/league/age/stat filters above all apply here too."
    )
    chosen = st.multiselect(
        "Stats to show",
        numeric_stats,
        default=["Age", "PA", "HR", "OPS", "wOBA", "WAR"],
        format_func=_stat_label,
        key="bat_custom_cols",
    )
    if not chosen:
        st.info("Pick at least one stat to build a leaderboard.")
    else:
        ccol1, ccol2 = st.columns(2)
        with ccol1:
            custom_sort = st.selectbox("Sort by", chosen, format_func=_stat_label, key="bat_custom_sort")
        with ccol2:
            custom_order = st.radio(
                "Order", ["High → Low", "Low → High"], horizontal=True, key="bat_custom_order",
            )
        display = teams.add_team_abbr(table_rows)[["Name", "Tm"] + chosen]
        display = display.sort_values(
            custom_sort, ascending=(custom_order == "Low → High"), na_position="last",
        ).reset_index(drop=True)
        st.dataframe(
            style.style_stats_table(
                display.rename(columns=_stat_label),
                higher_better=[_stat_label(c) for c in chosen if c not in _BATTING_LOWER_BETTER],
                lower_better=[_stat_label(c) for c in chosen if c in _BATTING_LOWER_BETTER],
                team_col="Tm",
                team_color_fn=teams.color_for_abbr,
            ),
            column_config=style.pin_first_column(display.rename(columns=_stat_label)),
            use_container_width=True,
            height=600,
        )

with explore_tab:
    st.caption("Pick any two stats to plot against each other, sized by PA and colored by OPS.")
    axis_options = [
        "HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS", "ISO", "BABIP", "K_PCT", "BB_PCT",
        "wOBA", "xwOBA", "avg_exit_velo", "max_exit_velo", "hard_hit_pct", "barrel_pct", "xBA", "xSLG",
        "contact_pct", "chase_pct", "bat_speed", "xISO", "xOBP",
    ]
    ecol1, ecol2 = st.columns(2)
    with ecol1:
        x_stat = st.selectbox("X axis", axis_options, index=axis_options.index("avg_exit_velo"))
    with ecol2:
        y_stat = st.selectbox("Y axis", axis_options, index=axis_options.index("barrel_pct"))

    chart_df = filtered.dropna(subset=[x_stat, y_stat])
    fig = px.scatter(
        chart_df, x=x_stat, y=y_stat, size="PA", color="OPS",
        hover_name="Name", color_continuous_scale=style.BLUE_SCALE,
    )
    fig.update_layout(
        height=500, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color=style.CHART_TEXT,
    )
    st.plotly_chart(fig, use_container_width=True)
