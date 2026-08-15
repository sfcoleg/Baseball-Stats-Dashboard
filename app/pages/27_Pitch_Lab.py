"""Pitch Lab — league-wide pitch-level research: per-pitcher arsenals,
movement maps, per-pitch leaderboards, and year-over-year arsenal changes.
Data from the pitch_arsenal table (ingest/pitch_lab.py backfill + nightly
refresh_data.fetch_pitch_arsenal)."""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style

st.set_page_config(page_title="Pitch Lab | Diamond Metrics", layout="wide")
st.title("Pitch Lab")
style.glossary_link()
st.caption(
    "Pitch-level Statcast research — what every pitcher throws, how it moves, and what hitters do "
    "against it. IVB = induced vertical break (rise vs. a gravity-only ball, inches). HB = horizontal "
    "break (inches, catcher's view: negative = toward a righty batter)."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
all_seasons_df = db.load_pitch_arsenal_all_seasons(mtime)
if all_seasons_df.empty:
    st.info("No pitch arsenal data yet — run ingest/pitch_lab.py to backfill.")
    st.stop()

seasons = sorted(all_seasons_df["season"].unique(), reverse=True)
season = st.selectbox("Season", seasons)
arsenal = all_seasons_df[all_seasons_df["season"] == season]

PITCH_COLORS = {
    "4-Seam Fastball": "#D32F2F", "Sinker": "#F57C00", "Cutter": "#FBC02D",
    "Slider": "#7CB342", "Sweeper": "#26A69A", "Slurve": "#4DB6AC",
    "Curveball": "#3B82F6", "Knuckle Curve": "#5C6BC0", "Changeup": "#AB47BC",
    "Splitter": "#EC407A", "Knuckleball": "#8D6E63", "Screwball": "#78909C",
    "Forkball": "#EC407A", "Eephus": "#9AA3B5",
}

_ARSENAL_TABLE_COLS = {
    "pitch_name": "Pitch", "usage_pct": "Usage %", "velocity": "Velo",
    "spin_rate": "Active Spin %", "vert_break": "IVB", "horz_break": "HB",
    "whiff_pct": "Whiff %", "ba": "BA", "slg": "SLG", "woba": "wOBA",
    "hard_hit_percent": "Hard-Hit %", "run_value_per_100": "RV/100",
}
_ARSENAL_PRECISION = {
    "Usage %": "{:.1f}", "Velo": "{:.1f}", "Active Spin %": "{:.1f}", "IVB": "{:.1f}",
    "HB": "{:.1f}", "Whiff %": "{:.1f}", "BA": "{:.3f}", "SLG": "{:.3f}",
    "wOBA": "{:.3f}", "Hard-Hit %": "{:.1f}", "RV/100": "{:+.1f}",
}

# --- Pitcher arsenal deep dive ---------------------------------------------
style.colored_header("Pitcher Arsenal", "pitching")
by_pitches = arsenal.groupby(["mlbID", "Name"], as_index=False)["usage_pct"].count()
names = arsenal.groupby("Name")["mlbID"].first()
pitcher_name = st.selectbox("Pitcher", sorted(names.index.tolist()))
mine = arsenal[arsenal["Name"] == pitcher_name].sort_values("usage_pct", ascending=False)

if not mine.empty:
    display = mine[list(_ARSENAL_TABLE_COLS)].rename(columns=_ARSENAL_TABLE_COLS)
    st.dataframe(
        style.style_stats_table(
            display,
            higher_better=["Whiff %", "RV/100"],
            lower_better=["BA", "SLG", "wOBA", "Hard-Hit %"],
            precision=_ARSENAL_PRECISION,
        ),
        use_container_width=True, hide_index=True,
    )
    st.caption(
        "RV/100 = run value per 100 pitches from the pitcher's perspective — positive is good "
        "(runs saved). BA/SLG/wOBA = what hitters produce against that pitch."
    )

    # Movement plot: this pitcher's pitches on the league's movement cloud.
    plot_season = arsenal.dropna(subset=["vert_break", "horz_break"])
    fig = go.Figure()
    for pname, seg in plot_season.groupby("pitch_name"):
        fig.add_trace(go.Scatter(
            x=seg["horz_break"], y=seg["vert_break"], mode="markers", name=pname,
            marker=dict(size=5, color=PITCH_COLORS.get(pname, "#9AA3B5"), opacity=0.18),
            hoverinfo="skip", showlegend=False,
        ))
    mine_mv = mine.dropna(subset=["vert_break", "horz_break"])
    for _, row in mine_mv.iterrows():
        fig.add_trace(go.Scatter(
            x=[row["horz_break"]], y=[row["vert_break"]], mode="markers+text",
            name=row["pitch_name"],
            text=[row["pitch_name"]], textposition="top center",
            textfont=dict(size=11, color="#FAFAFA"),
            marker=dict(size=14, color=PITCH_COLORS.get(row["pitch_name"], "#FAFAFA"),
                        line=dict(width=2, color="#FAFAFA")),
        ))
    fig.add_hline(y=0, line_color="rgba(154,163,181,0.4)", line_width=1)
    fig.add_vline(x=0, line_color="rgba(154,163,181,0.4)", line_width=1)
    fig.update_xaxes(title="Horizontal Break (in)", gridcolor="rgba(74,82,102,0.25)", color="#9AA3B5")
    fig.update_yaxes(title="Induced Vertical Break (in)", gridcolor="rgba(74,82,102,0.25)", color="#9AA3B5")
    fig.update_layout(
        height=480, margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA",
        title=dict(text=f"{pitcher_name} vs. the league's movement cloud", font=dict(size=14)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    st.plotly_chart(fig, use_container_width=True)

# --- Movement map ----------------------------------------------------------
style.colored_header("Movement Map", "chart")
st.caption(
    "Every pitcher's version of one pitch type — movement profiles across the whole league. "
    "Dots far from the pack are the outliers hitters have never seen before."
)
map_pitch = st.selectbox(
    "Pitch type", sorted(arsenal["pitch_name"].dropna().unique().tolist()),
    key="movement_map_pitch",
)
seg = arsenal[(arsenal["pitch_name"] == map_pitch)].dropna(subset=["vert_break", "horz_break"])
if seg.empty:
    st.caption("No movement data for this pitch type.")
else:
    color_by = st.radio("Color by", ["Velocity", "Whiff %"], horizontal=True, key="movement_color")
    color_col = "velocity" if color_by == "Velocity" else "whiff_pct"
    fig = go.Figure(go.Scatter(
        x=seg["horz_break"], y=seg["vert_break"], mode="markers",
        marker=dict(
            size=7, color=seg[color_col], colorscale="RdYlBu_r" if color_col == "velocity" else "Viridis",
            colorbar=dict(title=color_by, tickfont=dict(color="#9AA3B5")), opacity=0.85,
        ),
        hovertext=[
            f"{r['Name']} ({r['pitch_hand']}HP) — {r['velocity']:.1f} mph, "
            f"IVB {r['vert_break']:.1f}\", HB {r['horz_break']:.1f}\", whiff {r['whiff_pct']:.1f}%"
            if pd.notna(r["whiff_pct"]) else f"{r['Name']} — {r['velocity']:.1f} mph"
            for _, r in seg.iterrows()
        ],
        hoverinfo="text",
    ))
    fig.add_hline(y=0, line_color="rgba(154,163,181,0.4)", line_width=1)
    fig.add_vline(x=0, line_color="rgba(154,163,181,0.4)", line_width=1)
    fig.update_xaxes(title="Horizontal Break (in)", gridcolor="rgba(74,82,102,0.25)", color="#9AA3B5")
    fig.update_yaxes(title="Induced Vertical Break (in)", gridcolor="rgba(74,82,102,0.25)", color="#9AA3B5")
    fig.update_layout(
        height=520, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA",
    )
    st.plotly_chart(fig, use_container_width=True)

# --- Pitch leaderboards ----------------------------------------------------
style.colored_header("Pitch Leaderboards", "batting")
lb_col1, lb_col2, lb_col3 = st.columns(3)
with lb_col1:
    lb_pitch = st.selectbox(
        "Pitch type", ["All"] + sorted(arsenal["pitch_name"].dropna().unique().tolist()),
        key="lb_pitch",
    )
with lb_col2:
    lb_metric = st.selectbox(
        "Rank by",
        ["whiff_pct", "run_value_per_100", "velocity", "vert_break", "horz_break", "woba", "usage_pct"],
        format_func=lambda c: {
            "whiff_pct": "Whiff % (nastiest)", "run_value_per_100": "RV/100 (most valuable)",
            "velocity": "Velocity", "vert_break": "IVB (most rise)", "horz_break": "HB (most sweep)",
            "woba": "wOBA against (stingiest)", "usage_pct": "Usage %",
        }[c],
        key="lb_metric",
    )
with lb_col3:
    min_usage = st.slider("Minimum usage %", 0, 50, 10, key="lb_min_usage",
                          help="Filters out show-me pitches a pitcher rarely throws.")

lb = arsenal[arsenal["usage_pct"] >= min_usage]
if lb_pitch != "All":
    lb = lb[lb["pitch_name"] == lb_pitch]
lb = lb.dropna(subset=[lb_metric])
# wOBA-against flatters low; RV/100 is pitcher-perspective (high = good); HB is magnitude.
if lb_metric == "woba":
    lb = lb.sort_values(lb_metric, ascending=True)
elif lb_metric == "horz_break":
    lb = lb.reindex(lb[lb_metric].abs().sort_values(ascending=False).index)
else:
    lb = lb.sort_values(lb_metric, ascending=False)
display = lb.head(30)[["Name", "team", "pitch_name"] + list(
    dict.fromkeys(["usage_pct", "velocity", "vert_break", "horz_break", "whiff_pct", "woba", "run_value_per_100"])
)].rename(columns={
    "Name": "Pitcher", "team": "Tm", "pitch_name": "Pitch", "usage_pct": "Usage %",
    "velocity": "Velo", "vert_break": "IVB", "horz_break": "HB", "whiff_pct": "Whiff %",
    "woba": "wOBA", "run_value_per_100": "RV/100",
})
st.dataframe(
    style.style_stats_table(
        display,
        higher_better=["Whiff %", "RV/100"],
        lower_better=["wOBA"],
        precision={"Usage %": "{:.1f}", "Velo": "{:.1f}", "IVB": "{:.1f}", "HB": "{:.1f}",
                   "Whiff %": "{:.1f}", "wOBA": "{:.3f}", "RV/100": "{:+.1f}"},
    ),
    use_container_width=True, height=500, hide_index=True,
)

# --- Year-over-year arsenal changes ----------------------------------------
style.colored_header("Arsenal Changes", "headliners")
prior_season = season - 1
prior = all_seasons_df[all_seasons_df["season"] == prior_season]
if prior.empty:
    st.caption(f"No {prior_season} data stored, so no year-over-year comparison for {season}.")
else:
    merged = arsenal.merge(
        prior[["mlbID", "pitch_type", "usage_pct", "velocity"]],
        on=["mlbID", "pitch_type"], how="left", suffixes=("", "_prior"),
    )

    tab_velo, tab_new, tab_usage = st.tabs(["Velocity Changes", "New Pitches", "Usage Shifts"])
    with tab_velo:
        st.caption(f"Biggest average-velocity changes on the same pitch, {prior_season} → {season}. Min 10% usage both years.")
        velo = merged.dropna(subset=["velocity", "velocity_prior"])
        velo = velo[(velo["usage_pct"] >= 10) & (velo["usage_pct_prior"] >= 10)].copy()
        velo["velo_change"] = velo["velocity"] - velo["velocity_prior"]
        vel_disp = pd.concat([velo.nlargest(10, "velo_change"), velo.nsmallest(10, "velo_change")])
        vel_disp = vel_disp[["Name", "team", "pitch_name", "velocity_prior", "velocity", "velo_change"]].rename(
            columns={"Name": "Pitcher", "team": "Tm", "pitch_name": "Pitch",
                     "velocity_prior": f"{prior_season} Velo", "velocity": f"{season} Velo", "velo_change": "Change"}
        ).sort_values("Change", ascending=False)
        st.dataframe(
            style.style_stats_table(
                vel_disp, higher_better=["Change"],
                precision={f"{prior_season} Velo": "{:.1f}", f"{season} Velo": "{:.1f}", "Change": "{:+.1f}"},
            ),
            use_container_width=True, hide_index=True,
        )
    with tab_new:
        st.caption(
            f"Pitches thrown at least 5% of the time in {season} that were rare or absent in {prior_season} "
            f"(under 1% usage) — new weapons, ranked by how well they're working."
        )
        pitched_prior = merged["usage_pct_prior"].fillna(0)
        new_pitches = merged[
            (merged["usage_pct"] >= 5) & (pitched_prior < 1)
            & merged["mlbID"].isin(prior["mlbID"].unique())  # pitcher existed last year — not a rookie
        ].sort_values("run_value_per_100", ascending=False)
        if new_pitches.empty:
            st.caption("No qualifying new pitches found.")
        else:
            disp = new_pitches[["Name", "team", "pitch_name", "usage_pct", "velocity", "whiff_pct", "run_value_per_100"]].rename(
                columns={"Name": "Pitcher", "team": "Tm", "pitch_name": "New Pitch", "usage_pct": "Usage %",
                         "velocity": "Velo", "whiff_pct": "Whiff %", "run_value_per_100": "RV/100"}
            )
            st.dataframe(
                style.style_stats_table(
                    disp, higher_better=["Whiff %", "RV/100"],
                    precision={"Usage %": "{:.1f}", "Velo": "{:.1f}", "Whiff %": "{:.1f}", "RV/100": "{:+.1f}"},
                ),
                use_container_width=True, height=420, hide_index=True,
            )
    with tab_usage:
        st.caption(f"Biggest usage-rate shifts on an existing pitch, {prior_season} → {season}.")
        usage = merged.dropna(subset=["usage_pct", "usage_pct_prior"]).copy()
        usage["usage_change"] = usage["usage_pct"] - usage["usage_pct_prior"]
        usage_disp = pd.concat([usage.nlargest(10, "usage_change"), usage.nsmallest(10, "usage_change")])
        usage_disp = usage_disp[["Name", "team", "pitch_name", "usage_pct_prior", "usage_pct", "usage_change"]].rename(
            columns={"Name": "Pitcher", "team": "Tm", "pitch_name": "Pitch",
                     "usage_pct_prior": f"{prior_season} Usage %", "usage_pct": f"{season} Usage %",
                     "usage_change": "Change"}
        ).sort_values("Change", ascending=False)
        st.dataframe(
            style.style_stats_table(
                usage_disp,
                precision={f"{prior_season} Usage %": "{:.1f}", f"{season} Usage %": "{:.1f}", "Change": "{:+.1f}"},
            ),
            use_container_width=True, hide_index=True,
        )
