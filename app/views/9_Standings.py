import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Standings | Diamond Metrics", layout="wide")

clicked_team = st.query_params.get("team")
if clicked_team:
    st.session_state["team_page_selected_team"] = clicked_team
    st.switch_page("views/4_Team.py")

st.title("Standings")
if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
standings = db.load_standings(mtime)

if standings.empty:
    st.info("No standings data yet — run the ingest script.")
    st.stop()

playoff_odds = db.compute_playoff_odds(mtime)
if not playoff_odds.empty:
    standings = standings.merge(playoff_odds[["team_abbr", "playoff_pct"]], on="team_abbr", how="left")

_CLINCH_SYMBOLS = {"division_clinch": "z", "wildcard_clinch": "x", "eliminated": "e"}
clinch_symbols = {
    e["team_abbr"]: _CLINCH_SYMBOLS[e["kind"]] for e in db.clinch_elimination_status(mtime)
}

DIVISION_ORDER = ["AL East", "AL Central", "AL West", "NL East", "NL Central", "NL West"]

for league in ["AL", "NL"]:
    style.colored_header(f"{league} — American League" if league == "AL" else f"{league} — National League", "batting" if league == "AL" else "pitching")
    league_divs = [d for d in DIVISION_ORDER if d.startswith(league)]
    # Stacked full-width (not 3-across) — with RS/RA/Diff/Playoff Odds added,
    # the table is too wide for a third-of-page column at most viewport
    # sizes; each division's own horizontal scroll (rather than 3 squeezed
    # side by side) keeps every column readable.
    for division in league_divs:
        st.markdown(f"**{division}**")
        div_standings = standings[standings["division"] == division].sort_values("div_rank")
        display_cols = {
            "team_abbr": "Team", "wins": "W", "losses": "L", "pct": "PCT", "games_back": "GB",
            "streak": "Streak", "runs_scored": "RS", "runs_allowed": "RA", "run_diff": "Diff",
        }
        if "playoff_pct" in div_standings.columns:
            display_cols["playoff_pct"] = "Playoff%"
        display = div_standings[list(display_cols)].rename(columns=display_cols)
        st.markdown(
            "<div style='overflow-x:auto'>"
            + style.standings_table(display, teams.color_for_abbr, clinch_symbols)
            + "</div>",
            unsafe_allow_html=True,
        )
