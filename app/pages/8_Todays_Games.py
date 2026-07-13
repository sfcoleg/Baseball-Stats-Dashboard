import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Today's Games | Diamond Metrics", layout="wide")
st.title("Today's Games")
st.caption("Our own win probabilities/odds — not real sportsbook lines. Based on Log5 + starter/bullpen ERA, lineup wOBA, and platoon splits.")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
games = db.load_todays_games(mtime)

if games.empty:
    st.info("No games scheduled for today.")
    st.stop()

season = db.get_seasons("batting")[0]
pitching_raw = db.load_pitching(season, mtime)
pitching = teams.add_team_abbr(pitching_raw)
batting = teams.add_team_abbr(db.load_batting(season, mtime))
live_scores = db.load_live_scores(games.iloc[0]["date"])
if st.button("Refresh live scores"):
    db.load_live_scores.clear()
    st.rerun()

_pitcher_ids = tuple(sorted({
    int(v) for col in ("away_pitcher_mlbID", "home_pitcher_mlbID")
    for v in games[col].dropna().tolist()
}))
pitcher_hands = db.load_pitcher_handedness(_pitcher_ids)


def team_color(abbr):
    return teams.color_for_abbr(teams.normalize_mlb_abbr(abbr))


def pitcher_era(mlbID):
    if mlbID is None or pd.isna(mlbID):
        return None
    match = pitching[pitching["mlbID"] == int(mlbID)]
    return None if match.empty else match.iloc[0]["ERA"]


for _, row in games.iterrows():
    pred = db.predict_game(row, pitching, batting, pitcher_hands)
    away_color, home_color = team_color(row["away_abbr"]), team_color(row["home_abbr"])
    live = live_scores.get(row["game_pk"], {})
    status = live.get("status") or row["status"]
    started = status not in ("Scheduled", "Pre-Game", "Warmup", "Delayed Start", "Postponed")

    with st.container(border=True):
        if status == "In Progress":
            st.markdown(
                "<div style='display:flex;justify-content:flex-end;margin:-4px 0 -6px 0'>"
                "<span style='background-color:#D32F2F;color:#FFFFFF;padding:3px 12px;"
                "border-radius:8px;font-weight:700;font-size:0.75rem;letter-spacing:0.5px'>"
                "LIVE</span></div>",
                unsafe_allow_html=True,
            )
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
            if started and live.get("away_score") is not None and live.get("home_score") is not None:
                st.markdown(
                    f"<div style='text-align:center;font-size:1.8rem;font-weight:700'>"
                    f"{int(live['away_score'])} - {int(live['home_score'])}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    "<div style='text-align:center;color:#9AA3B5;padding-top:8px'>@</div>",
                    unsafe_allow_html=True,
                )
            status_line = status
            if status == "In Progress" and live.get("inning"):
                status_line = live["inning"]
            st.caption(f"<div style='text-align:center'>{status_line}</div>", unsafe_allow_html=True)
            if row.get("game_time") and not started:
                st.markdown(
                    f"<div class='game-time-local' data-utc='{row['game_time']}' "
                    f"style='text-align:center;color:#9AA3B5;font-size:0.85rem'>{row['game_time']}</div>",
                    unsafe_allow_html=True,
                )
            if row.get("venue"):
                st.caption(f"<div style='text-align:center'>{row['venue']}</div>", unsafe_allow_html=True)

            if started:
                box_key = f"show_box_{row['game_pk']}"
                is_shown = st.session_state.get(box_key, False)
                if st.button("Hide box score" if is_shown else "Show box score", key=f"btn_{row['game_pk']}", use_container_width=True):
                    st.session_state[box_key] = not is_shown
                    st.rerun()

                wp_key = f"show_wp_{row['game_pk']}"
                wp_shown = st.session_state.get(wp_key, False)
                if st.button("Hide win probability" if wp_shown else "Show win probability", key=f"wp_btn_{row['game_pk']}", use_container_width=True):
                    st.session_state[wp_key] = not wp_shown
                    st.rerun()

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

        if started and st.session_state.get(f"show_box_{row['game_pk']}", False):
            linescore = db.load_linescore(row["game_pk"])
            if not linescore or "innings" not in linescore:
                st.caption("Box score not available yet.")
            else:
                st.markdown(
                    style.box_score_table(
                        linescore, row["away_abbr"], row["home_abbr"], away_color, home_color,
                    ),
                    unsafe_allow_html=True,
                )

        if started and st.session_state.get(f"show_wp_{row['game_pk']}", False):
            wp_df = db.load_win_probability(row["game_pk"])
            if wp_df.empty:
                st.caption("Win probability not available yet.")
            else:
                st.caption(
                    "Our own live estimate from the score and outs remaining — not an official "
                    "MLB stat, and it doesn't account for base-out state (e.g. bases loaded vs. "
                    "empty with the same score/outs looks identical here)."
                )
                st.plotly_chart(
                    style.win_probability_chart(wp_df, row["home_abbr"], home_color),
                    use_container_width=True,
                    key=f"wp_chart_{row['game_pk']}",
                )

# Converts each game's UTC start time (stored in data-utc, e.g. "2026-07-12T23:10:00Z")
# to the viewer's own local time/timezone client-side, so a West Coast visitor sees
# PDT and an East Coast visitor sees EDT for the same game. st.markdown's
# unsafe_allow_html doesn't execute <script> tags (innerHTML-inserted scripts never
# run, per browser spec) — st.components.v1.html() runs in a real iframe, so it
# reaches into the parent document to update the placeholder divs instead.
# setInterval keeps re-applying because Streamlit reruns (e.g. clicking "Show box
# score") recreate those divs with fresh unconverted text.
components.html(
    """
    <script>
    (function() {
        function updateGameTimes() {
            const els = window.parent.document.querySelectorAll('.game-time-local[data-utc]');
            els.forEach(function(el) {
                const d = new Date(el.dataset.utc);
                if (isNaN(d.getTime())) return;
                el.textContent = d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit', timeZoneName: 'short'});
            });
        }
        updateGameTimes();
        setInterval(updateGameTimes, 1000);
    })();
    </script>
    """,
    height=0,
)
