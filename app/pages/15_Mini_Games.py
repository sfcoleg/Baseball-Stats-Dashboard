import random
import sys
import time
from datetime import date
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import minigames
import style

st.set_page_config(page_title="Mini Games | Diamond Metrics", layout="wide")
st.title("Mini Games")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

season = db.get_seasons("batting")[0]
mtime = db.db_mtime()
pool = db.guesser_pool(season, mtime)
if len(pool) < 10:
    st.info("Not enough player data yet to play — check back once more of the season is in.")
    st.stop()

pool_lookup = dict(zip(pool["mlbID"], pool["Name"]))
pool_ids = sorted(pool_lookup)

style.colored_header("Player Guesser", "batting")
st.caption(
    f"Guess the {season} MLB player from their photo. Eligible pool: batters with 50+ AB "
    "or pitchers with 20+ IP that season."
)


def _guess_and_skip(form_key: str):
    """Renders the name input + Guess button (inside a form, so Enter
    submits) with a Skip button underneath. Returns (submitted_guess_or_None,
    skip_clicked)."""
    with st.form(form_key, clear_on_submit=True):
        guess = st.text_input("Who is this player?", key=f"{form_key}_input", label_visibility="collapsed",
                               placeholder="Type the player's name...")
        submitted = st.form_submit_button("Guess", use_container_width=True)
    skip_clicked = st.button("Skip", key=f"{form_key}_skip", use_container_width=True)
    return (guess if submitted else None), skip_clicked


def _show_photo(mlbID):
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.image(style.headshot_url(mlbID, width=400), use_container_width=True)


tab_daily, tab_casual, tab_timed = st.tabs(["Daily", "Casual", "Timed"])

# ---------------------------------------------------------------- Daily ----
with tab_daily:
    minigames.bootstrap_daily()
    daily = st.session_state["guesser_daily"]
    today = date.today().isoformat()
    player_id = minigames.daily_player_id(pool_ids, date.today())
    name = pool_lookup[player_id]

    streak = daily["streak"]
    st.metric("Current Streak", f"{streak} day{'s' if streak != 1 else ''}")

    if daily.get("last_played") == today:
        if daily.get("last_result") == "correct":
            st.success(f"You already got today's player: **{name}** ✅ Come back tomorrow for a new one.")
        else:
            st.error(f"You already played today. Today's player was **{name}**. Come back tomorrow for a new one.")
        _show_photo(player_id)
    else:
        _show_photo(player_id)
        guess, skip_clicked = _guess_and_skip("daily_guess")
        if guess is not None:
            minigames.record_daily_result(daily, today, minigames.is_correct_guess(guess, name))
            minigames.save_daily()
            st.rerun()
        elif skip_clicked:
            minigames.record_daily_result(daily, today, False)
            minigames.save_daily()
            st.rerun()

# --------------------------------------------------------------- Casual ----
with tab_casual:
    def _start_casual():
        st.session_state["guesser_casual"] = {
            "players": random.sample(pool_ids, min(10, len(pool_ids))),
            "idx": 0,
            "score": 0,
        }

    if "guesser_casual" not in st.session_state:
        _start_casual()
    casual = st.session_state["guesser_casual"]

    if casual["idx"] >= len(casual["players"]):
        st.success(f"Final score: {casual['score']} / {len(casual['players'])}")
        if st.button("Play Again", key="casual_replay"):
            _start_casual()
            st.rerun()
    else:
        player_id = casual["players"][casual["idx"]]
        name = pool_lookup[player_id]
        st.caption(f"Player {casual['idx'] + 1} of {len(casual['players'])}  ·  Score: {casual['score']}")
        _show_photo(player_id)
        guess, skip_clicked = _guess_and_skip("casual_guess")
        if guess is not None or skip_clicked:
            correct = guess is not None and minigames.is_correct_guess(guess, name)
            if correct:
                casual["score"] += 1
                st.toast(f"✅ Correct! {name}")
            else:
                st.toast(f"❌ It was {name}")
            casual["idx"] += 1
            st.rerun()

# ---------------------------------------------------------------- Timed ----
with tab_timed:
    def _next_timed_player(exclude_id):
        candidates = [pid for pid in pool_ids if pid != exclude_id] or pool_ids
        return random.choice(candidates)

    def _start_timed():
        first = random.choice(pool_ids)
        st.session_state["guesser_timed"] = {
            "current": first,
            "score": 0,
            "start_time": time.time(),
            "ended": False,
        }

    @st.fragment(run_every="1s")
    def _timed_countdown():
        game = st.session_state.get("guesser_timed")
        if not game or game["ended"]:
            return
        remaining = max(0, 60 - (time.time() - game["start_time"]))
        st.metric("Time Left", f"{int(remaining)}s")
        if remaining <= 0:
            game["ended"] = True
            st.rerun()

    timed = st.session_state.get("guesser_timed")

    if timed is None:
        st.write("Guess as many players as you can in 60 seconds.")
        if st.button("Start", key="timed_start"):
            _start_timed()
            st.rerun()
    elif timed["ended"] or (time.time() - timed["start_time"]) >= 60:
        st.success(f"Time's up! Final score: {timed['score']}")
        if st.button("Play Again", key="timed_replay"):
            _start_timed()
            st.rerun()
    else:
        _timed_countdown()
        st.caption(f"Score: {timed['score']}")
        player_id = timed["current"]
        name = pool_lookup[player_id]
        _show_photo(player_id)
        guess, skip_clicked = _guess_and_skip("timed_guess")
        if guess is not None or skip_clicked:
            correct = guess is not None and minigames.is_correct_guess(guess, name)
            if correct:
                timed["score"] += 1
            timed["current"] = _next_timed_player(player_id)
            st.rerun()
