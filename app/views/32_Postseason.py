"""Postseason Archive — every playoff series since 2008, by season."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Postseason | Diamond Metrics", layout="wide")
st.title("Postseason Archive")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
seasons = db.postseason_seasons(mtime)
if not seasons:
    st.info(
        "No postseason data yet — run `python ingest/refresh_data.py --postseason` "
        "to build the archive."
    )
    st.stop()

season = st.selectbox("Season", seasons)
games = db.postseason_games(season, mtime)
series = db.postseason_series(games)

if series.empty:
    st.caption(f"No completed postseason games on file for {season}.")
    st.stop()

# The champion is whoever won the World Series — surfaced on its own rather
# than left as the last row of a table, since it's the thing people came for.
final = series[series["Round"] == "World Series"]
if not final.empty:
    row = final.iloc[0]
    champ_abbr = teams.team_meta_from_nickname(row["Winner"].split()[-1])[0]
    champ_color = teams.color_for_abbr(champ_abbr) if champ_abbr else "#666666"
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:12px;padding:14px 18px;"
        f"border-radius:12px;background:var(--dm-card);border-left:4px solid {champ_color};"
        f"margin-bottom:6px'>"
        f"<div><div style='font-size:0.66rem;letter-spacing:1.2px;text-transform:uppercase;"
        f"color:var(--dm-dim)'>{season} Champion</div>"
        f"<div style='font-family:Archivo Narrow,sans-serif;font-weight:800;font-size:1.5rem;"
        f"color:var(--dm-text)'>{row['Winner']}</div>"
        f"<div style='color:var(--dm-dim);font-size:0.82rem'>Beat {row['Loser']} "
        f"{row['Result']} in the World Series</div></div></div>",
        unsafe_allow_html=True,
    )

style.colored_header("Series Results", "headliners")
st.dataframe(
    style.style_stats_table(series, precision={"Games": "{:.0f}"}),
    use_container_width=True, hide_index=True, height=430,
)

style.colored_header("Every Game", "batting")
st.caption(f"{len(games)} completed postseason games in {season}.")
detail = pd.DataFrame({
    "Date": games["date"],
    "Round": games["round"],
    "Gm": games["series_game"],
    "Away": games["away_team"],
    "R": games["away_score"],
    "Home": games["home_team"],
    "R.": games["home_score"],
})
st.dataframe(
    style.style_stats_table(detail, precision={"Gm": "{:.0f}", "R": "{:.0f}", "R.": "{:.0f}"}),
    use_container_width=True, hide_index=True, height=560,
)
