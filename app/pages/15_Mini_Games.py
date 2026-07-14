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

mtime = db.db_mtime()
season = db.get_seasons("batting")[0]

game_guesser, game_grid, game_hl = st.tabs(["Player Guesser", "Diamond Grid", "Higher or Lower"])


def _guess_and_skip(form_key: str, skip_label: str = "Skip"):
    """Renders the name input + Guess button (inside a form, so Enter
    submits) with a Skip button underneath. Returns (submitted_guess_or_None,
    skip_clicked)."""
    with st.form(form_key, clear_on_submit=True):
        guess = st.text_input("Who is this player?", key=f"{form_key}_input", label_visibility="collapsed",
                               placeholder="Type the player's name...")
        submitted = st.form_submit_button("Guess", use_container_width=True)
    skip_clicked = st.button(skip_label, key=f"{form_key}_skip", use_container_width=True)
    return (guess if submitted else None), skip_clicked


def _show_photo(mlbID, width=400):
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.image(style.headshot_url(mlbID, width=width), use_container_width=True)


# ============================================================== Guesser ====
with game_guesser:
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

    tab_daily, tab_casual, tab_timed = st.tabs(["Daily", "Casual", "Timed"])

    # ------------------------------------------------------------ Daily ----
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

    # ----------------------------------------------------------- Casual ----
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

    # ------------------------------------------------------------ Timed ----
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

# =========================================================== Diamond Grid ==
with game_grid:
    grid_pool = db.grid_pool(mtime)
    categories, names, current_team = grid_pool["categories"], grid_pool["names"], grid_pool["current_team"]

    style.colored_header("Diamond Grid", "chart")
    st.caption(
        "Fill all 9 cells with a player who matches both their row and column — a different "
        "player for every cell. Full name required (accents/case don't matter)."
    )

    def _new_grid_state(seed_source):
        picked = minigames.pick_grid_categories(categories, seed_source)
        if picked is None:
            return None
        row_keys, col_keys = picked
        return {
            "row_keys": row_keys,
            "col_keys": col_keys,
            "cells": {},  # "r_c" -> {"correct": bool, "name": str, "reason": str}
            "used_ids": set(),
        }

    def _render_grid(state_key, grid, key_prefix):
        if grid is None:
            st.error("Couldn't build a valid grid right now — try again.")
            return
        row_keys, col_keys = grid["row_keys"], grid["col_keys"]
        solved = len(grid["cells"])

        header_cols = st.columns([1.4, 1, 1, 1])
        header_cols[0].write("")
        for i, ck in enumerate(col_keys):
            header_cols[i + 1].markdown(f"**{categories[ck]['label']}**")

        for rk in row_keys:
            row_cols = st.columns([1.4, 1, 1, 1])
            row_cols[0].markdown(f"**{categories[rk]['label']}**")
            for i, ck in enumerate(col_keys):
                cell_key = f"{rk}|{ck}"
                with row_cols[i + 1]:
                    result = grid["cells"].get(cell_key)
                    if result and result["correct"]:
                        abbr = current_team.get(result["mlbID"], "")
                        st.success(f"{result['name']}" + (f"  ({abbr})" if abbr else ""))
                    elif result:
                        st.error("Try again" if result["reason"] == "not_eligible" else "Already used")
                        _grid_cell_input(state_key, cell_key, key_prefix)
                    else:
                        _grid_cell_input(state_key, cell_key, key_prefix)

        st.caption(f"Solved: {solved} / 9")
        if solved == 9:
            st.success("Immaculate! You filled the whole grid. 🎉")

    def _grid_cell_input(state_key, cell_key, key_prefix):
        input_key = f"{key_prefix}_{cell_key}"
        guess = st.text_input("guess", key=input_key, label_visibility="collapsed", placeholder="Player name")
        if guess:
            grid = st.session_state[state_key]
            rk, ck = cell_key.split("|")
            result = minigames.check_grid_guess(guess, categories, names, rk, ck, grid["used_ids"])
            grid["cells"][cell_key] = result
            if result["correct"]:
                grid["used_ids"].add(result["mlbID"])
            del st.session_state[input_key]
            st.rerun()

    tab_grid_daily, tab_grid_practice = st.tabs(["Daily", "Practice"])

    with tab_grid_daily:
        today_iso = date.today().isoformat()
        if st.session_state.get("grid_daily_date") != today_iso:
            st.session_state["grid_daily"] = _new_grid_state(today_iso)
            st.session_state["grid_daily_date"] = today_iso
        _render_grid("grid_daily", st.session_state["grid_daily"], "griddaily")

    with tab_grid_practice:
        if "grid_practice" not in st.session_state:
            st.session_state["grid_practice"] = _new_grid_state(None)
        if st.button("New Grid", key="grid_practice_new"):
            st.session_state["grid_practice"] = _new_grid_state(None)
            st.rerun()
        _render_grid("grid_practice", st.session_state["grid_practice"], "gridpractice")

# ========================================================= Higher or Lower ==
with game_hl:
    batters = db.load_batting(season, mtime)
    batters = batters.loc[batters["AB"] >= 50]
    if len(batters) < 2:
        st.info("Not enough player data yet to play — check back once more of the season is in.")
        st.stop()
    hl_lookup = batters.set_index("mlbID").to_dict("index")
    hl_ids = list(hl_lookup)

    style.colored_header("Higher or Lower", "batting")
    st.caption(
        f"Two {season} batters (50+ AB), one random stat each round — WAR, HR, RBI, SB, Age, OPS, "
        "BA, Hits, or Runs. Guess whether the right player is higher or lower than the left, and "
        "keep the streak alive. The stat changes every round."
    )

    def _start_hl():
        first, second = random.sample(hl_ids, 2)
        st.session_state["hl_game"] = {
            "current_id": first,
            "next_id": second,
            "stat": random.choice(list(minigames.HL_STATS)),
            "score": 0,
            "used_ids": {first, second},
            "ended": False,
            "reveal": None,
        }

    hl_game = st.session_state.get("hl_game")

    if hl_game is None:
        st.write("Build the longest streak you can.")
        if st.button("Start", key="hl_start"):
            _start_hl()
            st.rerun()
    elif hl_game["ended"]:
        st.error(f"Streak over — final score: {hl_game['score']}. {hl_game['reveal']}")
        if st.button("Play Again", key="hl_replay"):
            _start_hl()
            st.rerun()
    else:
        stat = hl_game["stat"]
        stat_label = minigames.HL_STATS[stat]["label"]
        current = hl_lookup[hl_game["current_id"]]
        nxt = hl_lookup[hl_game["next_id"]]

        st.caption(f"Score: {hl_game['score']}")
        col1, col2 = st.columns(2)
        with col1:
            _show_photo(hl_game["current_id"], width=250)
            st.markdown(f"**{current['Name']}**")
            st.metric(stat_label, minigames.hl_format(stat, current[stat]))
        with col2:
            _show_photo(hl_game["next_id"], width=250)
            st.markdown(f"**{nxt['Name']}**")
            st.metric(stat_label, "?")
            higher_col, lower_col = st.columns(2)
            higher_clicked = higher_col.button("Higher ⬆️", key="hl_higher", use_container_width=True)
            lower_clicked = lower_col.button("Lower ⬇️", key="hl_lower", use_container_width=True)

        if higher_clicked or lower_clicked:
            correct = minigames.hl_check(current[stat], nxt[stat], guess_higher=higher_clicked)
            actual = minigames.hl_format(stat, nxt[stat])
            if correct:
                st.toast(f"✅ {nxt['Name']}: {actual} {stat_label}")
                hl_game["score"] += 1
                hl_game["current_id"] = hl_game["next_id"]
                remaining = [i for i in hl_ids if i not in hl_game["used_ids"]] or \
                    [i for i in hl_ids if i != hl_game["current_id"]]
                hl_game["next_id"] = random.choice(remaining)
                hl_game["used_ids"].add(hl_game["next_id"])
                hl_game["stat"] = random.choice(list(minigames.HL_STATS))
            else:
                hl_game["ended"] = True
                hl_game["reveal"] = f"{nxt['Name']} was {actual} {stat_label} vs. {current['Name']}'s {minigames.hl_format(stat, current[stat])}."
            st.rerun()
