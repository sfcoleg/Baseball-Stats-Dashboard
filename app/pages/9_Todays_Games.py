import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Today's Games | Sabermetrics Dashboard", layout="wide")
st.title("Today's Games")
st.caption(
    "Win probabilities and odds are calculated by this dashboard — not real sportsbook lines. "
    "The model uses the Log5 method (each team's season winning percentage) plus a home-field-advantage "
    "adjustment, then nudges the prediction based on how each probable starter's ERA compares to "
    "qualified league-average ERA. There's no park factors, bullpen strength, injuries, or weather in this — "
    "treat it as a sabermetrics estimate, not a betting recommendation."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
games = db.load_todays_games(mtime)

if games.empty:
    st.info("No games scheduled for today.")
    st.stop()

season = db.get_seasons("batting")[0]
pitching = db.load_pitching(season, mtime)

_ABBR_FIX = {"AZ": "ARI"}


def team_color(abbr):
    return teams.color_for_abbr(_ABBR_FIX.get(abbr, abbr))


def pitcher_era(mlbID):
    if mlbID is None or pd.isna(mlbID):
        return None
    match = pitching[pitching["mlbID"] == int(mlbID)]
    return None if match.empty else match.iloc[0]["ERA"]


for _, row in games.iterrows():
    pred = db.predict_game(row, pitching)
    away_color, home_color = team_color(row["away_abbr"]), team_color(row["home_abbr"])

    with st.container(border=True):
        acol, mid, hcol = st.columns([3, 2, 3])

        with acol:
            st.markdown(
                f"<span style='background-color:{away_color}66;color:#FAFAFA;padding:3px 10px;"
                f"border-radius:8px;font-weight:700'>{row['away_abbr']}</span> &nbsp;"
                f"<span style='font-weight:700;font-size:1.1rem'>{row['away_team']}</span>",
                unsafe_allow_html=True,
            )
            era = pitcher_era(row.get("away_pitcher_mlbID"))
            sp_line = row["away_pitcher_name"] or "TBD"
            if era is not None and pd.notna(era):
                sp_line += f" ({era:.2f} ERA)"
            st.caption(f"SP: {sp_line}")
            st.caption(f"Record: {row['away_wins']}-{row['away_losses']}")
            if pred:
                st.markdown(
                    f"<div style='font-size:1.3rem;font-weight:700'>{pred['away_odds']}</div>"
                    f"<div style='color:#9AA3B5'>{pred['away_prob']*100:.0f}% win probability</div>",
                    unsafe_allow_html=True,
                )

        with mid:
            st.markdown(
                f"<div style='text-align:center;color:#9AA3B5;padding-top:8px'>@</div>",
                unsafe_allow_html=True,
            )
            st.caption(f"Status: {row['status']}")

        with hcol:
            st.markdown(
                f"<span style='background-color:{home_color}66;color:#FAFAFA;padding:3px 10px;"
                f"border-radius:8px;font-weight:700'>{row['home_abbr']}</span> &nbsp;"
                f"<span style='font-weight:700;font-size:1.1rem'>{row['home_team']}</span>",
                unsafe_allow_html=True,
            )
            era = pitcher_era(row.get("home_pitcher_mlbID"))
            sp_line = row["home_pitcher_name"] or "TBD"
            if era is not None and pd.notna(era):
                sp_line += f" ({era:.2f} ERA)"
            st.caption(f"SP: {sp_line}")
            st.caption(f"Record: {row['home_wins']}-{row['home_losses']}")
            if pred:
                st.markdown(
                    f"<div style='font-size:1.3rem;font-weight:700'>{pred['home_odds']}</div>"
                    f"<div style='color:#9AA3B5'>{pred['home_prob']*100:.0f}% win probability</div>",
                    unsafe_allow_html=True,
                )

        if not pred:
            st.caption("Not enough season data yet to generate a prediction for this game.")
