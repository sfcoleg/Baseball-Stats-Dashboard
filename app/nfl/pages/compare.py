"""NFL Compare — two players side by side.

Which stats appear depends on what the two players actually do: comparing a
quarterback against a cornerback on passing yards would be meaningless, so
the row set is chosen from the positions involved rather than fixed."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import db as fdb
from nfl import teams as fteams

st.set_page_config(page_title="NFL Compare | Diamond Metrics", layout="wide")
st.title("Compare")

mtime = fdb.nfl_db_mtime()
season_list = fdb.seasons(mtime)
if not season_list:
    st.info("No NFL data yet — run `python ingest/nfl_refresh.py` to build it.")
    st.stop()

season = st.selectbox("Season", season_list, index=fdb.season_index(season_list, mtime),
                      format_func=fdb.season_label)
players = fdb.load_player_seasons(season, mtime)
if players.empty:
    st.caption(f"No player data for {fdb.season_label(season)} yet.")
    st.stop()

# Only offer players with real volume — the full season table includes every
# player who touched the field once, and a picker of 2,000 names where most
# have a single snap is worse than useless.
def _has_volume(row) -> bool:
    return (
        (row.get("attempts") or 0) >= 50
        or (row.get("carries") or 0) >= 25
        or (row.get("targets") or 0) >= 15
    )


pool = players[players.apply(_has_volume, axis=1)].copy()
if pool.empty:
    st.caption("Not enough players with meaningful volume this season.")
    st.stop()
pool["label"] = pool["player_display_name"] + " (" + pool["team"].fillna("") + ")"
options = pool.sort_values("player_display_name")["label"].tolist()

c1, c2 = st.columns(2)
left_label = c1.selectbox("Player A", options, index=0, key="nfl_cmp_a")
right_label = c2.selectbox(
    "Player B", options, index=min(1, len(options) - 1), key="nfl_cmp_b"
)
if left_label == right_label:
    st.caption("Pick two different players.")
    st.stop()

a = pool[pool["label"] == left_label].iloc[0]
b = pool[pool["label"] == right_label].iloc[0]

# Row sets per discipline. A row only renders if at least one of the two
# players has volume in it, so a QB-vs-QB comparison shows passing and a
# WR-vs-RB comparison shows the ground each shares.
PASSING = [
    ("Attempts", "attempts", True, "{:.0f}"),
    ("Completion %", "completion_pct", True, "{:.1f}"),
    ("Yards", "passing_yards", True, "{:.0f}"),
    ("Yards / Attempt", "yards_per_attempt", True, "{:.1f}"),
    ("Touchdowns", "passing_tds", True, "{:.0f}"),
    ("Interceptions", "passing_interceptions", False, "{:.0f}"),
    ("EPA", "passing_epa", True, "{:.1f}"),
    ("EPA / Attempt", "passing_epa_per_att", True, "{:.2f}"),
    ("CPOE", "passing_cpoe", True, "{:+.1f}"),
]
RUSHING = [
    ("Carries", "carries", True, "{:.0f}"),
    ("Rush Yards", "rushing_yards", True, "{:.0f}"),
    ("Yards / Carry", "yards_per_carry", True, "{:.1f}"),
    ("Rush TD", "rushing_tds", True, "{:.0f}"),
    ("Rush EPA", "rushing_epa", True, "{:.1f}"),
    ("Rush EPA / Att", "rushing_epa_per_carry", True, "{:.2f}"),
]
RECEIVING = [
    ("Targets", "targets", True, "{:.0f}"),
    ("Receptions", "receptions", True, "{:.0f}"),
    ("Rec Yards", "receiving_yards", True, "{:.0f}"),
    ("Yards / Rec", "yards_per_reception", True, "{:.1f}"),
    ("Rec TD", "receiving_tds", True, "{:.0f}"),
    ("YAC", "receiving_yards_after_catch", True, "{:.0f}"),
    ("Rec EPA", "receiving_epa", True, "{:.1f}"),
    ("Rec EPA / Tgt", "receiving_epa_per_target", True, "{:.2f}"),
]


def _relevant(rows, volume_col, floor):
    return (a.get(volume_col) or 0) >= floor or (b.get(volume_col) or 0) >= floor


sections = []
if _relevant(PASSING, "attempts", 50):
    sections.append(("Passing", PASSING))
if _relevant(RUSHING, "carries", 25):
    sections.append(("Rushing", RUSHING))
if _relevant(RECEIVING, "targets", 15):
    sections.append(("Receiving", RECEIVING))

color_a = fteams.color_for_abbr(a.get("team") or "")
color_b = fteams.color_for_abbr(b.get("team") or "")

st.markdown(
    "<div style='display:flex;justify-content:space-between;align-items:center;"
    "margin:6px 0 2px'>"
    f"<div style='font-weight:800;font-size:1.1rem;color:{style.team_text_color(color_a)}'>"
    f"{a['player_display_name']} <span style='color:var(--dm-dim);font-weight:600'>"
    f"{a.get('team') or ''} · {a.get('position') or ''}</span></div>"
    f"<div style='font-weight:800;font-size:1.1rem;text-align:right;"
    f"color:{style.team_text_color(color_b)}'>{b['player_display_name']} "
    f"<span style='color:var(--dm-dim);font-weight:600'>{b.get('team') or ''} · "
    f"{b.get('position') or ''}</span></div></div>",
    unsafe_allow_html=True,
)

if not sections:
    st.caption("These two players don't share a comparable statistical profile.")
    st.stop()

for title, rows in sections:
    style.colored_header(title, "batting")
    body = []
    for label, key, higher_better, fmt in rows:
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
