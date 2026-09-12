"""NBA Player profile — reached from search, not from the nav (same
convention as the MLB/NFL/NHL player pages)."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nba import db as ndb
from nba import teams as nteams

st.set_page_config(page_title="NBA Player | Diamond Metrics", layout="wide")

mtime = ndb.nba_db_mtime()

# Deep links carry the id in the URL; in-app navigation (search) puts it in
# session state. Either is enough to land on a player.
if "nba_selected_player" not in st.session_state and "player" in st.query_params:
    st.session_state["nba_selected_player"] = st.query_params["player"]

player_id = st.session_state.get("nba_selected_player")
if not player_id:
    st.title("Player")
    st.info("Search for a player using the box in the top bar.")
    st.stop()
player_id = int(player_id)

season_row = ndb.load_player_season(player_id, mtime)
bio_row = ndb.load_player_bio(player_id, mtime)

if season_row is None and bio_row is None:
    st.title("Player")
    st.warning("No data on file for that player.")
    st.stop()

name = (season_row or {}).get("PLAYER_NAME") or (bio_row or {}).get("PLAYER") or "Player"
abbr = (season_row or {}).get("TEAM_ABBREVIATION")
if not abbr and bio_row:
    abbr = ndb.team_abbr_map(mtime).get(bio_row.get("TeamID"))
color = nteams.color_for_abbr(abbr) if abbr else "#666666"
st.query_params["player"] = str(player_id)

st.title(name)
badge = (
    f"<span style='background-color:{color}66;color:var(--dm-text);padding:3px 12px;"
    f"border-radius:8px;font-weight:700'>{abbr}</span>" if abbr else ""
)
bio_bits = []
if bio_row:
    if bio_row.get("POSITION"):
        bio_bits.append(str(bio_row["POSITION"]))
    if bio_row.get("HEIGHT"):
        bio_bits.append(str(bio_row["HEIGHT"]))
    if bio_row.get("WEIGHT"):
        bio_bits.append(f"{bio_row['WEIGHT']} lb")
    if bio_row.get("NUM"):
        bio_bits.append(f"#{bio_row['NUM']}")
bio_line = " · ".join(bio_bits)

st.markdown(
    "<div style='display:flex;align-items:center;gap:14px;margin-bottom:8px'>"
    f"<img src='https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png' "
    f"style='width:74px;height:74px;border-radius:50%;object-fit:cover;object-position:top;"
    f"border:2px solid {color};background:var(--dm-surface-mute)' onerror=\"this.style.display='none'\" />"
    f"<div>{badge} <span style='color:var(--dm-dim)'>{bio_line}</span></div>"
    "</div>",
    unsafe_allow_html=True,
)

season_label = season_row.get("season") if season_row else None
if season_row:
    st.caption(f"{season_label} season averages" + (
        " — the most recently completed one; 2026-27 hasn't tipped off yet."
        if season_label and season_label != ndb.current_season_label() else "."
    ))
    m = st.columns(7)
    for col, (src, label, fmt) in zip(m, [
        ("PTS_PG", "PPG", "{:.1f}"), ("REB_PG", "RPG", "{:.1f}"), ("AST_PG", "APG", "{:.1f}"),
        ("STL_PG", "SPG", "{:.1f}"), ("BLK_PG", "BPG", "{:.1f}"),
        ("FG_PCT", "FG%", "{:.3f}"), ("FG3_PCT", "3P%", "{:.3f}"),
    ]):
        val = season_row.get(src)
        col.metric(label, fmt.format(val) if val is not None and pd.notna(val) else "—")
else:
    st.caption("No season stats on file yet for this player.")

style.colored_header("Recent Games", "batting")
if season_label:
    log = ndb.load_player_gamelog(player_id, season_label)
else:
    log = pd.DataFrame()

if log.empty:
    st.caption("No game log available.")
else:
    display = pd.DataFrame({
        "Date": pd.to_datetime(log["GAME_DATE"]).dt.strftime("%b %d"),
        "Matchup": log["MATCHUP"], "W/L": log["WL"],
        "MIN": log["MIN"], "PTS": log["PTS"], "REB": log["REB"], "AST": log["AST"],
        "STL": log["STL"], "BLK": log["BLK"],
        "FG": log["FGM"].astype(str) + "-" + log["FGA"].astype(str),
        "3P": log["FG3M"].astype(str) + "-" + log["FG3A"].astype(str),
        "FT": log["FTM"].astype(str) + "-" + log["FTA"].astype(str),
    })
    st.dataframe(
        style.style_stats_table(
            display,
            higher_better=["PTS", "REB", "AST", "STL", "BLK"],
        ),
        use_container_width=True, hide_index=True, height=560,
    )
