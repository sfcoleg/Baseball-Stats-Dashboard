"""NFL Player profile — reached from search or from a leaderboard, not from
the nav (same convention as the MLB and NHL player pages)."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import db as fdb
from nfl import teams as fteams

st.set_page_config(page_title="NFL Player | Diamond Metrics", layout="wide")

mtime = fdb.nfl_db_mtime()

# Deep links carry the id in the URL; in-app navigation puts it in session
# state. Either is enough to land on a player.
if "nfl_selected_player" not in st.session_state and "player" in st.query_params:
    st.session_state["nfl_selected_player"] = st.query_params["player"]

player_id = st.session_state.get("nfl_selected_player")
if not player_id:
    st.title("Player")
    st.info("Search for a player using the box in the top bar.")
    st.stop()

career = fdb.load_player_career(player_id, mtime)
if career.empty:
    st.title("Player")
    st.warning("No data on file for that player.")
    st.stop()

reg = career[career["season_type"] == "REG"]
latest = (reg if not reg.empty else career).iloc[0]
name = latest["player_display_name"]
team = latest.get("team") or ""
color = fteams.color_for_abbr(team)
st.query_params["player"] = str(player_id)

st.title(name)
head = []
if latest.get("headshot_url"):
    head.append(
        f"<img src='{latest['headshot_url']}' style='width:74px;height:74px;border-radius:50%;"
        f"object-fit:cover;border:2px solid {color};background:var(--dm-surface-mute)' />"
    )
badge = (
    f"<span style='background-color:{color}66;color:var(--dm-text);padding:3px 12px;"
    f"border-radius:8px;font-weight:700'>{team}</span>" if team else ""
)
st.markdown(
    "<div style='display:flex;align-items:center;gap:14px;margin-bottom:8px'>"
    + "".join(head)
    + f"<div>{badge} <span style='color:var(--dm-dim)'>{latest.get('position') or ''}</span></div>"
    "</div>",
    unsafe_allow_html=True,
)

# --- Which side of the ball to show ----------------------------------------
# A profile shouldn't show a receiver an empty passing table. Pick the groups
# this player actually has volume in, and fall back to his position group.
# A threshold, not just "> 0". Quarterbacks pick up a target or two on trick
# plays across a career, and receivers throw the odd pass — testing for any
# volume at all gave Mahomes a receiving table built on two catches.
_MIN_CAREER_VOLUME = 20


def _has(col: str) -> bool:
    if col not in reg.columns:
        return False
    return pd.to_numeric(reg[col], errors="coerce").fillna(0).sum() >= _MIN_CAREER_VOLUME

sections = [k for k, col in (("Passing", "attempts"), ("Rushing", "carries"), ("Receiving", "targets")) if _has(col)]
if not sections:
    sections = ["Passing"] if latest.get("position") == "QB" else ["Receiving"]

SECTION_COLUMNS = {
    "Passing": ([("season", "Season"), ("team", "Tm"), ("games", "G"), ("attempts", "Att"),
                 ("completion_pct", "Cmp%"), ("passing_yards", "Yds"), ("yards_per_attempt", "Y/A"),
                 ("passing_tds", "TD"), ("passing_interceptions", "INT"),
                 ("passing_epa", "EPA"), ("passing_epa_per_att", "EPA/Att"), ("passing_cpoe", "CPOE")],
                {"Cmp%": "{:.1f}", "Y/A": "{:.1f}", "EPA": "{:.1f}", "EPA/Att": "{:.2f}", "CPOE": "{:.1f}"}),
    "Rushing": ([("season", "Season"), ("team", "Tm"), ("games", "G"), ("carries", "Att"),
                 ("rushing_yards", "Yds"), ("yards_per_carry", "Y/C"), ("rushing_tds", "TD"),
                 ("rushing_first_downs", "1D"), ("rushing_epa", "EPA"), ("rushing_epa_per_carry", "EPA/Att")],
                {"Y/C": "{:.1f}", "EPA": "{:.1f}", "EPA/Att": "{:.2f}"}),
    "Receiving": ([("season", "Season"), ("team", "Tm"), ("games", "G"), ("targets", "Tgt"),
                   ("receptions", "Rec"), ("receiving_yards", "Yds"), ("yards_per_reception", "Y/R"),
                   ("receiving_tds", "TD"), ("receiving_yards_after_catch", "YAC"),
                   ("receiving_epa", "EPA"), ("receiving_epa_per_target", "EPA/Tgt")],
                  {"Y/R": "{:.1f}", "EPA": "{:.1f}", "EPA/Tgt": "{:.2f}"}),
}

for section in sections:
    columns, precision = SECTION_COLUMNS[section]
    style.colored_header(f"{section} by Season", "batting", color)
    display = pd.DataFrame()
    for src, label in columns:
        if src in reg.columns:
            display[label] = reg[src]
    st.dataframe(
        style.style_stats_table(
            display, team_col="Tm", team_color_fn=fteams.color_for_abbr,
            higher_better=[l for _, l in columns if l not in ("Season", "Tm", "INT")],
            lower_better=["INT"] if "INT" in display.columns else [],
            precision={**precision, "Season": "{:.0f}"},
        ),
        use_container_width=True, hide_index=True,
    )

# --- Game log ---------------------------------------------------------------
weekly_seasons = sorted(reg["season"].astype(int).unique(), reverse=True)
if weekly_seasons:
    style.colored_header("Game Log", "headliners", color)
    picked = st.selectbox("Season", weekly_seasons, format_func=fdb.season_label, key="nfl_gamelog_season")
    log = fdb.load_player_weeks(player_id, picked, mtime)
    if log.empty:
        st.caption(
            "Weekly detail is kept for the most recent seasons only — season totals above cover the rest."
        )
    else:
        cols = [("week", "Wk"), ("opponent_team", "Opp")]
        if "Passing" in sections:
            cols += [("attempts", "Att"), ("passing_yards", "Pass Yds"), ("passing_tds", "Pass TD"),
                     ("passing_interceptions", "INT"), ("passing_epa", "Pass EPA")]
        if "Rushing" in sections:
            cols += [("carries", "Car"), ("rushing_yards", "Rush Yds"), ("rushing_tds", "Rush TD")]
        if "Receiving" in sections:
            cols += [("targets", "Tgt"), ("receptions", "Rec"), ("receiving_yards", "Rec Yds"),
                     ("receiving_tds", "Rec TD")]
        display = pd.DataFrame()
        for src, label in cols:
            if src in log.columns:
                display[label] = log[src]
        st.dataframe(
            style.style_stats_table(
                display, team_col="Opp", team_color_fn=fteams.color_for_abbr,
                higher_better=[l for _, l in cols if l not in ("Wk", "Opp", "INT")],
                lower_better=["INT"] if "INT" in display.columns else [],
                precision={"Pass EPA": "{:.1f}"},
            ),
            use_container_width=True, hide_index=True, height=460,
        )
