"""NHL Today's Games — live scores/schedule for a given date, straight from
the NHL's own schedule API (see nhl/db.py's load_schedule_for_date)."""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from nhl import db as ndb
from nhl import teams as nteams

st.set_page_config(page_title="NHL Today's Games | Diamond Metrics", layout="wide")
st.title("Today's Games")
_elo = ndb.load_elo_model()
if _elo:
    st.caption(
        f"Win% on scheduled games is our own margin-of-victory-adjusted Elo model — not real "
        f"sportsbook lines. Trained on {_elo['trained_through']} results, "
        f"{_elo['holdout_accuracy']:.1%} accuracy on its {_elo['holdout_season']} holdout."
    )

if "nhl_games_date" not in st.session_state:
    st.session_state["nhl_games_date"] = ndb.today_pacific()

nav1, nav2, nav3 = st.columns([1, 2, 1])
with nav1:
    if st.button("← Previous day"):
        st.session_state["nhl_games_date"] -= timedelta(days=1)
with nav3:
    if st.button("Next day →"):
        st.session_state["nhl_games_date"] += timedelta(days=1)
with nav2:
    st.session_state["nhl_games_date"] = st.date_input(
        "Date", st.session_state["nhl_games_date"], label_visibility="collapsed"
    )

date_str = st.session_state["nhl_games_date"].strftime("%Y-%m-%d")


@st.fragment(run_every=20)
def _render_games(date_str: str):
    games = ndb.load_schedule_for_date(date_str)
    if not games:
        st.info("No games scheduled for this date.")
        return

    def _status(game: dict) -> str:
        state = game.get("gameState")
        if state in ("OFF", "FINAL"):
            outcome = (game.get("gameOutcome") or {}).get("lastPeriodType", "REG")
            return "Final" if outcome == "REG" else f"Final/{outcome}"
        if state in ("LIVE", "CRIT"):
            period = (game.get("periodDescriptor") or {}).get("number")
            clock = (game.get("clock") or {}).get("timeRemaining")
            label = f"Period {period}" if period else "Live"
            return f"{label} — {clock}" if clock else label
        try:
            utc = datetime.fromisoformat(game["startTimeUTC"].replace("Z", "+00:00"))
            local = utc.astimezone(ZoneInfo("America/New_York"))
            return local.strftime("%-I:%M %p ET")
        except Exception:
            return state or "Scheduled"

    cols_per_row = 3
    rows = [games[i:i + cols_per_row] for i in range(0, len(games), cols_per_row)]
    for row in rows:
        cols = st.columns(cols_per_row)
        for col, game in zip(cols, row):
            away, home = game["awayTeam"], game["homeTeam"]
            with col:
                with st.container(border=True):
                    st.caption(_status(game) + f"  ·  {(game.get('venue') or {}).get('default', '')}")
                    live = game.get("gameState") in ("OFF", "FINAL", "LIVE", "CRIT")
                    a_score = away.get("score", "") if live else ""
                    h_score = home.get("score", "") if live else ""
                    l, r = st.columns(2)
                    with l:
                        st.image(away.get("logo", ""), width=40)
                        st.markdown(f"**{away['abbrev']}** {a_score}")
                    with r:
                        st.image(home.get("logo", ""), width=40)
                        st.markdown(f"**{home['abbrev']}** {h_score}")
                    if not live:
                        p_home = ndb.game_win_prob(home["abbrev"], away["abbrev"])
                        if p_home is not None:
                            st.caption(f"Win%: {away['abbrev']} {100 * (1 - p_home):.0f}% — {home['abbrev']} {100 * p_home:.0f}%")
                    if st.button("Team pages", key=f"gm{game['id']}", use_container_width=True):
                        st.session_state["nhl_team_page_selected_team"] = home["abbrev"]
                        st.switch_page("nhl/pages/team.py")


_render_games(date_str)
