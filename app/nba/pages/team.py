"""NBA Team — one club's current roster, joined with each player's most
recent season stats. Roster is CURRENT (confirmed: 2026-27 rosters already
reflect real offseason moves, e.g. Boston's real trade for Mitchell
Robinson), stats are the last completed season — so a new arrival shows
real bio info with stats blank rather than someone else's numbers under
the wrong team."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nba import db as ndb
from nba import teams as nteams

st.set_page_config(page_title="NBA Team | Diamond Metrics", layout="wide")
st.title("Team")

mtime = ndb.nba_db_mtime()
all_teams = nteams.all_teams()
if not all_teams:
    st.info("No NBA data yet — run `python ingest/nba_refresh.py` to build it.")
    st.stop()

labels = [f"{abbr} — {nick}" for abbr, nick in all_teams]
default_idx = 0
if st.session_state.get("nba_team_selected"):
    want = st.session_state["nba_team_selected"]
    default_idx = next((i for i, (a, _) in enumerate(all_teams) if a == want), 0)
choice = st.selectbox("Team", labels, index=default_idx)
abbr = choice.split(" — ")[0]
st.session_state["nba_team_selected"] = abbr

team_id = nteams._table().get(abbr, {}).get("team_id")

color = nteams.color_for_abbr(abbr)
name_color = style.team_text_color(color)
st.markdown(
    f"<div style='font-size:1.6rem;font-weight:800;color:{name_color};margin-bottom:8px'>"
    f"{nteams.name_for_abbr(abbr)}</div>",
    unsafe_allow_html=True,
)

standings = ndb.load_standings(mtime)
if not standings.empty and team_id is not None:
    row = standings[standings["TeamID"] == team_id]
    if not row.empty:
        r = row.iloc[0]
        m1, m2, m3 = st.columns(3)
        m1.metric("Record", f"{int(r['WINS'])}-{int(r['LOSSES'])}")
        m2.metric("Conference Rank", f"#{int(r['PlayoffRank'])}" if pd.notna(r.get("PlayoffRank")) else "—")
        m3.metric("Conference", r.get("Conference", "—"))
        if ndb.standings_are_preseason(mtime):
            st.caption(f"{ndb.current_season_label()} hasn't tipped off yet — this is the real, unplayed record.")

style.colored_header("Roster", "batting", color)
if team_id is None:
    st.caption("Team not found.")
    st.stop()

roster = ndb.load_roster(team_id, mtime)
if roster.empty:
    st.caption("No roster data yet for this team.")
    st.stop()

stats = ndb.load_player_stats(mtime)
stats_season = ndb.player_stats_season(mtime)
if not stats.empty:
    keep_stats = [c for c in ("PLAYER_ID", "GP", "PTS_PG", "REB_PG", "AST_PG", "FG_PCT") if c in stats.columns]
    roster = roster.merge(stats[keep_stats], on="PLAYER_ID", how="left")

if stats_season:
    st.caption(f"Stats shown are from {stats_season}, the most recently completed season — "
               "blank for anyone new to the roster since then.")

display = pd.DataFrame({
    "Player": roster["PLAYER"],
    "#": roster["NUM"],
    "Pos": roster["POSITION"],
    "Ht": roster["HEIGHT"],
    "Wt": roster["WEIGHT"],
    "Age": roster["AGE"],
})
for src, label in (("GP", "GP"), ("PTS_PG", "PPG"), ("REB_PG", "RPG"), ("AST_PG", "APG"), ("FG_PCT", "FG%")):
    if src in roster.columns:
        display[label] = roster[src]

st.dataframe(
    style.style_stats_table(
        display,
        higher_better=[l for l in ("PPG", "RPG", "APG", "FG%") if l in display.columns],
        precision={"PPG": "{:.1f}", "RPG": "{:.1f}", "APG": "{:.1f}", "FG%": "{:.3f}"},
    ),
    use_container_width=True, hide_index=True, height=560,
)
