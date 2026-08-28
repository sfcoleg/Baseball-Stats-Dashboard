"""NFL Home — where the season is right now: this week's games and the
current standings picture at a glance."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import db as fdb
from nfl import teams as fteams

st.set_page_config(page_title="NFL | Diamond Metrics", layout="wide")
st.title("NFL")

mtime = fdb.nfl_db_mtime()
season_list = fdb.seasons(mtime)
if not season_list:
    st.info("No NFL data yet — run `python ingest/nfl_refresh.py` to build it.")
    st.stop()

season = st.selectbox("Season", season_list, index=fdb.season_index(season_list, mtime),
                       format_func=fdb.season_label)
games = fdb.load_games(season, mtime)
standings = fdb.load_standings(season, mtime)

week = fdb.current_week(games)
if week is not None:
    this_week = games[games["week"] == week]
    label = fdb.GAME_TYPE_LABELS.get(this_week.iloc[0]["game_type"], "") if not this_week.empty else ""
    style.colored_header(f"Week {week}" + (f" · {label}" if label and label != "Regular season" else ""), "headliners")
    rows = []
    for _, g in this_week.iterrows():
        away, home = g["away_team"], g["home_team"]
        if g["played"]:
            score = f"{int(g['away_score'])} – {int(g['home_score'])}"
            winner = away if g["away_score"] > g["home_score"] else (home if g["home_score"] > g["away_score"] else "tie")
            status = "Final"
        else:
            score, winner, status = "—", "", str(g.get("gametime") or "")
        rows.append({
            "Away": away, "Home": home, "Score": score, "Status": status,
            "Day": str(g.get("weekday") or ""), "Date": str(g.get("gameday") or ""),
            "_winner": winner,
        })
    if rows:
        table = pd.DataFrame(rows).drop(columns=["_winner"])
        st.dataframe(
            style.style_stats_table(table, team_col="Away", team_color_fn=fteams.color_for_abbr),
            use_container_width=True, hide_index=True,
        )

# --- Standings snapshot -----------------------------------------------------
if not standings.empty:
    style.colored_header("Standings", "batting")
    for conf in ("AFC", "NFC"):
        conf_rows = standings[standings["team_conf"] == conf]
        if conf_rows.empty:
            continue
        st.markdown(f"**{conf}**")
        display = pd.DataFrame({
            "Team": conf_rows["team"],
            "Division": conf_rows["team_division"].str.replace(f"{conf} ", "", regex=False),
            "W": conf_rows["wins"].astype(int),
            "L": conf_rows["losses"].astype(int),
            "T": conf_rows["ties"].astype(int),
            "PCT": conf_rows["win_pct"],
            "PF": conf_rows["points_for"].astype(int),
            "PA": conf_rows["points_against"].astype(int),
            "DIFF": conf_rows["point_diff"].astype(int),
        })
        st.dataframe(
            style.style_stats_table(
                display, team_col="Team", team_color_fn=fteams.color_for_abbr,
                higher_better=["W", "PCT", "PF", "DIFF"], lower_better=["L", "PA"],
                precision={"PCT": "{:.3f}"},
            ),
            use_container_width=True, hide_index=True, height=560,
        )
else:
    style.colored_header("Standings", "batting")
    st.caption(
        f"No games played yet in {fdb.season_label(season)} — standings appear once the season starts."
    )
