"""NHL Skaters — season stats for every skater: Standard (box score),
Advanced (possession + expected goals), Special Teams, and Shot Types.
Data: NHL stats API reports + MoneyPuck xG, via ingest/nhl_refresh.py."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nhl import db as ndb
from nhl import style as nstyle
from nhl import teams as nteams

st.set_page_config(page_title="NHL Skaters | Diamond Metrics", layout="wide")
st.title("Skaters")
nstyle.glossary_link()

mtime = ndb.nhl_db_mtime()
seasons = ndb.skater_seasons(mtime)
if not seasons:
    st.info("No NHL skater data yet — run ingest/nhl_refresh.py to backfill.")
    st.stop()

season = st.selectbox("Season", seasons, format_func=ndb.season_label)
skaters = ndb.load_skaters(season, mtime)
# SLOT (our own expected-goals model, ingest/nhl_xg.py) — only present for
# seasons whose shot coordinates have been backfilled and scored.
slot = ndb.skater_slot(season, mtime)
has_slot = not slot.empty
if has_slot:
    skaters = skaters.merge(slot, on="playerId", how="left")
skaters["Tm"] = skaters["teamAbbrevs"].map(nteams._primary)
# Age at the season's traditional Oct 1 reference date.
skaters["Age"] = (
    (pd.Timestamp(f"{season}-10-01") - pd.to_datetime(skaters["birthDate"], errors="coerce")).dt.days // 365
)

c1, c2, c3, c4 = st.columns(4)
with c1:
    team = st.selectbox("Team", ["All"] + sorted(skaters["Tm"].dropna().unique().tolist()))
with c2:
    pos = st.selectbox("Position", ["All", "Forwards", "Defense", "C", "L", "R", "D"])
with c3:
    min_gp = st.slider("Minimum GP", 0, int(skaters["gamesPlayed"].max()), 20)
with c4:
    sort_options = ["points", "goals", "assists", "ixG"]
    if has_slot:
        sort_options += ["slot_xg", "slot_above"]
    sort_options += ["xGF_pct_5v5", "satPercentage", "pointsPer605v5", "hits",
                     "blockedShots", "timeOnIcePerGame"]
    sort_by = st.selectbox("Sort by", sort_options,
                           format_func=lambda c: ndb.STAT_LABELS.get(c, c))

filtered = skaters[skaters["gamesPlayed"] >= min_gp]
if team != "All":
    filtered = filtered[filtered["Tm"] == team]
if pos == "Forwards":
    filtered = filtered[filtered["positionCode"].isin(["C", "L", "R"])]
elif pos == "Defense":
    filtered = filtered[filtered["positionCode"] == "D"]
elif pos != "All":
    filtered = filtered[filtered["positionCode"] == pos]
filtered = filtered.sort_values(sort_by, ascending=False).reset_index(drop=True)
st.caption(f"{len(filtered)} skaters match filters.")


def _table(cols, higher_better=(), lower_better=(), precision=None, height=600):
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


std_tab, adv_tab, st_tab, shot_tab = st.tabs(["Standard", "Advanced", "Special Teams", "Shot Types"])

with std_tab:
    _table(
        ["skaterFullName", "Tm", "positionCode", "Age", "gamesPlayed", "goals", "assists", "points",
         "pointsPerGame", "plusMinus", "penaltyMinutes", "ppGoals", "ppPoints", "shGoals",
         "gameWinningGoals", "shots", "shootingPct", "timeOnIcePerGame", "faceoffWinPct"],
        higher_better=["goals", "assists", "points", "pointsPerGame", "plusMinus", "ppGoals", "ppPoints",
                       "shGoals", "gameWinningGoals", "shots", "shootingPct", "faceoffWinPct"],
        precision={"pointsPerGame": "{:.2f}", "shootingPct": "{:.1f}", "timeOnIcePerGame": "{:.0f}",
                   "faceoffWinPct": "{:.1f}"},
    )

with adv_tab:
    filtered["finishing"] = filtered["goals"] - filtered["ixG"]
    ndb.STAT_LABELS.setdefault("finishing", "G − xG")
    slot_cols = ["slot_xg", "slot_above"] if has_slot else []
    _table(
        ["skaterFullName", "Tm", "positionCode", "gamesPlayed", "goals", "ixG", "finishing",
         *slot_cols,
         "ixG_high_danger", "xGF_pct_5v5", "office_xGF_pct", "satPercentage", "satRelative",
         "usatPercentage", "skaterShootingPlusSavePct5v5", "zoneStartPct5v5", "goalsPer605v5",
         "pointsPer605v5", "primaryAssistsPer605v5", "hits", "blockedShots", "takeaways",
         "giveaways", "penaltiesDrawn", "netPenaltiesPer60"],
        higher_better=[*slot_cols, "ixG", "finishing", "ixG_high_danger", "xGF_pct_5v5", "satPercentage",
                       "satRelative", "usatPercentage", "goalsPer605v5", "pointsPer605v5",
                       "primaryAssistsPer605v5", "hits", "blockedShots", "takeaways",
                       "penaltiesDrawn", "netPenaltiesPer60"],
        lower_better=["giveaways"],
        precision={"ixG": "{:.1f}", "finishing": "{:+.1f}", "slot_xg": "{:.1f}",
                   "slot_above": "{:+.1f}", "ixG_high_danger": "{:.1f}",
                   "xGF_pct_5v5": "{:.1f}", "office_xGF_pct": "{:.1f}", "satPercentage": "{:.1f}",
                   "satRelative": "{:+.1f}", "usatPercentage": "{:.1f}",
                   "skaterShootingPlusSavePct5v5": "{:.1f}", "zoneStartPct5v5": "{:.1f}",
                   "goalsPer605v5": "{:.2f}", "pointsPer605v5": "{:.2f}",
                   "primaryAssistsPer605v5": "{:.2f}", "netPenaltiesPer60": "{:+.2f}"},
    )

with st_tab:
    _table(
        ["skaterFullName", "Tm", "positionCode", "gamesPlayed", "ppGoals", "ppAssists", "ppPoints",
         "ppShots", "ppShootingPct", "ppGoalsPer60", "ppPointsPer60", "ppTimeOnIcePerGame",
         "ppTimeOnIcePctPerGame", "shGoals", "shAssists", "shPoints", "shPointsPer60",
         "shTimeOnIcePerGame", "shTimeOnIcePctPerGame", "ppGoalsAgainstPer60"],
        higher_better=["ppGoals", "ppAssists", "ppPoints", "ppShots", "ppShootingPct", "ppGoalsPer60",
                       "ppPointsPer60", "ppTimeOnIcePctPerGame", "shGoals", "shAssists", "shPoints",
                       "shPointsPer60", "shTimeOnIcePctPerGame"],
        lower_better=["ppGoalsAgainstPer60"],
        precision={"ppShootingPct": "{:.1f}", "ppGoalsPer60": "{:.2f}", "ppPointsPer60": "{:.2f}",
                   "ppTimeOnIcePerGame": "{:.0f}", "ppTimeOnIcePctPerGame": "{:.1f}",
                   "shPointsPer60": "{:.2f}", "shTimeOnIcePerGame": "{:.0f}",
                   "shTimeOnIcePctPerGame": "{:.1f}", "ppGoalsAgainstPer60": "{:.2f}"},
    )

with shot_tab:
    _table(
        ["skaterFullName", "Tm", "positionCode", "goals", "goalsWrist", "goalsSnap", "goalsSlap",
         "goalsBackhand", "goalsTipIn", "goalsDeflected", "goalsWrapAround", "shotsOnNetWrist",
         "shotsOnNetSnap", "shotsOnNetSlap", "shootingPctWrist", "shootingPctSnap", "shootingPctSlap",
         "shootingPctBackhand", "shootingPctTipIn"],
        higher_better=["goals", "goalsWrist", "goalsSnap", "goalsSlap", "goalsBackhand", "goalsTipIn",
                       "goalsDeflected", "shootingPctWrist", "shootingPctSnap", "shootingPctSlap",
                       "shootingPctBackhand", "shootingPctTipIn"],
        precision={"shootingPctWrist": "{:.1f}", "shootingPctSnap": "{:.1f}", "shootingPctSlap": "{:.1f}",
                   "shootingPctBackhand": "{:.1f}", "shootingPctTipIn": "{:.1f}"},
    )
