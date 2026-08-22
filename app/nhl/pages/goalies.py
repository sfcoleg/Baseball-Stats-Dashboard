"""NHL Goalies — season stats for every goalie: Standard (box score) and
Advanced (workload + goals saved above expected).
Data: NHL stats API goalie reports + MoneyPuck xGA, via ingest/nhl_refresh.py."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nhl import db as ndb
from nhl import teams as nteams

st.set_page_config(page_title="NHL Goalies | Diamond Metrics", layout="wide")
st.title("Goalies")

mtime = ndb.nhl_db_mtime()
seasons = ndb.goalie_seasons(mtime)
if not seasons:
    st.info("No NHL goalie data yet — run ingest/nhl_refresh.py to backfill.")
    st.stop()

season = st.selectbox("Season", seasons, format_func=ndb.season_label)
goalies = ndb.load_goalies(season, mtime)
goalies["Tm"] = goalies["teamAbbrevs"].map(nteams._primary)
goalies["Age"] = (
    (pd.Timestamp(f"{season}-10-01") - pd.to_datetime(goalies["birthDate"], errors="coerce")).dt.days // 365
)
goalies["gsax"] = goalies["xGA"] - goalies["goalsAgainst"]
ndb.STAT_LABELS.setdefault("gsax", "GSAx")

c1, c2, c3 = st.columns(3)
with c1:
    team = st.selectbox("Team", ["All"] + sorted(goalies["Tm"].dropna().unique().tolist()))
with c2:
    min_gp = st.slider("Minimum GP", 0, int(goalies["gamesPlayed"].max()), 10)
with c3:
    sort_by = st.selectbox(
        "Sort by", ["wins", "savePct", "goalsAgainstAverage", "gsax", "qualityStartsPct", "shutouts"],
        format_func=lambda c: ndb.STAT_LABELS.get(c, c),
    )

filtered = goalies[goalies["gamesPlayed"] >= min_gp]
if team != "All":
    filtered = filtered[filtered["Tm"] == team]
ascending = sort_by == "goalsAgainstAverage"
filtered = filtered.sort_values(sort_by, ascending=ascending).reset_index(drop=True)
st.caption(f"{len(filtered)} goalies match filters.")


def _table(cols, higher_better=(), lower_better=(), precision=None, height=560):
    present = [c for c in cols if c in filtered.columns]
    display = filtered[present].rename(columns=ndb.STAT_LABELS)
    st.dataframe(
        style.style_stats_table(
            display,
            higher_better=[ndb.STAT_LABELS.get(c, c) for c in higher_better if c in present],
            lower_better=[ndb.STAT_LABELS.get(c, c) for c in lower_better if c in present],
            team_col="Tm", team_color_fn=nteams.color_for_abbr,
            precision={ndb.STAT_LABELS.get(k, k): v for k, v in (precision or {}).items()},
        ),
        use_container_width=True, height=height, hide_index=True,
    )


std_tab, adv_tab = st.tabs(["Standard", "Advanced"])

with std_tab:
    _table(
        ["goalieFullName", "Tm", "Age", "shootsCatches", "gamesPlayed", "gamesStarted", "wins",
         "losses", "otLosses", "goalsAgainstAverage", "savePct", "shutouts", "shotsAgainst", "saves"],
        higher_better=["wins", "savePct", "shutouts", "saves"],
        lower_better=["goalsAgainstAverage", "losses", "otLosses"],
        precision={"goalsAgainstAverage": "{:.2f}", "savePct": "{:.1f}"},
    )
    st.caption("SV% and other rate stats shown ×100 (e.g. 91.2 = .912).")

with adv_tab:
    st.caption(
        "Workload and shot quality. xGA (expected goals against) and HD xGA (high-danger xGA) are "
        "from MoneyPuck's public model. GSAx = xGA − actual goals against — positive means the goalie "
        "stopped more than expected. Quality Start% and Complete Game% measure game-to-game "
        "consistency rather than one big total."
    )
    _table(
        ["goalieFullName", "Tm", "gamesPlayed", "xGA", "gsax", "xGA_high_danger", "qualityStart",
         "qualityStartsPct", "completeGames", "completeGamePct", "regulationWins", "goalsFor",
         "goalsForAverage", "shotsAgainstPer60"],
        higher_better=["gsax", "qualityStart", "qualityStartsPct", "completeGamePct", "regulationWins",
                       "goalsFor", "goalsForAverage"],
        lower_better=["xGA", "xGA_high_danger", "shotsAgainstPer60"],
        precision={"xGA": "{:.1f}", "gsax": "{:+.1f}", "xGA_high_danger": "{:.1f}",
                   "qualityStartsPct": "{:.1f}", "completeGamePct": "{:.1f}",
                   "goalsForAverage": "{:.2f}", "shotsAgainstPer60": "{:.1f}"},
    )
