"""NFL Schedule — one week at a time, the way the league is watched."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import db as fdb
from nfl import teams as fteams

st.set_page_config(page_title="NFL Schedule | Diamond Metrics", layout="wide")
st.title("Schedule")

mtime = fdb.nfl_db_mtime()
season_list = fdb.seasons(mtime)
if not season_list:
    st.info("No NFL data yet — run `python ingest/nfl_refresh.py` to build it.")
    st.stop()

c1, c2 = st.columns(2)
season = c1.selectbox("Season", season_list, index=fdb.season_index(season_list, mtime),
                      format_func=fdb.season_label)
games = fdb.load_games(season, mtime)
if games.empty:
    st.caption("No schedule for this season yet.")
    st.stop()

weeks = sorted(games["week"].dropna().unique().astype(int).tolist())
default_week = fdb.current_week(games)
week = c2.selectbox(
    "Week", weeks,
    index=weeks.index(default_week) if default_week in weeks else 0,
    format_func=lambda w: f"Week {w}",
)

week_games = games[games["week"] == week]
game_type = week_games.iloc[0]["game_type"] if not week_games.empty else "REG"
label = fdb.GAME_TYPE_LABELS.get(game_type, "")
style.colored_header(f"Week {week}" + (f" · {label}" if label and label != "Regular season" else ""), "headliners")

rows = []
for _, g in week_games.iterrows():
    played = g["played"]
    rows.append({
        "Day": str(g.get("weekday") or ""),
        "Date": str(g.get("gameday") or ""),
        "Away": g["away_team"],
        "Pts": float(g["away_score"]) if played else float("nan"),
        "Home": g["home_team"],
        "Pts.": float(g["home_score"]) if played else float("nan"),
        "Total": float(g["total"]) if played and pd.notna(g.get("total")) else float("nan"),
        "Stadium": str(g.get("stadium") or ""),
    })
st.dataframe(
    style.style_stats_table(
        pd.DataFrame(rows), team_col="Away", team_color_fn=fteams.color_for_abbr,
        precision={"Pts": "{:.0f}", "Pts.": "{:.0f}", "Total": "{:.0f}"},
    ),
    use_container_width=True, hide_index=True, height=560,
)

unplayed = int((~week_games["played"]).sum())
if unplayed:
    st.caption(f"{unplayed} of {len(week_games)} games in this week haven't been played yet.")
