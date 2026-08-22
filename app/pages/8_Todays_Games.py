import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import localstorage_bridge
import predictions
import style
import teams

st.set_page_config(page_title="Today's Games | Diamond Metrics", layout="wide")
st.title("Today's Games")
st.caption(
    "Our own win probabilities/odds — not real sportsbook lines. From a logistic-regression model "
    "trained on 2015-2025 games (56.7% accuracy on its 2025 holdout): team record, run differential, "
    "prior-season strength, each probable starter's prior-season ERA, and home field."
)

# Normally seeded by predictions.bootstrap() in main.py, but Streamlit's
# legacy pages/-folder auto-discovery can route a direct URL hit straight to
# this page's script (bypassing main.py entirely) — so bootstrap defensively
# here too. The actual localStorage->query-param redirect has to run from
# HERE (not main.py) — see following.py's identical comment on this in
# pages/13_Following.py for why.
predictions.bootstrap()
localstorage_bridge.register("predictions", predictions.STORAGE_KEY)
localstorage_bridge.redirect()

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


def team_color(abbr):
    return teams.color_for_abbr(teams.normalize_mlb_abbr(abbr))


def team_logo(abbr):
    team_id = teams.team_id_for_abbr(teams.normalize_mlb_abbr(abbr))
    return style.team_logo_for_season(teams.normalize_mlb_abbr(abbr), team_id, season) if team_id else None


def pitcher_era(mlbID):
    if mlbID is None or pd.isna(mlbID):
        return None
    match = pitching[pitching["mlbID"] == int(mlbID)]
    return None if match.empty else match.iloc[0]["ERA"]


# A fragment (not the whole page) so live scores can auto-refresh on a timer
# without losing scroll position, "Show box score" toggles, or in-progress
# pick selections elsewhere on the page. Clears the live-scores cache on
# every tick rather than relying on that cache's own ttl to expire in sync —
# ttl and run_every racing against each other would mean some ticks render
# stale data. st.rerun() defaults to a full-page rerun even inside a
# fragment; scope="fragment" keeps a button click (box score toggle, a
# pick) from blowing away that same isolation.
@st.fragment(run_every="20s")
def render_games():
    db.load_live_scores.clear()
    live_scores = db.load_live_scores(games.iloc[0]["date"])
    my_picks = {p["game_pk"]: p["pick_abbr"] for p in predictions.get_picks()}

    for _, row in games.iterrows():
        pred = db.predict_game(row, mtime)
        away_color, home_color = team_color(row["away_abbr"]), team_color(row["home_abbr"])
        away_logo, home_logo = team_logo(row["away_abbr"]), team_logo(row["home_abbr"])
        live = live_scores.get(row["game_pk"], {})
        status = live.get("status") or row["status"]
        started = status not in ("Scheduled", "Pre-Game", "Warmup", "Delayed Start", "Postponed")

        # Compares this poll's score against the previous one (kept in
        # session_state, since the fragment has no other memory between its
        # own 20s reruns) to detect a run just being scored — drives the
        # "+N" flash next to whichever team's abbreviation badge scored.
        # Updated for every game on every run regardless of whether this
        # particular game changed, so a game that hasn't started yet (no
        # scores) doesn't leave a stale/missing entry that would misfire
        # once it does.
        prev_scores = st.session_state.setdefault("_prev_scores", {})
        away_score, home_score = live.get("away_score"), live.get("home_score")
        prev_away_score, prev_home_score = prev_scores.get(row["game_pk"], (None, None))
        away_runs_scored = (
            away_score - prev_away_score
            if away_score is not None and prev_away_score is not None and away_score > prev_away_score
            else None
        )
        home_runs_scored = (
            home_score - prev_home_score
            if home_score is not None and prev_home_score is not None and home_score > prev_home_score
            else None
        )
        prev_scores[row["game_pk"]] = (away_score, home_score)

        with st.container(border=True):
            if status == "In Progress":
                st.markdown(
                    "<div style='display:flex;justify-content:flex-end;margin:-4px 0 -6px 0'>"
                    "<span style='background-color:#D32F2F;color:#FFFFFF;padding:3px 12px;"
                    "border-radius:8px;font-weight:700;font-size:0.75rem;letter-spacing:0.5px' class='live-badge'>"
                    "LIVE</span></div>",
                    unsafe_allow_html=True,
                )
            acol, mid, hcol = st.columns([3, 2, 3])

            with acol:
                logo_html = (
                    f"<img src='{away_logo}' style='height:32px;width:32px;object-fit:contain;"
                    f"vertical-align:middle;margin-right:6px'>" if away_logo else ""
                )
                st.markdown(
                    f"<div style='display:flex;align-items:center'>{logo_html}"
                    f"<span style='background-color:{away_color}66;color:#FAFAFA;padding:3px 10px;"
                    f"border-radius:8px;font-weight:700'>{row['away_abbr']}</span> &nbsp;"
                    f"<span style='font-weight:700;font-size:1.1rem'>{row['away_team']}</span></div>",
                    unsafe_allow_html=True,
                )
                era = pitcher_era(row.get("away_pitcher_mlbID"))
                sp_line = row["away_pitcher_name"] or "TBD"
                if era is not None and pd.notna(era):
                    sp_line += f" ({era:.2f} ERA)"
                st.caption(f"SP: {sp_line}")
                st.caption(f"Record: {row['away_wins']}-{row['away_losses']}")
                away_form = db.team_recent_form(row["away_abbr"], mtime)
                if away_form:
                    st.caption(f"Last 10: {away_form['last10']} · {away_form['streak']}")
                if pred:
                    st.markdown(
                        f"<div style='font-size:1.3rem;font-weight:700'>{pred['away_odds']}</div>"
                        f"<div style='color:#9AA3B5'>{pred['away_prob']*100:.0f}% win probability</div>",
                        unsafe_allow_html=True,
                    )

            with mid:
                if started and live.get("away_score") is not None and live.get("home_score") is not None:
                    away_span_class = "score-pop" if away_runs_scored else ""
                    home_span_class = "score-pop" if home_runs_scored else ""
                    # Badges sit right next to whichever number changed and
                    # fly a short distance TOWARD it (away's badge is to its
                    # left and flies right; home's is to its right and flies
                    # left) — see style.run_scored_badge_html for the sign
                    # convention and main.py's diamondRunFlyIn/.score-pop
                    # keyframes for how the two are timed to land together.
                    away_badge = style.run_scored_badge_html(away_runs_scored, away_color, "10px") if away_runs_scored else ""
                    home_badge = style.run_scored_badge_html(home_runs_scored, home_color, "-10px") if home_runs_scored else ""
                    st.markdown(
                        f"<div style='text-align:center;font-size:1.8rem;font-weight:700'>"
                        f"{away_badge}<span class='{away_span_class}'>{int(live['away_score'])}</span>"
                        f" - "
                        f"<span class='{home_span_class}'>{int(live['home_score'])}</span>{home_badge}</div>",
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
                outs = live.get("outs") if status == "In Progress" else None
                st.markdown(
                    f"<div style='display:flex;justify-content:center'>"
                    f"{style.game_state_html(status_line, live.get('bases', {}), outs)}</div>",
                    unsafe_allow_html=True,
                )
                if row.get("game_time") and not started:
                    st.markdown(
                        f"<div class='game-time-local' data-utc='{row['game_time']}' "
                        f"style='text-align:center;color:#9AA3B5;font-size:0.85rem'>{row['game_time']}</div>",
                        unsafe_allow_html=True,
                    )
                if row.get("venue"):
                    st.caption(f"<div style='text-align:center'>{row['venue']}</div>", unsafe_allow_html=True)

                if started:
                    if st.button("Game Center", key=f"btn_{row['game_pk']}", use_container_width=True):
                        st.session_state["selected_game_pk"] = row["game_pk"]
                        st.session_state["selected_game_date"] = row["date"]
                        st.session_state["selected_game_away_abbr"] = row["away_abbr"]
                        st.session_state["selected_game_home_abbr"] = row["home_abbr"]
                        st.session_state["selected_game_away_team"] = row["away_team"]
                        st.session_state["selected_game_home_team"] = row["home_team"]
                        st.switch_page("pages/_Game_Detail.py")

            with hcol:
                logo_html = (
                    f"<img src='{home_logo}' style='height:32px;width:32px;object-fit:contain;"
                    f"vertical-align:middle;margin-right:6px'>" if home_logo else ""
                )
                st.markdown(
                    f"<div style='display:flex;align-items:center'>{logo_html}"
                    f"<span style='background-color:{home_color}66;color:#FAFAFA;padding:3px 10px;"
                    f"border-radius:8px;font-weight:700'>{row['home_abbr']}</span> &nbsp;"
                    f"<span style='font-weight:700;font-size:1.1rem'>{row['home_team']}</span></div>",
                    unsafe_allow_html=True,
                )
                era = pitcher_era(row.get("home_pitcher_mlbID"))
                sp_line = row["home_pitcher_name"] or "TBD"
                if era is not None and pd.notna(era):
                    sp_line += f" ({era:.2f} ERA)"
                st.caption(f"SP: {sp_line}")
                st.caption(f"Record: {row['home_wins']}-{row['home_losses']}")
                home_form = db.team_recent_form(row["home_abbr"], mtime)
                if home_form:
                    st.caption(f"Last 10: {home_form['last10']} · {home_form['streak']}")
                if pred:
                    st.markdown(
                        f"<div style='font-size:1.3rem;font-weight:700'>{pred['home_odds']}</div>"
                        f"<div style='color:#9AA3B5'>{pred['home_prob']*100:.0f}% win probability</div>",
                        unsafe_allow_html=True,
                    )

            if not pred:
                st.caption("Not enough season data yet to generate a prediction for this game.")

            current_pick = my_picks.get(row["game_pk"])
            if started:
                st.caption(f"Your pick: {current_pick}" if current_pick else "Picks locked — game has started.")
            else:
                st.caption("Tap a team to pick the winner")
                pcol1, pcol2 = st.columns(2)
                for col, abbr in ((pcol1, row["away_abbr"]), (pcol2, row["home_abbr"])):
                    with col:
                        is_picked = current_pick == abbr
                        pick_key = f"pick_{row['game_pk']}_{abbr}"
                        # Streamlit exposes each widget's `key` as a
                        # `st-key-{key}` class on its wrapper div — the only
                        # way to reach a SPECIFIC button's own <button> with
                        # CSS, since type="primary"/"secondary" only offers
                        # two canned looks, not an arbitrary team color.
                        st.markdown(
                            f"<style>.st-key-{pick_key} button {{"
                            "padding:2px 0 !important;min-height:1.8rem !important;font-size:0.8rem !important;"
                            + (
                                f"background-color:{team_color(abbr)} !important;"
                                "border-color:transparent !important;color:#FAFAFA !important;"
                                if is_picked else ""
                            )
                            + "}}</style>",
                            unsafe_allow_html=True,
                        )
                        if st.button(abbr, key=pick_key, use_container_width=True):
                            predictions.add_pick(row["game_pk"], row["date"], abbr, row["away_abbr"], row["home_abbr"])
                            # A full rerun, not scope="fragment" — st.rerun()
                            # aborts the script immediately, so a save() call
                            # placed right before it (in-fragment) never gives
                            # its injected iframe time to actually run the
                            # localStorage write. A full rerun instead lets
                            # the page's own predictions.save() backstop (see
                            # bottom of this file) complete on the next pass,
                            # with nothing immediately re-aborting it.
                            st.rerun()

render_games()

st.divider()
style.colored_header("Your Accuracy", "chart")
overall, by_day = predictions.compute_accuracy(predictions.get_picks(), db.load_schedule_for_date)
if overall["total"] == 0:
    st.caption("No resolved picks yet — pick some winners above, then check back once those games finish.")
else:
    acol1, acol2, acol3 = st.columns(3)
    acol1.metric("Correct", overall["correct"])
    acol2.metric("Total Picks", overall["total"])
    acol3.metric("Accuracy", f"{overall['pct']}%")
    st.dataframe(by_day, hide_index=True, use_container_width=True)

# Persists any pick made above into localStorage — unconditional/idempotent
# per render, same pattern as following.save(), so it doesn't need to be
# wired to the specific button that changed something. This is the ONLY
# place that actually calls save(): a pick button triggers a full st.rerun()
# (see render_games()) specifically so this line gets a clean, unraced
# chance to run afterward.
predictions.save()

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
