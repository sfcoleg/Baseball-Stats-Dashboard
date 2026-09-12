"""NBA Compare — two players side by side. Every NBA player shares the
same stat categories (unlike NFL, where a QB and a cornerback share
almost nothing), so this is one fixed row set rather than picking
sections by position."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nba import db as ndb
from nba import teams as nteams

st.set_page_config(page_title="NBA Compare | Diamond Metrics", layout="wide")
st.title("Compare")

mtime = ndb.nba_db_mtime()
players = ndb.load_player_stats(mtime)
if players.empty:
    st.info("No NBA player data yet — run `python ingest/nba_refresh.py` to build it.")
    st.stop()

season = ndb.player_stats_season(mtime)
st.caption(f"{season} season" if season else "")

pool = ndb.qualified_players(players)
if pool.empty:
    st.caption("Not enough qualifying players yet.")
    st.stop()
pool = pool.copy()
pool["label"] = pool["PLAYER_NAME"] + " (" + pool["TEAM_ABBREVIATION"].fillna("") + ")"
options = pool.sort_values("PLAYER_NAME")["label"].tolist()

c1, c2 = st.columns(2)
left_label = c1.selectbox("Player A", options, index=0, key="nba_cmp_a")
right_label = c2.selectbox("Player B", options, index=min(1, len(options) - 1), key="nba_cmp_b")
if left_label == right_label:
    st.caption("Pick two different players.")
    st.stop()

a = pool[pool["label"] == left_label].iloc[0]
b = pool[pool["label"] == right_label].iloc[0]

ROWS = [
    ("Points / Game", "PTS_PG", True, "{:.1f}"),
    ("Rebounds / Game", "REB_PG", True, "{:.1f}"),
    ("Assists / Game", "AST_PG", True, "{:.1f}"),
    ("Steals / Game", "STL_PG", True, "{:.1f}"),
    ("Blocks / Game", "BLK_PG", True, "{:.1f}"),
    ("Turnovers / Game", "TOV_PG", False, "{:.1f}"),
    ("Minutes / Game", "MIN_PG", True, "{:.1f}"),
    ("FG%", "FG_PCT", True, "{:.3f}"),
    ("3P%", "FG3_PCT", True, "{:.3f}"),
    ("FT%", "FT_PCT", True, "{:.3f}"),
    ("Plus/Minus", "PLUS_MINUS", True, "{:+.0f}"),
]

color_a = nteams.color_for_abbr(a.get("TEAM_ABBREVIATION") or "")
color_b = nteams.color_for_abbr(b.get("TEAM_ABBREVIATION") or "")

st.markdown(
    "<div style='display:flex;justify-content:space-between;align-items:center;"
    "margin:6px 0 2px'>"
    f"<div style='font-weight:800;font-size:1.1rem;color:{style.team_text_color(color_a)}'>"
    f"{a['PLAYER_NAME']} <span style='color:var(--dm-dim);font-weight:600'>"
    f"{a.get('TEAM_ABBREVIATION') or ''}</span></div>"
    f"<div style='font-weight:800;font-size:1.1rem;text-align:right;"
    f"color:{style.team_text_color(color_b)}'>{b['PLAYER_NAME']} "
    f"<span style='color:var(--dm-dim);font-weight:600'>{b.get('TEAM_ABBREVIATION') or ''}</span></div>"
    "</div>",
    unsafe_allow_html=True,
)

style.colored_header("Season Stats", "batting")
body = []
for label, key, higher_better, fmt in ROWS:
    va, vb = a.get(key), b.get(key)
    if (va is None or pd.isna(va)) and (vb is None or pd.isna(vb)):
        continue
    va = 0 if va is None or pd.isna(va) else va
    vb = 0 if vb is None or pd.isna(vb) else vb
    a_wins = (va > vb) if higher_better else (va < vb)
    body.append(
        "<tr style='border-top:1px solid var(--dm-line)'>"
        f"<td style='padding:6px 10px;text-align:right;font-weight:{700 if a_wins else 400};"
        f"color:{'var(--dm-text)' if a_wins else 'var(--dm-dim)'}'>{fmt.format(va)}</td>"
        f"<td style='padding:6px 14px;text-align:center;color:var(--dm-dim);"
        f"white-space:nowrap'>{label}</td>"
        f"<td style='padding:6px 10px;text-align:left;font-weight:{400 if a_wins else 700};"
        f"color:{'var(--dm-dim)' if a_wins else 'var(--dm-text)'}'>{fmt.format(vb)}</td></tr>"
    )
if body:
    st.markdown(
        "<table style='width:100%;border-collapse:collapse'>"
        f"<tbody>{''.join(body)}</tbody></table>",
        unsafe_allow_html=True,
    )
