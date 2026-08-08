import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Research | Diamond Metrics", layout="wide")
st.title("Research")
st.caption(
    "Sabermetric analysis tools: stack filters across any stat, test whether two stats actually "
    "correlate, and see how much a stat sticks year over year."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
seasons = db.get_seasons("batting")

BATTING_STATS = [
    "Age", "G", "PA", "AB", "R", "H", "2B", "3B", "HR", "RBI", "BB", "SO", "SB", "CS", "BA", "OBP", "SLG",
    "OPS", "ISO", "BABIP", "K_PCT", "BB_PCT", "wOBA", "xwOBA", "avg_exit_velo", "max_exit_velo",
    "hard_hit_pct", "barrel_pct", "xBA", "xSLG", "OPS_plus", "wRC_plus", "WAR", "sprint_speed",
]
PITCHING_STATS = [
    "Age", "G", "GS", "W", "L", "SV", "IP", "ERA", "WHIP", "SO", "BB", "HR", "K_9", "BB_9", "K_BB", "FIP",
    "xERA", "BAbip", "GB_FB", "avg_exit_velo_against", "hard_hit_pct_against", "barrel_pct_against",
    "ERA_plus", "WAR",
]

OPS = {
    ">=": lambda s, v: s >= v, "<=": lambda s, v: s <= v,
    ">": lambda s, v: s > v, "<": lambda s, v: s < v, "==": lambda s, v: s == v,
}

screener_tab, corr_tab, stability_tab = st.tabs(["Stat Screener", "Correlation Explorer", "Stat Stability"])

# ------------------------------------------------------------ Stat Screener -
with screener_tab:
    st.caption("Stack any number of conditions across batting or pitching stats, one season at a time.")
    role = st.radio("Player type", ["Batting", "Pitching"], horizontal=True, key="screener_role")
    season = st.selectbox("Season", seasons, index=0, key="screener_season")
    stats_list = BATTING_STATS if role == "Batting" else PITCHING_STATS
    df = db.load_batting(season, mtime) if role == "Batting" else db.load_pitching(season, mtime)

    # Reset filters when switching Batting<->Pitching so a leftover filter
    # can't silently reference a stat that doesn't exist in the new table.
    if st.session_state.get("screener_last_role") != role:
        st.session_state["screener_filters"] = [{"stat": stats_list[0], "op": ">=", "value": 0.0}]
        st.session_state["screener_last_role"] = role

    remove_idx = None
    for i, f in enumerate(st.session_state["screener_filters"]):
        c1, c2, c3, c4 = st.columns([3, 1.3, 2, 0.6])
        with c1:
            f["stat"] = st.selectbox(
                "Stat", stats_list, index=stats_list.index(f["stat"]), key=f"screener_stat_{i}",
                label_visibility="collapsed" if i else "visible",
            )
        with c2:
            f["op"] = st.selectbox(
                "Op", list(OPS.keys()), index=list(OPS.keys()).index(f["op"]), key=f"screener_op_{i}",
                label_visibility="collapsed" if i else "visible",
            )
        with c3:
            f["value"] = st.number_input(
                "Value", value=float(f["value"]), key=f"screener_val_{i}",
                label_visibility="collapsed" if i else "visible",
            )
        with c4:
            if i == 0:
                st.write("")
            if st.button("✕", key=f"screener_remove_{i}", use_container_width=True):
                remove_idx = i
    if remove_idx is not None:
        st.session_state["screener_filters"].pop(remove_idx)
        st.rerun()

    if st.button("+ Add filter", key="screener_add"):
        st.session_state["screener_filters"].append({"stat": stats_list[0], "op": ">=", "value": 0.0})
        st.rerun()

    mask = pd.Series(True, index=df.index)
    for f in st.session_state["screener_filters"]:
        mask &= OPS[f["op"]](df[f["stat"]], f["value"])
    results = df[mask]

    st.caption(f"{len(results)} player-seasons match.")
    filter_cols = list(dict.fromkeys(f["stat"] for f in st.session_state["screener_filters"]))
    display_cols = ["Name", "Tm"] + [c for c in filter_cols if c not in ("Name", "Tm")]
    display = teams.add_team_abbr(results.sort_values(filter_cols[0], ascending=False))[display_cols]
    st.dataframe(
        style.style_stats_table(display, team_col="Tm", team_color_fn=teams.color_for_abbr),
        use_container_width=True, height=500, hide_index=True,
    )

# ------------------------------------------------------ Correlation Explorer
with corr_tab:
    st.caption(
        "Scatter any two stats against each other with a fitted regression line and R² — a quick way to "
        "test whether a relationship you're assuming is actually there in the data."
    )
    role2 = st.radio("Player type", ["Batting", "Pitching"], horizontal=True, key="corr_role")
    season2 = st.selectbox("Season", seasons, index=0, key="corr_season")
    stats_list2 = BATTING_STATS if role2 == "Batting" else PITCHING_STATS
    df2 = db.load_batting(season2, mtime) if role2 == "Batting" else db.load_pitching(season2, mtime)
    min_col = "PA" if role2 == "Batting" else "IP"
    min_default = 50 if role2 == "Batting" else 20

    min_val = st.slider(f"Minimum {min_col}", 0, int(df2[min_col].max()), min_default, key="corr_min")
    df2 = df2[df2[min_col] >= min_val]

    c1, c2 = st.columns(2)
    with c1:
        x_stat = st.selectbox("X axis", stats_list2, index=0, key="corr_x")
    with c2:
        y_default = 1 if len(stats_list2) > 1 else 0
        y_stat = st.selectbox("Y axis", stats_list2, index=y_default, key="corr_y")

    chart_df = df2.dropna(subset=[x_stat, y_stat])
    if len(chart_df) < 3:
        st.info("Not enough qualifying players for this combination — lower the minimum or pick a different season.")
    else:
        x = chart_df[x_stat].astype(float).to_numpy()
        y = chart_df[y_stat].astype(float).to_numpy()
        slope, intercept = np.polyfit(x, y, 1)
        r = float(np.corrcoef(x, y)[0, 1])

        fig = px.scatter(
            chart_df, x=x_stat, y=y_stat, hover_name="Name", color_discrete_sequence=["#3B82F6"],
        )
        line_x = np.linspace(x.min(), x.max(), 100)
        fig.add_trace(go.Scatter(
            x=line_x, y=slope * line_x + intercept, mode="lines",
            line=dict(color="#F5B942", width=3), showlegend=False,
        ))
        fig.update_layout(
            height=460, margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA",
        )
        st.plotly_chart(fig, use_container_width=True)

        m1, m2, m3 = st.columns(3)
        m1.metric("R²", f"{r ** 2:.3f}")
        m2.metric("Correlation (r)", f"{r:.3f}")
        m3.metric("Sample size", len(chart_df))

# ---------------------------------------------------------- Stat Stability -
with stability_tab:
    st.caption(
        "How much a stat 'sticks' year to year — the classic sabermetric signal-vs-noise question. "
        "Computed as the season-N to season-(N+1) correlation among players who qualified in both "
        "years, at increasing minimum-sample thresholds. A skill-driven stat should show a rising, "
        "fairly high correlation as the minimum sample grows; a mostly-luck stat stays low no matter "
        "how much playing time you require."
    )
    role3 = st.radio("Player type", ["Batting", "Pitching"], horizontal=True, key="stability_role")
    stats_list3 = BATTING_STATS if role3 == "Batting" else PITCHING_STATS
    default_stat = "OPS" if role3 == "Batting" else "ERA"
    stat3 = st.selectbox("Stat", stats_list3, index=stats_list3.index(default_stat), key="stability_stat")
    min_col3 = "PA" if role3 == "Batting" else "IP"
    thresholds = [50, 100, 150, 250, 350, 500] if role3 == "Batting" else [20, 40, 60, 90, 120, 160]

    table_name = "batting" if role3 == "Batting" else "pitching"
    history_df = db.load_stat_across_seasons(table_name, stat3, min_col3, mtime)
    by_season = {s: g for s, g in history_df.groupby("season")}

    rows = []
    for th in thresholds:
        pair_frames = []
        for s in seasons:
            if s not in by_season or (s + 1) not in by_season:
                continue
            cur = by_season[s][by_season[s][min_col3] >= th][["mlbID", stat3]].rename(columns={stat3: "y1"})
            nxt = by_season[s + 1][by_season[s + 1][min_col3] >= th][["mlbID", stat3]].rename(columns={stat3: "y2"})
            merged = cur.merge(nxt, on="mlbID")
            if not merged.empty:
                pair_frames.append(merged)
        if not pair_frames:
            continue
        pairs = pd.concat(pair_frames, ignore_index=True)
        if len(pairs) >= 10:
            r = float(np.corrcoef(pairs["y1"], pairs["y2"])[0, 1])
            rows.append({f"Min {min_col3}": th, "Year-over-year r": round(r, 3), "Pairs": len(pairs)})

    if not rows:
        st.info("Not enough year-over-year pairs to compute stability for this stat.")
    else:
        stability_df = pd.DataFrame(rows)
        fig = px.bar(
            stability_df, x=f"Min {min_col3}", y="Year-over-year r", text="Pairs",
            color_discrete_sequence=["#3B82F6"],
        )
        fig.update_layout(
            height=380, margin=dict(l=0, r=0, t=10, b=0), yaxis_range=[-1, 1],
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA",
        )
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(stability_df, use_container_width=True, hide_index=True)
