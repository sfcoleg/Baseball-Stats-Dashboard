import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Custom Rankings | Sabermetrics Dashboard", layout="wide")
st.title("Custom Rankings")
st.caption(
    "Build your own leaderboard by weighting the stats you care about. Each stat is converted to a "
    "z-score (standard deviations from the league-average qualified player) before weighting, so a "
    "weight of 2 on OBP and 1 on HR means OBP counts twice as much toward the composite score — "
    "regardless of the stats' different scales."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
seasons = db.get_seasons("batting")
season = st.selectbox("Season", seasons, index=0)

role = st.radio("Player type", ["Batters", "Pitchers"], horizontal=True)


def zscore(series):
    std = series.std()
    if std == 0 or pd.isna(std):
        return series * 0
    return (series - series.mean()) / std


if role == "Batters":
    batting = db.load_batting(season, mtime)
    pool = batting[batting["PA"] >= 50].copy()
    stat_options = {
        "HR": ("Home Runs", False), "OBP": ("On-Base %", False), "SLG": ("Slugging %", False),
        "SB": ("Stolen Bases", False), "BB_PCT": ("Walk %", False), "K_PCT": ("Strikeout %", True),
        "wOBA": ("wOBA", False), "barrel_pct": ("Barrel %", False),
    }
else:
    pitching = db.load_pitching(season, mtime)
    pool = pitching[pitching["IP"] >= 20].copy()
    stat_options = {
        "K_9": ("K/9", False), "BB_9": ("BB/9", True), "ERA": ("ERA", True),
        "WHIP": ("WHIP", True), "SV": ("Saves", False), "FIP": ("FIP", True),
    }

st.subheader("Weights")
weight_cols = st.columns(4)
weights = {}
for i, (col, (label, lower_is_better)) in enumerate(stat_options.items()):
    with weight_cols[i % 4]:
        weights[col] = st.slider(label, 0, 5, 1)

active_weights = {k: w for k, w in weights.items() if w > 0}
if not active_weights:
    st.info("Set at least one weight above 0 to build a ranking.")
    st.stop()

composite = pd.Series(0.0, index=pool.index)
for col, weight in active_weights.items():
    _, lower_is_better = stat_options[col]
    z = zscore(pool[col].fillna(pool[col].mean()))
    composite += weight * (-z if lower_is_better else z)

pool["Composite Score"] = composite.round(2)
ranked = pool.sort_values("Composite Score", ascending=False).head(30).reset_index(drop=True)

style.colored_header(f"Your Custom {role} Ranking", "batting" if role == "Batters" else "pitching")
display_cols = ["Name", "Tm", "Composite Score"] + list(active_weights.keys())
display = teams.add_team_abbr(ranked)[display_cols]
precision = {col: "{:.3f}" for col in active_weights if col not in ("HR", "SB", "SV")}
precision["Composite Score"] = "{:.2f}"
st.dataframe(
    style.style_stats_table(
        display,
        higher_better=["Composite Score"],
        team_col="Tm",
        team_color_fn=teams.color_for_abbr,
        precision=precision,
    ),
    use_container_width=True,
    height=700,
    hide_index=True,
)
