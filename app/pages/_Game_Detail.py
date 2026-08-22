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
mtime = db.db_mtime()


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

        current_pitchers = db.load_current_pitchers(game_pk)
        if current_pitchers:
            style.colored_header("On the Mound", "pitching")
            st.caption("Each team's pitcher currently in the game — tonight's line and season numbers.")
            p_cols = st.columns(len(current_pitchers))
            for col, p in zip(p_cols, current_pitchers):
                abbr = away_abbr if p["side"] == "away" else home_abbr
                norm = teams.normalize_mlb_abbr(abbr)
                p_color = teams.color_for_abbr(norm)
                with col:
                    with st.container(border=True):
                        mound_tag = (
                            "<span style='background-color:#D32F2F33;color:#FF8A80;padding:2px 8px;"
                            "border-radius:6px;font-weight:700;font-size:0.7rem;margin-left:6px'>"
                            "ON THE MOUND</span>" if p["on_mound"] else ""
                        )
                        st.markdown(
                            f"<div style='display:flex;align-items:center;gap:12px'>"
                            f"<img src='{style.headshot_url(p['mlbID'], width=120)}' "
                            f"style='width:56px;height:56px;border-radius:50%;object-fit:cover;"
                            f"object-position:center 25%'>"
                            f"<div><span style='background-color:{p_color}66;color:#FAFAFA;padding:2px 8px;"
                            f"border-radius:6px;font-weight:700;font-size:0.8rem'>{norm}</span>{mound_tag}"
                            f"<div style='font-weight:700;font-size:1.05rem;margin-top:2px'>"
                            f"<a href='{style.player_link(p['mlbID'], season)}' target='_self' "
                            f"style='color:inherit;text-decoration:none'>{p['name']}</a></div></div></div>",
                            unsafe_allow_html=True,
                        )
                        g = p["game"]
                        if g.get("ip") is not None:
                            st.caption(
                                f"Tonight: {g['ip']} IP · {g.get('h', 0)} H · {g.get('er', 0)} ER · "
                                f"{g.get('so', 0)} K · {g.get('bb', 0)} BB · {g.get('pitches', 0)} pitches"
                            )
                        s = p["season"]
                        if s.get("era"):
                            st.caption(
                                f"Season: {s['era']} ERA · {s.get('whip', '—')} WHIP · "
                                f"{s.get('so', 0)} K in {s.get('ip', '—')} IP"
                            )

        due_up = db.load_due_up(game_pk)
        if due_up:
            style.colored_header("Due Up", "batting")
            hand = due_up.get("pitcher_hand")
            hand_label = {"R": "RHP", "L": "LHP"}.get(hand, "")
            facing_bits = f"Facing {due_up['pitcher_name']}" + (f" ({hand_label})" if hand_label else "")
            # The pitcher's two most-used pitches, so you know what the
            # due-up hitters are about to see.
            p_arsenal = db.get_player_pitch_arsenal(due_up["pitcher_id"], season, mtime)
            if not p_arsenal.empty:
                top2 = p_arsenal.head(2)
                pitches_bits = ", ".join(
                    f"{r['usage_pct']:.0f}% {r['pitch_name']}"
                    + (f" ({r['velocity']:.0f} mph)" if pd.notna(r.get("velocity")) else "")
                    for _, r in top2.iterrows()
                )
                facing_bits += f" — {pitches_bits}"
            st.caption(facing_bits)

            season_batting = db.load_batting(season, mtime)
            split_key = {"R": "vs RHP", "L": "vs LHP"}.get(hand)
            cols = st.columns(len(due_up["due"]))
            for col, batter in zip(cols, due_up["due"]):
                with col:
                    with st.container(border=True):
                        st.markdown(
                            f"<div style='display:flex;align-items:center;gap:10px'>"
                            f"<img src='{style.headshot_url(batter['mlbID'], width=100)}' "
                            f"style='width:44px;height:44px;border-radius:50%;object-fit:cover;"
                            f"object-position:center 25%'>"
                            f"<div><div style='color:#9AA3B5;font-size:0.75rem;font-weight:700'>"
                            f"{batter['label'].upper()}</div>"
                            f"<div style='font-weight:700'><a href='{style.player_link(batter['mlbID'], season)}' "
                            f"target='_self' style='color:inherit;text-decoration:none;"
                            f"'>{batter['name']}</a></div></div></div>",
                            unsafe_allow_html=True,
                        )
                        mine = season_batting[season_batting["mlbID"] == batter["mlbID"]]
                        if not mine.empty:
                            row = mine.iloc[0]
                            st.caption(
                                f"Season: {row['BA']:.3f} / {row['OPS']:.3f} OPS · {int(row['HR'])} HR"
                            )
                        if split_key:
                            splits = db.load_split_stats(batter["mlbID"], season, "hitting")
                            s = splits.get(split_key) or {}
                            if s.get("avg") and s.get("ops"):
                                st.caption(f"{split_key}: {s['avg']} AVG / {s['ops']} OPS")

    wp_df = db.load_win_probability(game_pk)
    if not wp_df.empty:
        style.colored_header("Win Probability", "batting")
        # Live tension gauge from OUR trained model — how much the very
        # next plate appearance could swing the game vs. an average moment.
        if status == "In Progress":
            lev = db.current_leverage(game_pk)
            if lev and lev["ratio"] >= 1.5:
                st.markdown(
                    f"<div style='background-color:#D32F2F22;border-left:4px solid #D32F2F;"
                    f"padding:8px 14px;border-radius:6px;margin:4px 0'>"
                    f"<b>High-leverage moment</b> — this at-bat can swing the game "
                    f"{lev['ratio']:.1f}× more than an average one "
                    f"<span style='color:#9AA3B5'>(our win probability model)</span></div>",
                    unsafe_allow_html=True,
                )
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

        # Live batted-ball charts — no Final-only gate: this feeds from
        # MLB's live play-by-play feed (see db.load_game_batted_balls),
        # not Baseball Savant's post-game export that forced the old
        # version of this section to wait for Final.
        style.colored_header("Batted Balls", "batting")
        batted_balls = db.load_game_batted_balls(game_pk)
        if batted_balls.empty:
            st.caption("No balls in play yet.")
        else:
            team_filter = st.radio(
                "Team filter", ["Both Teams", away_abbr, home_abbr],
                horizontal=True, key="game_center_spray_team_filter",
            )
            filtered = (
                batted_balls if team_filter == "Both Teams"
                else batted_balls[batted_balls["team_abbr"] == team_filter]
            )
            view_mode = st.radio(
                "View", ["Top-Down", "3D Trajectory"],
                horizontal=True, key="game_center_spray_view_mode",
            )
            st.caption(
                "Live from MLB's tracking feed — every ball put in play so far, updating as the game goes. "
                "Hover a point for the batter and contact quality."
            )
            field_lines = style.field_wall_lines(
                db.team_stadium_outline(teams.normalize_mlb_abbr(home_abbr))
            )
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
