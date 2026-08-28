"""NFL Team — one club's season: record, results and per-week production."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import db as fdb
from nfl import teams as fteams

st.set_page_config(page_title="NFL Team | Diamond Metrics", layout="wide")
st.title("Team")

mtime = fdb.nfl_db_mtime()
season_list = fdb.seasons(mtime)
if not season_list:
    st.info("No NFL data yet — run `python ingest/nfl_refresh.py` to build it.")
    st.stop()

all_teams = fteams.all_teams()
c1, c2 = st.columns(2)
season = c1.selectbox("Season", season_list, index=fdb.season_index(season_list, mtime),
                      format_func=fdb.season_label)
labels = [f"{abbr} — {nick}" for abbr, nick in all_teams]
default_idx = 0
if st.session_state.get("nfl_team_selected"):
    want = st.session_state["nfl_team_selected"]
    default_idx = next((i for i, (a, _) in enumerate(all_teams) if a == want), 0)
choice = c2.selectbox("Team", labels, index=default_idx)
abbr = choice.split(" — ")[0]
st.session_state["nfl_team_selected"] = abbr

color = fteams.color_for_abbr(abbr)
name_color = style.team_text_color(color)
logo = fteams.logo_url(abbr)
st.markdown(
    "<div style='display:flex;align-items:center;gap:14px;margin-bottom:8px'>"
    + (f"<img src='{logo}' style='width:56px;height:56px;object-fit:contain' />" if logo else "")
    + f"<div style='font-size:1.6rem;font-weight:800;color:{name_color}'>{fteams.name_for_abbr(abbr)}</div>"
    + f"<div style='color:var(--dm-dim)'>{fteams.division_for_abbr(abbr)}</div>"
    "</div>",
    unsafe_allow_html=True,
)

standings = fdb.load_standings(season, mtime)
row = standings[standings["team"] == abbr]
if not row.empty:
    r = row.iloc[0]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Record", fdb.record_string(r))
    m2.metric("Points For", int(r["points_for"]))
    m3.metric("Points Against", int(r["points_against"]))
    m4.metric("Point Diff", f"{int(r['point_diff']):+d}")

# --- Results ---------------------------------------------------------------
games = fdb.load_games(season, mtime)
own = fdb.team_schedule(games, abbr)
style.colored_header("Results", "headliners", color)
if own.empty:
    st.caption("No games scheduled for this team in this season.")
else:
    rows = []
    for _, g in own.iterrows():
        rows.append({
            "Wk": int(g["week"]),
            "Date": str(g.get("gameday") or ""),
            "H/A": "vs" if g["is_home"] else "@",
            "Opp": g["opponent"],
            "Result": g["result"] if pd.notna(g["result"]) else "—",
            "PF": float(g["points_for"]) if g["played"] else float("nan"),
            "PA": float(g["points_against"]) if g["played"] else float("nan"),
        })
    st.dataframe(
        style.style_stats_table(
            pd.DataFrame(rows), team_col="Opp", team_color_fn=fteams.color_for_abbr,
            higher_better=["PF"], lower_better=["PA"],
            precision={"PF": "{:.0f}", "PA": "{:.0f}"},
        ),
        use_container_width=True, hide_index=True, height=460,
    )

# --- Weekly production ------------------------------------------------------
weeks = fdb.load_team_weeks(season, mtime)
if not weeks.empty and "team" in weeks.columns:
    own_weeks = weeks[weeks["team"] == abbr].sort_values("week")
    if not own_weeks.empty:
        style.colored_header("Weekly Production", "batting", color)
        cols = [c for c in (
            "week", "passing_yards", "passing_tds", "passing_epa", "passing_cpoe",
            "rushing_yards", "rushing_tds", "rushing_epa",
        ) if c in own_weeks.columns]
        display = own_weeks[cols].rename(columns={
            "week": "Wk", "passing_yards": "Pass Yds", "passing_tds": "Pass TD",
            "passing_epa": "Pass EPA", "passing_cpoe": "CPOE",
            "rushing_yards": "Rush Yds", "rushing_tds": "Rush TD", "rushing_epa": "Rush EPA",
        })
        st.dataframe(
            style.style_stats_table(
                display,
                higher_better=[c for c in ("Pass Yds", "Pass TD", "Pass EPA", "CPOE", "Rush Yds", "Rush TD", "Rush EPA") if c in display.columns],
                precision={"Pass EPA": "{:.1f}", "Rush EPA": "{:.1f}", "CPOE": "{:.1f}"},
            ),
            use_container_width=True, hide_index=True, height=460,
        )
elif weeks.empty:
    style.colored_header("Weekly Production", "batting", color)
    st.caption(
        "nflverse hasn't published this season's team stats yet — they appear once games are played."
    )
