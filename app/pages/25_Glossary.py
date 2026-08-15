"""Stat glossary — reached via the small info link at the bottom of the
sidebar (see main.py). Plain reference content, grouped to match the
site's own page sections. Player search itself is rendered once globally
by main.py, not per-page, so this doesn't call sidebar.render_search()."""
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import style

st.set_page_config(page_title="Glossary | Diamond Metrics", layout="wide")
st.title("Stat Glossary")
st.caption(
    "Quick definitions for every stat and composite score used across Diamond Metrics — standard "
    "sabermetrics plus our own in-house composites, called out as such below."
)


def _entry(term: str, definition: str):
    st.markdown(f"**{term}** — {definition}")


style.colored_header("Batting", "batting")
_entry("AVG", "Batting average — hits divided by at-bats.")
_entry("OBP", "On-base percentage — how often a plate appearance ends with the batter reaching base (hits, walks, HBP).")
_entry("SLG", "Slugging percentage — total bases per at-bat.")
_entry("OPS", "On-base plus slugging — OBP + SLG, a quick overall offensive gauge.")
_entry("ISO", "Isolated power — SLG minus AVG, extra-base power stripped of raw batting average.")
_entry("BABIP", "Batting average on balls in play — average on everything except home runs and strikeouts.")
_entry("K%", "Strikeout rate — strikeouts per plate appearance.")
_entry("BB%", "Walk rate — walks per plate appearance.")
_entry("wOBA", "Weighted on-base average — like OBP, but weights each way of reaching base by its actual run value.")
_entry("wRC+", "Weighted runs created plus — overall offensive value, park- and league-adjusted, where 100 is league average.")
_entry("OPS+", "OPS adjusted for park and league, where 100 is league average.")
_entry("WAR", "Wins above replacement — estimated total wins a player is worth versus a replacement-level fill-in.")
_entry("xBA / xSLG / xwOBA", "Expected versions of BA/SLG/wOBA — what those numbers \"should\" be based on the quality of contact (exit velocity, launch angle), stripping out defense and luck.")
_entry("xISO / xOBP", "Expected isolated power and expected on-base — same idea, applied to ISO and OBP.")
_entry("Avg / Max Exit Velo", "How hard the ball comes off the bat, on average and at its hardest, in mph.")
_entry("Hard-Hit%", "Share of batted balls hit 95+ mph.")
_entry("Barrel%", "Share of batted balls hit with the ideal combination of exit velocity and launch angle for extra-base damage.")
_entry("Contact%", "Share of swings that make contact (whiff avoided).")
_entry("Chase%", "Share of pitches outside the strike zone that the batter swings at — lower is better plate discipline.")
_entry("Bat Speed", "Average swing speed, in mph.")
_entry("HVS (Hitting Value Score)", "Our own 1-100 in-house composite blending Hard Contact, Power, Bat-to-Ball, Plate Eye, and Volume (playing time) — deliberately separate from WAR/wRC+/OPS+ to avoid double-counting the same production.")
_entry("Quality of Contact", "Our own 1-100 in-house composite of hard-hit rate, barrel rate, and average exit velocity — a single number for \"how hard does this player hit the ball,\" not an official MLB/Statcast stat.")

style.colored_header("Baserunning", "batting")
_entry("BsR", "Baserunning runs — estimated runs added or lost through baserunning (steals, taking extra bases, etc.) beyond the average runner.")
_entry("SB / CS", "Stolen bases and caught stealing.")
_entry("SB%", "Stolen base success rate.")
_entry("Sprint Speed", "Top running speed on competitive plays, in feet per second.")
_entry("Home-to-1st", "Time from home plate to first base on a batted ball, in seconds — lower is faster.")

style.colored_header("Pitching", "pitching")
_entry("ERA", "Earned run average — earned runs allowed per 9 innings.")
_entry("WHIP", "Walks plus hits per inning pitched.")
_entry("FIP", "Fielding-independent pitching — an ERA-scale estimate built only from strikeouts, walks, and home runs, stripping out the defense behind the pitcher.")
_entry("xERA", "Expected ERA — what ERA \"should\" be based on the quality of contact allowed, not the actual results.")
_entry("K/9, BB/9", "Strikeouts and walks per 9 innings.")
_entry("K-BB%", "Strikeout rate minus walk rate — a single-number gauge of a pitcher's command and dominance.")
_entry("GB/FB", "Ground ball to fly ball ratio.")
_entry("BAbip", "Batting average on balls in play allowed — same idea as batter BABIP, from the pitcher's side.")
_entry("xBA / xSLG / xwOBA against", "Expected batting line allowed, based on contact quality rather than actual results.")
_entry("ERA+", "ERA adjusted for park and league, where 100 is league average (higher is better, unlike raw ERA).")
_entry("Fastball Velo", "Average fastball velocity, in mph.")
_entry("Induced Chase%", "Share of the pitcher's out-of-zone pitches that batters chase — a pitcher-side view of the same chase-rate idea from the batting section.")

style.colored_header("Pitch Arsenal (player pages)", "pitching")
_entry("IVB (Induced Vertical Break)", "How much a pitch rises relative to a gravity-only ball, in inches — high-IVB fastballs \"carry\" and get swings under them.")
_entry("HB (Horizontal Break)", "Sideways movement in inches, from the catcher's view.")
_entry("Active Spin %", "Share of a pitch's spin that actually contributes to movement (vs. gyro spin, which doesn't).")
_entry("Usage %", "How often the pitcher throws that pitch.")
_entry("Whiff %", "Swings and misses per swing against that pitch.")
_entry("Put Away %", "How often a two-strike pitch of this type finishes the strikeout.")
_entry("RV/100 (Run Value per 100)", "Total run impact of a pitch per 100 thrown, from the pitcher's perspective — positive means the pitch saves runs.")

style.colored_header("Fielding", "fielding")
_entry("OAA", "Outs above average — total defensive plays made above what an average fielder at that position would be expected to make.")
_entry("FRP", "Fielding runs prevented — OAA translated into an estimated run value.")
_entry("Success Rate", "Share of fielding opportunities converted into outs.")
_entry("Est. Success Rate", "How often an average fielder would convert the same opportunities, adjusted for their difficulty.")
_entry("Success Rate +/-", "Actual success rate minus estimated — positive means outperforming the difficulty of the plays faced.")
_entry("Arm Strength", "Average recorded throw velocity, in mph.")

style.colored_header("Catcher Defense", "fielding")
_entry("Framing Runs", "Runs added or cost purely by getting borderline pitches called strikes (and keeping real strikes called), versus an average catcher.")
_entry("Strike Rate (shadow zone)", "Share of borderline pitches — the ring around the zone's edges — that end up called strikes.")
_entry("Pop Time", "Glove-to-glove seconds on a steal attempt (to 2B, league average is about 2.00s — lower is better).")
_entry("Exchange", "Glove-to-release time in seconds on a throw down.")
_entry("Arm (catcher)", "Max-effort throw velocity on steal attempts, in mph.")

style.colored_header("Model-Based Projections", "headliners")
_entry(
    "Win Probability (Today's Games)",
    "From our own trained, backtested logistic regression model — not hand-tuned odds. Built on each team's "
    "shrunk in-season record/run differential, shrunk prior-season record, and the probable starter's prior-season "
    "ERA, walk-forward validated so a season's games are only ever scored using a model trained on seasons before it.",
)
_entry(
    "Playoff Odds / World Series Odds",
    "Season-long Monte Carlo-style projection built on the same trained team-strength model (a version with no "
    "starting-pitcher feature, since future starters aren't known yet). Postseason series are simulated on a "
    "neutral field.",
)

style.colored_header("Umpire Scorecards", "headliners")
_entry("Accuracy", "Share of called pitches (balls and strikes only, no swings) that matched the rulebook zone, judged against that specific batter's own measured strike zone.")
_entry("vs Expected", "Accuracy minus what a league-average umpire would have scored on the exact same pitches, adjusted for how difficult (how close to the edge of the zone) those pitches were.")
_entry("Clear Misses", "Missed calls more than 1 inch beyond the zone boundary — filters out the razor-thin calls where pitch-tracking's own margin of error makes \"miss\" debatable.")

st.divider()
st.caption("Something missing or unclear? These definitions describe how this site computes and labels each stat — always double-check against MLB/Statcast's own glossary for the official, canonical wording.")
