import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Game Center | Diamond Metrics", layout="wide")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

# Set by the "Game Center" button on Today's Games (st.switch_page) — no
# query-param deep link support (unlike _Player.py's ?mlbid=), since a game
# detail link would go stale the instant the game ends and there's no
# followed-game/bookmark use case pulling for one yet.
if "selected_game_pk" not in st.session_state:
    st.title("Game Center")
    st.info("Pick a game from Today's Games to see its live tracker, win probability, and box score here.")
    if st.button("Go to Today's Games"):
        st.switch_page("pages/8_Todays_Games.py")
    st.stop()

game_pk = st.session_state["selected_game_pk"]
game_date = st.session_state["selected_game_date"]
away_abbr = st.session_state["selected_game_away_abbr"]
home_abbr = st.session_state["selected_game_home_abbr"]
away_team = st.session_state["selected_game_away_team"]
home_team = st.session_state["selected_game_home_team"]

if st.button("← Back to Today's Games"):
    st.switch_page("pages/8_Todays_Games.py")

season = db.get_seasons("batting")[0]


def team_color(abbr):
    return teams.color_for_abbr(teams.normalize_mlb_abbr(abbr))


def team_logo(abbr):
    team_id = teams.team_id_for_abbr(teams.normalize_mlb_abbr(abbr))
    return style.team_logo_for_season(teams.normalize_mlb_abbr(abbr), team_id, season) if team_id else None


away_color, home_color = team_color(away_abbr), team_color(home_abbr)
away_logo, home_logo = team_logo(away_abbr), team_logo(home_abbr)


# A fragment (not the whole page) so the live tracker/win-probability/score
# can auto-refresh on a timer without losing scroll position — same reason
# Today's Games' render_games() is a fragment. 10s rather than that page's
# 20s since this IS the dedicated live view; the whole point of it is
# catching pitches as they happen, not just the score ticking over.
@st.fragment(run_every="10s")
def render_game_center():
    db.load_live_scores.clear()
    live = db.load_live_scores(game_date).get(game_pk, {})
    status = live.get("status") or "Scheduled"

    logo_col1, mid_col, logo_col2 = st.columns([3, 2, 3])
    with logo_col1:
        logo_html = (
            f"<img src='{away_logo}' style='height:48px;width:48px;object-fit:contain;"
            f"vertical-align:middle;margin-right:10px'>" if away_logo else ""
        )
        st.markdown(
            f"<div style='display:flex;align-items:center'>{logo_html}"
            f"<span style='background-color:{away_color}66;color:#FAFAFA;padding:4px 12px;"
            f"border-radius:8px;font-weight:700;font-size:1.1rem'>{away_abbr}</span>&nbsp;"
            f"<span style='font-weight:700;font-size:1.3rem'>{away_team}</span></div>",
            unsafe_allow_html=True,
        )
    with logo_col2:
        logo_html = (
            f"<img src='{home_logo}' style='height:48px;width:48px;object-fit:contain;"
            f"vertical-align:middle;margin-right:10px'>" if home_logo else ""
        )
        st.markdown(
            f"<div style='display:flex;align-items:center;justify-content:flex-end'>"
            f"<span style='font-weight:700;font-size:1.3rem'>{home_team}</span>&nbsp;"
            f"<span style='background-color:{home_color}66;color:#FAFAFA;padding:4px 12px;"
            f"border-radius:8px;font-weight:700;font-size:1.1rem'>{home_abbr}</span>{logo_html}</div>",
            unsafe_allow_html=True,
        )
    with mid_col:
        if live.get("away_score") is not None and live.get("home_score") is not None:
            st.markdown(
                f"<div style='text-align:center;font-size:2.4rem;font-weight:700'>"
                f"{int(live['away_score'])} - {int(live['home_score'])}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown("<div style='text-align:center;color:#9AA3B5;padding-top:12px'>@</div>", unsafe_allow_html=True)
        status_line = live.get("inning") if status == "In Progress" and live.get("inning") else status
        outs = live.get("outs") if status == "In Progress" else None
        st.markdown(style.game_state_html(status_line, live.get("bases", {}), outs, scale=2.2), unsafe_allow_html=True)

    if status == "In Progress":
        style.colored_header("Live Pitch Tracker", "pitching")
        tracker = db.load_live_pitch_tracker(game_pk)
        if tracker.get("pitches"):
            count = tracker.get("count", {})
            st.caption(
                f"{tracker.get('pitcher') or 'Pitcher'} to {tracker.get('batter') or 'batter'} — "
                f"{count.get('balls', 0)}-{count.get('strikes', 0)}, {count.get('outs', 0)} out(s)"
            )
            st.plotly_chart(style.strike_zone_chart(tracker["pitches"]), use_container_width=True, key="game_center_sz")
        else:
            st.caption("Waiting on the next pitch...")

    wp_df = db.load_win_probability(game_pk)
    if not wp_df.empty:
        style.colored_header("Win Probability", "batting")
        st.plotly_chart(
            style.win_probability_chart(wp_df, away_abbr, home_abbr, away_color, home_color),
            use_container_width=True, key="game_center_wp",
        )
        if len(wp_df) > 1:
            swings = wp_df["home_win_pct"].diff().abs()
            top_idx = swings.idxmax()
            swing_pct = swings.loc[top_idx] if pd.notna(swings.loc[top_idx]) else 0
            play = wp_df.loc[top_idx]
            if swing_pct > 0 and isinstance(play.get("description"), str):
                st.markdown(
                    f"<div style='background-color:#1B243866;border-left:4px solid #3B82F6;padding:8px 14px;"
                    f"border-radius:6px;margin:4px 0'><span style='color:#9AA3B5;font-size:0.85rem'>"
                    f"Play of the Game — {swing_pct:.0f}% win-probability swing</span>"
                    f"<div style='color:#DCE1EA'>{play['description']}</div></div>",
                    unsafe_allow_html=True,
                )

    if status not in ("Scheduled", "Pre-Game", "Warmup", "Delayed Start", "Postponed"):
        style.colored_header("Box Score", "fielding")
        linescore = db.load_linescore(game_pk)
        if not linescore or "innings" not in linescore:
            st.caption("Box score not available yet.")
        else:
            st.markdown(
                style.box_score_table(linescore, away_abbr, home_abbr, away_color, home_color),
                unsafe_allow_html=True,
            )

        player_box = db.load_boxscore_players(game_pk)
        if player_box:
            pbcol1, pbcol2 = st.columns(2)
            for col, side, abbr in ((pbcol1, "away", away_abbr), (pbcol2, "home", home_abbr)):
                with col:
                    batters = pd.DataFrame(player_box[side]["batters"])
                    if not batters.empty:
                        st.caption(f"{abbr} Batting")
                        st.dataframe(
                            batters[["Name", "Pos", "AB", "R", "H", "HR", "RBI", "BB", "SO"]],
                            hide_index=True, use_container_width=True,
                        )
                    pitchers = pd.DataFrame(player_box[side]["pitchers"])
                    if not pitchers.empty:
                        st.caption(f"{abbr} Pitching")
                        st.dataframe(pitchers, hide_index=True, use_container_width=True)

        # load_game_replay hits MLB's own live-feed API (same source as the
        # Live Pitch Tracker above) — it updates in real time as the game
        # progresses, unlike load_game_batted_balls (Baseball Savant's
        # per-game CSV export), which is confirmed empty until the game is
        # final. So fastest pitch can show live; hardest hit ball can't.
        replay_for_highs = db.load_game_replay(game_pk)
        fastest_pitch = max((p["speed"] for p in replay_for_highs if p.get("speed")), default=None)
        hardest_hit = None
        if status in db.FINAL_STATUSES:
            batted_for_highs = db.load_game_batted_balls(game_pk)
            hardest_hit = batted_for_highs["launch_speed"].max() if not batted_for_highs.empty else None
        if pd.notna(hardest_hit) or fastest_pitch:
            style.colored_header("Game Highs", "batting")
            hi_col1, hi_col2 = st.columns(2)
            with hi_col1:
                if pd.notna(hardest_hit):
                    hardest_label = f"{hardest_hit:.1f} mph"
                elif status not in db.FINAL_STATUSES:
                    hardest_label = "Final only"
                else:
                    hardest_label = "Processing…"
                st.metric("Hardest Hit Ball", hardest_label)
            with hi_col2:
                st.metric("Fastest Pitch", f"{fastest_pitch:.1f} mph" if fastest_pitch else "—")

        style.colored_header("Spray Chart", "batting")
        if status not in db.FINAL_STATUSES:
            # Confirmed directly against Baseball Savant's own CSV export
            # (the source behind pybaseball's statcast_single_game): for an
            # in-progress game it returns the header row and zero data rows
            # — not a lag, not partial data, nothing at all until the game
            # is over. So there's no live version of this chart to show.
            st.caption("Spray chart available once the game is final.")
        else:
            batted_balls = db.load_game_batted_balls(game_pk)
            if batted_balls.empty:
                st.caption(
                    "Baseball Savant hasn't finished processing this game's batted-ball data yet — "
                    "check back in a bit."
                )
            else:
                team_filter = st.radio(
                    "Team filter", ["Both Teams", away_abbr, home_abbr],
                    horizontal=True, key="game_center_spray_team_filter",
                )
                if team_filter == "Both Teams":
                    filtered = batted_balls
                else:
                    filtered = batted_balls[batted_balls["team_abbr"] == team_filter]

                view_mode = st.radio(
                    "View", ["Top-Down", "3D Trajectory"],
                    horizontal=True, key="game_center_spray_view_mode",
                )
                field_lines = style.field_wall_lines(db.team_stadium_outline(home_abbr))
                if filtered.empty:
                    st.caption("No batted balls for this selection.")
                elif view_mode == "3D Trajectory":
                    st.plotly_chart(
                        style.trajectory_3d_chart(filtered, field_lines, db.SPRAY_EVENT_COLORS),
                        use_container_width=True, key="game_center_spray_3d",
                    )
                else:
                    st.plotly_chart(
                        style.spray_chart_2d(filtered, field_lines, db.SPRAY_EVENT_COLORS),
                        width=800, height=490, key="game_center_spray_2d",
                    )

render_game_center()
