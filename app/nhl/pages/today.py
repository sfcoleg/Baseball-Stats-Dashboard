"""NHL Today's Games — live scores/schedule for a given date, straight from
the NHL's own schedule API (see nhl/db.py's load_schedule_for_date). Card
layout mirrors the MLB side's Today's Games exactly: a matchup-gradient
background in each team's colors, logo/abbr/name on the outside, score/
status in the middle, and odds + win probability text under each team
(not a bar chart — see nstyle.win_prob_html)."""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import prefs
import style
from nhl import db as ndb
from nhl import style as nstyle
from nhl import teams as nteams

st.set_page_config(page_title="NHL Today's Games | Diamond Metrics", layout="wide")
st.title("Today's Games")

# Must go through prefs.resolve_theme() (an explicit Light/Dark choice in
# Settings, not just whatever Streamlit's raw context reports) — same fix
# as the MLB side's Today's Games, for the same reason: reading
# st.context.theme.type directly here would let this page's matchup-
# gradient colors disagree with the --dm-* CSS variables everywhere else.
_detected = getattr(getattr(getattr(st, "context", None), "theme", None), "type", None)
_THEME = prefs.resolve_theme(_detected)

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


def _records() -> dict:
    standings = ndb.load_standings()
    if standings.empty:
        return {}
    return {
        r["teamAbbrev"]: {
            "record": f"{int(r['wins'])}-{int(r['losses'])}-{int(r['otLosses'])}",
            "last10": f"{int(r['l10Wins'])}-{int(r['l10Losses'])}-{int(r['l10OtLosses'])}"
            if "l10Wins" in r else None,
        }
        for _, r in standings.iterrows()
    }


@st.fragment(run_every=20)
def _render_games(date_str: str):
    games = ndb.load_schedule_for_date(date_str)
    if not games:
        st.info("No games scheduled for this date.")
        return
    records = _records()

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

    for game in games:
        away, home = game["awayTeam"], game["homeTeam"]
        state = game.get("gameState")
        started = state not in ("FUT", "PRE")
        live_now = state in ("LIVE", "CRIT")
        away_color, home_color = nteams.color_for_abbr(away["abbrev"]), nteams.color_for_abbr(home["abbrev"])
        # Pregame odds, computed regardless of whether the game has
        # started — kept showing after puck drop (and after Final) rather
        # than disappearing, same as the MLB side's Today's Games.
        p_home = ndb.game_win_prob(home["abbrev"], away["abbrev"])

        # Same matchup-gradient card background as the MLB side — away
        # color on the left, home on the right, meeting in a neutral band.
        card_key = f"nhlgame{game['id']}"
        st.markdown(
            f"<style>.st-key-{card_key}{{background:"
            f"{style.matchup_gradient(away_color, home_color, _THEME)} !important;}}</style>",
            unsafe_allow_html=True,
        )
        with st.container(border=True, key=card_key):
            if live_now:
                st.markdown(
                    "<div style='display:flex;justify-content:flex-end;margin:-4px 0 -6px 0'>"
                    "<span style='background-color:var(--dm-red);color:#FFFFFF;padding:3px 12px;"
                    "border-radius:8px;font-weight:700;font-size:0.75rem;letter-spacing:0.5px'>LIVE</span></div>",
                    unsafe_allow_html=True,
                )
            acol, mid, hcol = st.columns([3, 2, 3])

            def _team_col(team, color, prob):
                logo_html = (
                    f"<img src='{team.get('logo', '')}' style='height:48px;width:48px;object-fit:contain;"
                    f"vertical-align:middle;margin-right:8px'>" if team.get("logo") else ""
                )
                st.markdown(
                    f"<div style='display:flex;align-items:center'>{logo_html}"
                    f"<span style='background-color:{color}66;color:var(--dm-text);padding:3px 10px;"
                    f"border-radius:8px;font-weight:700'>{team['abbrev']}</span> &nbsp;"
                    f"<span style='font-weight:700;font-size:1.1rem'>{nteams.nickname_for_abbr(team['abbrev'])}</span></div>",
                    unsafe_allow_html=True,
                )
                info = records.get(team["abbrev"], {})
                if info.get("record"):
                    st.caption(f"Record: {info['record']}")
                if info.get("last10"):
                    st.caption(f"Last 10: {info['last10']}")
                if prob is not None:
                    st.markdown(nstyle.win_prob_html(prob * 100), unsafe_allow_html=True)

            with acol:
                _team_col(away, away_color, None if p_home is None else 1 - p_home)

            with mid:
                if started:
                    st.markdown(
                        f"<div style='text-align:center;font-size:1.8rem;font-weight:700'>"
                        f"{away.get('score', 0)} - {home.get('score', 0)}</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        "<div style='text-align:center;color:var(--dm-dim);padding-top:8px'>@</div>",
                        unsafe_allow_html=True,
                    )
                st.markdown(
                    f"<div style='text-align:center;color:var(--dm-dim)'>{_status(game)}</div>", unsafe_allow_html=True
                )
                venue = (game.get("venue") or {}).get("default")
                if venue:
                    st.markdown(f"<div style='text-align:center;color:var(--dm-dim);font-size:0.85rem'>{venue}</div>",
                                unsafe_allow_html=True)
                if started:
                    if st.button("Game Center", key=f"gm{game['id']}", use_container_width=True):
                        st.session_state["nhl_selected_game"] = int(game["id"])
                        st.switch_page("nhl/pages/game.py")
                elif st.button("Team pages", key=f"gm{game['id']}", use_container_width=True):
                    st.session_state["nhl_team_page_selected_team"] = home["abbrev"]
                    st.switch_page("nhl/pages/team.py")

            with hcol:
                _team_col(home, home_color, p_home)

            if p_home is None:
                st.caption("Not enough season data yet to generate a prediction for this game.")


_render_games(date_str)
