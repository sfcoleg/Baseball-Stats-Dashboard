import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Standings | Sabermetrics Dashboard", layout="wide")
st.title("Standings")
st.caption("Current MLB division standings, from the MLB Stats API.")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
standings = db.load_standings(mtime)

if standings.empty:
    st.info("No standings data yet — run the ingest script.")
    st.stop()

DIVISION_ORDER = ["AL East", "AL Central", "AL West", "NL East", "NL Central", "NL West"]

for league in ["AL", "NL"]:
    style.colored_header(f"{league} — American League" if league == "AL" else f"{league} — National League", "batting" if league == "AL" else "pitching")
    league_divs = [d for d in DIVISION_ORDER if d.startswith(league)]
    cols = st.columns(3)
    for col, division in zip(cols, league_divs):
        with col:
            st.markdown(f"**{division}**")
            div_standings = standings[standings["division"] == division].sort_values("div_rank")
            display = div_standings[["team_abbr", "wins", "losses", "pct", "games_back", "streak"]].rename(columns={
                "team_abbr": "Team", "wins": "W", "losses": "L", "pct": "PCT", "games_back": "GB", "streak": "Streak",
            })
            st.dataframe(
                style.style_stats_table(display, team_col="Team", team_color_fn=teams.color_for_abbr),
                use_container_width=True,
                hide_index=True,
            )
