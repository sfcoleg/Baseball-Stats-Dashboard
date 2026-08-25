import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import prefs
import style
import teams

st.set_page_config(page_title="Fielding | Diamond Metrics", layout="wide")
st.title("Fielding Stats")
style.glossary_link()

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

seasons = db.get_seasons("fielding")
season = st.selectbox("Season", seasons, index=prefs.default_season_index(seasons))
fielding = db.load_fielding(season, db.db_mtime())

col1, col2, col3 = st.columns(3)
with col1:
    team_options = ["All"] + sorted(fielding["Tm"].dropna().unique().tolist())
    team = st.selectbox("Team", team_options)
with col2:
    positions = ["All"] + sorted(fielding["Pos"].dropna().unique().tolist())
    position = st.selectbox("Position", positions)
with col3:
    # fielding's Tm is a nickname (e.g. "Yankees"), not an abbreviation —
    # unlike batting/pitching there's no Lev column to read the league off
    # directly, so this resolves nickname -> abbr -> league per row instead.
    league = st.selectbox("League", ["All", "AL", "NL"])

filtered = fielding
if team != "All":
    filtered = filtered[filtered["Tm"] == team]
if position != "All":
    filtered = filtered[filtered["Pos"] == position]
if league != "All":
    filtered = filtered[
        filtered["Tm"].map(lambda nick: teams.league_for_abbr(teams.team_meta_from_nickname(nick)[0])) == league
    ]
filtered = filtered.sort_values("OAA", ascending=False).reset_index(drop=True)

table_rows = filtered
st.caption(f"{len(filtered)} players match filters.")
display = teams.add_team_abbr_from_nickname(table_rows)[
    ["Name", "Tm", "Pos", "OAA", "FRP", "success_rate",
     "adj_estimated_success_rate_formatted", "diff_success_rate_formatted", "arm_strength"]
].rename(columns={
    "success_rate": "Success Rate",
    "adj_estimated_success_rate_formatted": "Est. Success Rate",
    "diff_success_rate_formatted": "Success Rate +/-",
    "arm_strength": "Arm Strength",
})
st.dataframe(
    style.style_stats_table(
        display,
        higher_better=["OAA", "FRP", "Arm Strength"],
        team_col="Tm",
        team_color_fn=teams.color_for_abbr,
        precision={"Arm Strength": "{:.1f}"},
    ),
    use_container_width=True,
    height=600,
)

# --- Catcher defense --------------------------------------------------------
# The two catcher skills the table above misses entirely — framing and
# controlling the running game. Data from catcher_framing/catcher_poptime
# (ingest/pitch_lab.py backfill + nightly refresh).
framing = db.load_catcher_framing(season, db.db_mtime())
poptime = db.load_catcher_poptime(season, db.db_mtime())

if not framing.empty:
    style.colored_header("Catcher Framing", "pitching")
    fr = framing.sort_values("framing_runs", ascending=False).copy()
    # framing_pct is stored as a 0-1 shadow-zone strike rate — show as a percentage.
    if fr["framing_pct"].max() <= 1:
        fr["framing_pct"] = fr["framing_pct"] * 100
    fr_disp = fr[["Name", "pitches", "framing_runs", "framing_pct"]].rename(columns={
        "Name": "Catcher", "pitches": "Pitches", "framing_runs": "Framing Runs",
        "framing_pct": "Strike Rate %",
    })
    st.dataframe(
        style.style_stats_table(
            fr_disp,
            higher_better=["Framing Runs", "Strike Rate %"],
            precision={"Framing Runs": "{:+.1f}", "Strike Rate %": "{:.1f}"},
        ),
        use_container_width=True, height=420, hide_index=True,
    )

if not poptime.empty:
    style.colored_header("Catcher Throwing", "fielding")
    pt = poptime.sort_values("pop_2b").copy()
    pt_disp = pt[["Name", "age", "pop_2b", "pop_2b_count", "pop_3b", "exchange_time", "arm"]].rename(columns={
        "Name": "Catcher", "age": "Age", "pop_2b": "Pop 2B (s)", "pop_2b_count": "2B Attempts",
        "pop_3b": "Pop 3B (s)", "exchange_time": "Exchange (s)", "arm": "Arm (mph)",
    })
    st.dataframe(
        style.style_stats_table(
            pt_disp,
            higher_better=["Arm (mph)"],
            lower_better=["Pop 2B (s)", "Pop 3B (s)", "Exchange (s)"],
            precision={"Pop 2B (s)": "{:.2f}", "Pop 3B (s)": "{:.2f}", "Exchange (s)": "{:.2f}",
                       "Arm (mph)": "{:.1f}"},
        ),
        use_container_width=True, height=420, hide_index=True,
    )

if not framing.empty and not poptime.empty:
    style.colored_header("Framing vs. Throwing", "chart")
    combo = framing.merge(poptime[["mlbID", "pop_2b"]], on="mlbID", how="inner").dropna(
        subset=["framing_runs", "pop_2b"]
    )
    if not combo.empty:
        st.caption(
            "Top-left = complete defensive catchers (elite framing AND a fast pop time). "
            "Bubble size = pitches caught."
        )
        fig = go.Figure(go.Scatter(
            x=combo["pop_2b"], y=combo["framing_runs"], mode="markers",
            marker=dict(
                size=(combo["pitches"] / combo["pitches"].max() * 22) + 6,
                color=combo["framing_runs"], colorscale=style.HEAT_SCALE_R,
                line=dict(width=1, color="rgba(250,250,250,0.35)"), opacity=0.9,
            ),
            hovertext=[
                f"{r['Name']}: {r['framing_runs']:+.1f} framing runs, {r['pop_2b']:.2f}s pop"
                for _, r in combo.iterrows()
            ],
            hoverinfo="text",
        ))
        fig.add_hline(y=0, line_color="rgba(154,163,181,0.5)", line_width=1, line_dash="dash")
        fig.add_vline(x=2.0, line_color="rgba(154,163,181,0.5)", line_width=1, line_dash="dash",
                      annotation_text="league avg pop", annotation_font_color=style.CHART_DIM)
        fig.update_xaxes(title="Pop Time to 2B (s) — lower is better", autorange="reversed",
                         gridcolor="rgba(74,82,102,0.25)", color=style.CHART_DIM)
        fig.update_yaxes(title="Framing Runs", gridcolor="rgba(74,82,102,0.25)", color=style.CHART_DIM)
        fig.update_layout(
            height=520, margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=style.CHART_TEXT,
        )
        st.plotly_chart(fig, use_container_width=True)
