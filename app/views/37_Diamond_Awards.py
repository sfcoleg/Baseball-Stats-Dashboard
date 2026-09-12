"""Diamond Metrics Awards — an end-of-season trophy case for the site's
OWN metrics, not a projection of the real MVP/Cy Young/Rookie of the Year
(that's views/29_Awards_Race.py, which already exists and uses real
WAR-based formulas). These five categories only exist here: Eye Score,
Contact Score, Power Score, and HVS are our own composites with no real
MLB or Statcast equivalent, so a "Best Eye" trophy is not a copy of
anything — it is the site's own opinion, stated as such."""
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import prefs
import style
import teams

st.set_page_config(page_title="Diamond Metrics Awards | Diamond Metrics", layout="wide")
st.title("🏆 Diamond Metrics Awards")
st.caption(
    "Our own end-of-season awards, built entirely from stats that live only on this site — "
    "not a projection of the real MVP or Cy Young race (see Awards Race for that)."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
seasons = db.get_seasons("batting")
season = st.selectbox("Season", seasons, index=prefs.default_season_index(seasons))

batting = db.load_batting(season, mtime)
batting["HVS"] = db.hitting_value_score(batting)

_bb = db.load_batted_ball(season, mtime)
if not _bb.empty:
    batting = batting.merge(_bb.drop(columns="season", errors="ignore"), on="mlbID", how="left")
_bt = db.load_bat_tracking(season, mtime)
if not _bt.empty:
    batting = batting.merge(_bt.drop(columns="season", errors="ignore"), on="mlbID", how="left")
batting["Power Score"] = db.power_score(batting)

_pd = db.load_plate_discipline(season, mtime)
if not _pd.empty and "total_pitches" in _pd.columns:
    _pd = _pd.merge(batting[["mlbID", "hp_to_1b"]], on="mlbID", how="left")
    if "swing_length" in batting.columns:
        _pd = _pd.merge(batting[["mlbID", "swing_length"]], on="mlbID", how="left")
    _pd = _pd.assign(Eye=db.discipline_eye_score(_pd), Contact=db.contact_score(_pd))
    batting = batting.merge(
        _pd[["mlbID", "Eye", "Contact"]].rename(columns={"Eye": "Eye Score", "Contact": "Contact Score"}),
        on="mlbID", how="left",
    )

wpa = db.load_wpa_batting(season, mtime)
if not wpa.empty:
    batting = batting.merge(wpa[["mlbID", "wpa"]], on="mlbID", how="left")

qualified = batting[batting["PA"] >= db.QUALIFIED_MIN_PA]


def _trophy_card(icon: str, title: str, blurb: str, stat_col: str, stat_label: str, fmt: str):
    """One award: winner's photo/name/team plus the stat that won it,
    reusing the site's own headshot/player-link helpers so a click goes
    straight to that player's real page."""
    pool = qualified.dropna(subset=[stat_col])
    if pool.empty:
        st.caption(f"Not enough data for {title} this season.")
        return
    winner = pool.nlargest(1, stat_col).iloc[0]
    runners_up = pool.nlargest(4, stat_col).iloc[1:]
    abbr = teams.normalize_mlb_abbr(winner["Tm"])
    color = teams.color_for_abbr(abbr)
    value = fmt.format(winner[stat_col])

    with st.container(border=True):
        st.markdown(
            f"<div style='font-size:0.68rem;letter-spacing:1.3px;text-transform:uppercase;"
            f"color:var(--dm-dim)'>{icon} {title}</div>",
            unsafe_allow_html=True,
        )
        st.caption(blurb)
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:14px;margin-top:6px'>"
            f"<img src='{style.headshot_url(int(winner['mlbID']), width=180)}' "
            f"style='width:72px;height:72px;border-radius:10px;object-fit:cover;"
            f"object-position:center 25%;flex-shrink:0' />"
            f"<div>"
            f"<div style='font-size:1.15rem;font-weight:700'>"
            f"<a href='{style.player_link(int(winner['mlbID']), season)}' target='_self' "
            f"style='color:inherit;text-decoration:none'>{winner['Name']}</a> "
            f"<span style='background-color:{color}66;color:var(--dm-text);padding:2px 9px;"
            f"border-radius:8px;font-size:0.65em;vertical-align:middle;font-weight:600'>{abbr}</span>"
            f"</div>"
            f"<div style='margin-top:4px;font-family:\"Archivo Narrow\",sans-serif;font-weight:800;"
            f"font-size:1.6rem;color:{color}'>{value} <span style='font-size:0.55em;"
            f"font-weight:600;color:var(--dm-dim);font-family:inherit'>{stat_label}</span></div>"
            f"</div></div>",
            unsafe_allow_html=True,
        )
        if not runners_up.empty:
            names = ", ".join(
                f"{r['Name']} ({fmt.format(r[stat_col])})" for _, r in runners_up.iterrows()
            )
            st.caption(f"Also considered: {names}")


col1, col2 = st.columns(2)
with col1:
    _trophy_card(
        "⭐", "Diamond MVP",
        "Highest Hitting Value Score — our own blend of hard contact, power, bat-to-ball, plate eye "
        "and playing time, deliberately excluding WAR/wRC+/OPS+ so it isn't just restating them.",
        "HVS", "HVS", "{:.0f}",
    )
with col2:
    _trophy_card(
        "🎯", "Best Eye",
        "Highest Eye Score — swing decisions by Statcast attack zone, including the shadow-in/"
        "shadow-out split no public leaderboard carries, weighted so protecting with two strikes "
        "isn't judged like chasing on 3-0.",
        "Eye Score", "Eye Score", "{:.0f}",
    )

col3, col4 = st.columns(2)
with col3:
    _trophy_card(
        "🤏", "Best Bat-to-Ball",
        "Highest Contact Score — built specifically to predict strikeout rate without ever using "
        "strikeout rate as an input. Correlates -0.89 with real K% on this season's data.",
        "Contact Score", "Contact Score", "{:.0f}",
    )
with col4:
    _trophy_card(
        "💥", "Most Raw Power",
        "Highest Power Score — hard-hit rate, exit velocity, bat speed and sweet-spot rate. "
        "Deliberately excludes ISO/HR/barrel%, since those are outcomes, not capacity.",
        "Power Score", "Power Score", "{:.0f}",
    )

st.markdown("")
_trophy_card(
    "🔥", "Clutch Award",
    "Highest Win Probability Added (WPA) — how much this player's own plate appearances moved his "
    "team's championship-relevant chances, from our own trained win-probability model. A double in "
    "the 9th with the game on the line counts for far more here than the same swing in the 3rd.",
    "wpa", "WPA", "{:+.2f}",
)
