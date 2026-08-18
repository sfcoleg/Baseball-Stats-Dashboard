"""League Trends — how baseball itself has changed, charted from our own
cached seasons: the offensive environment (2015+), the velocity race and
pitch-mix evolution (2017+, from the pitch arsenal backfill), and framing
(2015+). Aggregates only — no live fetches, everything comes from tables
the nightly ingest already maintains."""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style

st.set_page_config(page_title="League Trends | Diamond Metrics", layout="wide")
st.title("League Trends")
style.glossary_link()
st.caption(
    "The state of the sport, season by season — league-wide rates computed from every player row "
    "we cache. 2020 is the 60-game COVID season; treat its dots gently."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()

_LINE_LAYOUT = dict(
    height=360, margin=dict(l=10, r=10, t=10, b=10),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
)


def _axes(fig, y_title, suffix=""):
    fig.update_xaxes(dtick=1, gridcolor="rgba(74,82,102,0.25)", color="#9AA3B5")
    fig.update_yaxes(title=y_title, ticksuffix=suffix, gridcolor="rgba(74,82,102,0.25)", color="#9AA3B5")
    fig.update_layout(**_LINE_LAYOUT)
    return fig


@st.cache_data(show_spinner=False, max_entries=2)
def league_environment(db_mtime_val: float) -> pd.DataFrame:
    """Per-season league offensive rates, weighted properly (summed
    components, not averaged player rates)."""
    rows = []
    for season in sorted(db.get_seasons("batting")):
        bat = db.load_batting(season, db_mtime_val)
        if bat.empty:
            continue
        s = bat[["PA", "AB", "H", "2B", "3B", "HR", "BB", "SO", "SB"]].sum()
        if not s["PA"] or not s["AB"]:
            continue
        singles = s["H"] - s["2B"] - s["3B"] - s["HR"]
        tb = singles + 2 * s["2B"] + 3 * s["3B"] + 4 * s["HR"]
        rows.append({
            "season": season,
            "AVG": s["H"] / s["AB"],
            "ISO": (tb - s["H"]) / s["AB"],
            "K%": 100 * s["SO"] / s["PA"],
            "BB%": 100 * s["BB"] / s["PA"],
            "HR/600": 600 * s["HR"] / s["PA"],
            "SB/600": 600 * s["SB"] / s["PA"],
        })
    return pd.DataFrame(rows)


env = league_environment(mtime)

# --- Offensive environment --------------------------------------------------
style.colored_header("The Offensive Environment", "batting")
st.caption("League batting average and isolated power — contact quality vs. raw power, by season.")
fig = go.Figure()
fig.add_trace(go.Scatter(x=env["season"], y=env["AVG"], mode="lines+markers", name="League AVG",
                         line=dict(color="#3B82F6", width=2.5)))
fig.add_trace(go.Scatter(x=env["season"], y=env["ISO"], mode="lines+markers", name="League ISO",
                         line=dict(color="#F5B942", width=2.5)))
st.plotly_chart(_axes(fig, "Rate"), use_container_width=True)

style.colored_header("Strikeouts & Walks", "pitching")
st.caption("Share of all plate appearances ending in a strikeout or a walk.")
fig = go.Figure()
fig.add_trace(go.Scatter(x=env["season"], y=env["K%"], mode="lines+markers", name="K%",
                         line=dict(color="#D32F2F", width=2.5)))
fig.add_trace(go.Scatter(x=env["season"], y=env["BB%"], mode="lines+markers", name="BB%",
                         line=dict(color="#7CB342", width=2.5)))
st.plotly_chart(_axes(fig, "% of PA", "%"), use_container_width=True)

style.colored_header("Power & Speed", "headliners")
st.caption("Home runs and stolen bases per 600 plate appearances — watch the 2023 rule changes juice the running game.")
fig = go.Figure()
fig.add_trace(go.Scatter(x=env["season"], y=env["HR/600"], mode="lines+markers", name="HR per 600 PA",
                         line=dict(color="#F5B942", width=2.5)))
fig.add_trace(go.Scatter(x=env["season"], y=env["SB/600"], mode="lines+markers", name="SB per 600 PA",
                         line=dict(color="#26A69A", width=2.5)))
st.plotly_chart(_axes(fig, "Per 600 PA"), use_container_width=True)

# --- The velocity race ------------------------------------------------------
arsenal_all = db.load_pitch_arsenal_all_seasons(mtime)
if not arsenal_all.empty:
    style.colored_header("The Velocity Race", "pitching")
    st.caption(
        "League-average four-seam fastball velocity, weighted by how often each pitcher's four-seamer "
        "actually got used (PA against it). From the pitch arsenal data, 2017 onward."
    )
    ff = arsenal_all[(arsenal_all["pitch_name"] == "4-Seam Fastball")].dropna(subset=["velocity", "pa"])
    velo = ff.groupby("season").apply(
        lambda g: (g["velocity"] * g["pa"]).sum() / g["pa"].sum(), include_groups=False
    ).rename("velo").reset_index()
    fig = go.Figure(go.Scatter(x=velo["season"], y=velo["velo"], mode="lines+markers",
                               line=dict(color="#D32F2F", width=2.5)))
    st.plotly_chart(_axes(fig, "Avg 4-Seam Velo (mph)"), use_container_width=True)

    style.colored_header("Pitch Mix Evolution", "chart")
    st.caption(
        "Each pitch type's share of the league's diet by season (share of plate appearances ended "
        "against it) — the sweeper appears out of nowhere in 2021 and keeps climbing."
    )
    mix = arsenal_all.dropna(subset=["pa"]).groupby(["season", "pitch_name"])["pa"].sum().reset_index()
    totals = mix.groupby("season")["pa"].transform("sum")
    mix["share"] = 100 * mix["pa"] / totals
    # Keep it readable: only pitch types that ever reach 2% share.
    keep = mix[mix["share"] >= 2]["pitch_name"].unique()
    fig = go.Figure()
    for pname in sorted(keep):
        seg = mix[mix["pitch_name"] == pname].sort_values("season")
        fig.add_trace(go.Scatter(
            x=seg["season"], y=seg["share"], mode="lines+markers", name=pname,
            line=dict(color=style.PITCH_COLORS.get(pname, "#9AA3B5"), width=2.5),
        ))
    fig = _axes(fig, "Share of PA", "%")
    fig.update_layout(height=460)
    st.plotly_chart(fig, use_container_width=True)

# --- Framing ----------------------------------------------------------------
framing_rows = []
for season in sorted(db.get_seasons("batting")):
    fr = db.load_catcher_framing(season, mtime)
    if fr is not None and not fr.empty and len(fr) >= 20:
        framing_rows.append({"season": season, "spread": fr["framing_runs"].std(),
                             "best": fr["framing_runs"].max()})
if framing_rows:
    style.colored_header("The Death of Framing Edges", "fielding")
    st.caption(
        "Spread (standard deviation) of catcher framing runs across the league, and the best single "
        "framer's total, by season. As umpires improve and automated-zone pressure looms, the gap "
        "between the best and worst framers keeps shrinking."
    )
    frd = pd.DataFrame(framing_rows)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=frd["season"], y=frd["spread"], mode="lines+markers", name="League spread (std)",
                             line=dict(color="#3B82F6", width=2.5)))
    fig.add_trace(go.Scatter(x=frd["season"], y=frd["best"], mode="lines+markers", name="Best framer's runs",
                             line=dict(color="#F5B942", width=2.5)))
    st.plotly_chart(_axes(fig, "Framing Runs"), use_container_width=True)
