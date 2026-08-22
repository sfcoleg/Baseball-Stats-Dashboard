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
from nhl import teams as nteams

st.set_page_config(page_title="NHL Skaters | Diamond Metrics", layout="wide")
st.title("Skaters")

mtime = ndb.nhl_db_mtime()
seasons = ndb.skater_seasons(mtime)
if not seasons:
    st.info("No NHL skater data yet — run ingest/nhl_refresh.py to backfill.")
    st.stop()

season = st.selectbox("Season", seasons, format_func=ndb.season_label)
skaters = ndb.load_skaters(season, mtime)
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
    sort_by = st.selectbox(
        "Sort by", ["points", "goals", "assists", "ixG", "xGF_pct_5v5", "satPercentage",
                    "pointsPer605v5", "hits", "blockedShots", "timeOnIcePerGame"],
        format_func=lambda c: ndb.STAT_LABELS.get(c, c),
    )

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
    st.caption("TOI/GP in seconds per game (e.g. 1200 = 20:00). FO% blank for non-centers.")

with adv_tab:
    st.caption(
        "Possession and expected goals. CF%/FF% and the per-60 rates are 5v5 from the NHL; "
        "xG (a skater's own expected goals) and xGF% (share of expected goals while on ice) are "
        "from MoneyPuck's public model. G − xG = finishing above expectation. PDO = on-ice "
        "shooting% + save% (luck gauge, regresses to ~100)."
    )
    filtered["finishing"] = filtered["goals"] - filtered["ixG"]
    ndb.STAT_LABELS.setdefault("finishing", "G − xG")
    _table(
        ["skaterFullName", "Tm", "positionCode", "gamesPlayed", "goals", "ixG", "finishing",
         "ixG_high_danger", "xGF_pct_5v5", "office_xGF_pct", "satPercentage", "satRelative",
         "usatPercentage", "skaterShootingPlusSavePct5v5", "zoneStartPct5v5", "goalsPer605v5",
         "pointsPer605v5", "primaryAssistsPer605v5", "hits", "blockedShots", "takeaways",
         "giveaways", "penaltiesDrawn", "netPenaltiesPer60"],
        higher_better=["ixG", "finishing", "ixG_high_danger", "xGF_pct_5v5", "satPercentage",
                       "satRelative", "usatPercentage", "goalsPer605v5", "pointsPer605v5",
                       "primaryAssistsPer605v5", "hits", "blockedShots", "takeaways",
                       "penaltiesDrawn", "netPenaltiesPer60"],
        lower_better=["giveaways"],
        precision={"ixG": "{:.1f}", "finishing": "{:+.1f}", "ixG_high_danger": "{:.1f}",
                   "xGF_pct_5v5": "{:.1f}", "office_xGF_pct": "{:.1f}", "satPercentage": "{:.1f}",
                   "satRelative": "{:+.1f}", "usatPercentage": "{:.1f}",
                   "skaterShootingPlusSavePct5v5": "{:.1f}", "zoneStartPct5v5": "{:.1f}",
                   "goalsPer605v5": "{:.2f}", "pointsPer605v5": "{:.2f}",
                   "primaryAssistsPer605v5": "{:.2f}", "netPenaltiesPer60": "{:+.2f}"},
    )

with st_tab:
    st.caption("Power play and penalty kill production, rates per 60, and each skater's share of the team's PP/PK time.")
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
    st.caption("Goals, shots on net, and shooting % by shot type — who lives on the wrister and who tips everything.")
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
