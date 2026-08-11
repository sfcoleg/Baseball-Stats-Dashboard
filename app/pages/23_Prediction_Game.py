import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import predictions
import style
import teams

st.set_page_config(page_title="Prediction Game | Diamond Metrics", layout="wide")
st.title("Prediction Game")
st.caption("Pick today's winners. One point per correct pick, tallied on the leaderboard below.")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

if not predictions._configured():
    st.info(
        "Not configured yet — this feature needs a private GitHub Gist to store picks in "
        "(so they survive this app's daily redeploys). See predictions.py's module docstring "
        "for the two secrets it needs: predictions_gist_token and predictions_gist_id."
    )
    st.stop()

mtime = db.db_mtime()
games = db.load_todays_games(mtime)
today = db.today_pacific().isoformat()

name = st.text_input("Your name", placeholder="e.g. Cole")

if games.empty:
    st.info("No games scheduled for today — check back on game day.")
else:
    live_scores = db.load_live_scores(games.iloc[0]["date"])
    all_picks = predictions.load_picks()
    my_picks = {p["game_pk"]: p["pick_abbr"] for p in all_picks if p["name"] == name} if name else {}

    with st.form("prediction_form"):
        selections = {}
        for _, row in games.iterrows():
            live = live_scores.get(row["game_pk"], {})
            status = live.get("status") or row["status"]
            locked = status not in ("Scheduled", "Pre-Game", "Warmup", "Delayed Start")

            away_color, home_color = teams.color_for_abbr(row["away_abbr"]), teams.color_for_abbr(row["home_abbr"])
            st.markdown(
                f"<span style='background-color:{away_color}66;color:#FAFAFA;padding:3px 10px;"
                f"border-radius:8px;font-weight:700'>{row['away_abbr']}</span> {row['away_team']} @ "
                f"<span style='background-color:{home_color}66;color:#FAFAFA;padding:3px 10px;"
                f"border-radius:8px;font-weight:700'>{row['home_abbr']}</span> {row['home_team']}",
                unsafe_allow_html=True,
            )
            if locked:
                current = my_picks.get(row["game_pk"])
                st.caption(f"Picks locked — game has started. {'Your pick: ' + current if current else 'You did not pick this game.'}")
            else:
                default = my_picks.get(row["game_pk"])
                options = [row["away_abbr"], row["home_abbr"]]
                selections[row["game_pk"]] = st.radio(
                    "Winner", options, index=options.index(default) if default in options else None,
                    key=f"pick_{row['game_pk']}", horizontal=True, label_visibility="collapsed",
                )
            st.divider()

        submitted = st.form_submit_button("Save picks")

    if submitted:
        if not name.strip():
            st.error("Enter your name first.")
        else:
            saved = 0
            for _, row in games.iterrows():
                pick = selections.get(row["game_pk"])
                if not pick:
                    continue
                success, message = predictions.submit_pick(
                    name.strip(), row["game_pk"], today, pick, row["away_abbr"], row["home_abbr"],
                )
                if success:
                    saved += 1
                else:
                    st.error(message)
                    break
            if saved:
                st.success(f"Saved {saved} pick{'s' if saved != 1 else ''}!")
                st.rerun()

style.colored_header("Leaderboard", "chart")
leaderboard = predictions.compute_leaderboard(predictions.load_picks(), db.load_schedule_for_date)
if leaderboard.empty:
    st.caption("No resolved picks yet — check back once today's games finish.")
else:
    st.dataframe(leaderboard, hide_index=True, use_container_width=True)
