import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import following
import style
import teams

st.set_page_config(page_title="Following | Diamond Metrics", layout="wide")
st.title("Following")
st.caption(
    "Follow teams and players to get a personalized feed: today's games for your teams, "
    "yesterday's performances for your players. Saved in this browser only (no account) — "
    "it'll be here next time you visit on this device/browser, but won't follow you to another one."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
season = db.get_seasons("batting")[0]

# Normally seeded by following.bootstrap() in main.py, but Streamlit's legacy
# pages/-folder auto-discovery can route a direct URL hit straight to this
# page's script (bypassing main.py entirely) — so bootstrap defensively here too.
following.bootstrap()
followed_teams = st.session_state["followed_teams"]  # [{"abbr", "nickname"}, ...]
followed_players = st.session_state["followed_players"]  # [{"mlbID", "name"}, ...]

with st.expander("Manage who you follow", expanded=not (followed_teams or followed_players)):
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Follow a team**")
        team_options = teams.all_teams()
        followed_abbrs = {t["abbr"] for t in followed_teams}
        labels = [f"{abbr} — {nickname}" for abbr, nickname in team_options if abbr not in followed_abbrs]
        if labels:
            choice = st.selectbox("Team", labels, label_visibility="collapsed")
            if st.button("Follow team"):
                abbr, nickname = choice.split(" — ")
                followed_teams.append({"abbr": abbr, "nickname": nickname})
        else:
            st.caption("You're following every team.")

        if followed_teams:
            st.markdown("**Following**")
            for t in list(followed_teams):
                c1, c2 = st.columns([4, 1])
                c1.markdown(
                    f"<span style='background-color:{teams.color_for_abbr(t['abbr'])}66;color:#FAFAFA;"
                    f"padding:3px 10px;border-radius:8px;font-weight:700'>{t['abbr']}</span> {t['nickname']}",
                    unsafe_allow_html=True,
                )
                if c2.button("Unfollow", key=f"unfollow_team_{t['abbr']}"):
                    followed_teams.remove(t)

    with col2:
        st.markdown("**Follow a player**")
        query = st.text_input("Search players", label_visibility="collapsed", placeholder="e.g. Ohtani, Judge")
        followed_ids = {p["mlbID"] for p in followed_players}
        if query.strip():
            matches = db.search_players(query, season, mtime)
            matches = matches[~matches["mlbID"].isin(followed_ids)]
            for _, row in matches.head(8).iterrows():
                c1, c2 = st.columns([4, 1])
                c1.markdown(f"{row['Name']} ({row['Tm']}) — {row['roles']}")
                if c2.button("Follow", key=f"follow_player_{row['mlbID']}"):
                    followed_players.append({"mlbID": int(row["mlbID"]), "name": row["Name"]})
            if matches.empty:
                st.caption("No matches.")

        if followed_players:
            st.markdown("**Following**")
            for p in list(followed_players):
                c1, c2 = st.columns([4, 1])
                c1.markdown(p["name"])
                if c2.button("Unfollow", key=f"unfollow_player_{p['mlbID']}"):
                    followed_players.remove(p)

# Persists whatever's currently in session_state to this browser's localStorage
# — cheap and safe to call unconditionally on every render (see following.py).
following.save()

if not followed_teams and not followed_players:
    st.info("You're not following any teams or players yet — use \"Manage who you follow\" above to get started.")
    st.stop()

# --- Today's Games for followed teams ---------------------------------------
style.colored_header("Today's Games", "batting")
if not followed_teams:
    st.caption("Follow a team to see their games here.")
else:
    games = db.load_todays_games(mtime)
    followed_abbrs = {t["abbr"] for t in followed_teams}
    my_games = games[
        games["away_abbr"].apply(teams.normalize_mlb_abbr).isin(followed_abbrs)
        | games["home_abbr"].apply(teams.normalize_mlb_abbr).isin(followed_abbrs)
    ] if not games.empty else games

    if my_games.empty:
        st.caption("None of your followed teams play today.")
    else:
        pitching = teams.add_team_abbr(db.load_pitching(season, mtime))
        batting = teams.add_team_abbr(db.load_batting(season, mtime))
        live_scores = db.load_live_scores(my_games.iloc[0]["date"])
        pitcher_ids = tuple(sorted({
            int(v) for col in ("away_pitcher_mlbID", "home_pitcher_mlbID")
            for v in my_games[col].dropna().tolist()
        }))
        pitcher_hands = db.load_pitcher_handedness(pitcher_ids)

        def pitcher_era(mlbID):
            if mlbID is None or pd.isna(mlbID):
                return None
            match = pitching[pitching["mlbID"] == int(mlbID)]
            return None if match.empty else match.iloc[0]["ERA"]

        for _, row in my_games.iterrows():
            pred = db.predict_game(row, pitching, batting, pitcher_hands)
            away_color = teams.color_for_abbr(teams.normalize_mlb_abbr(row["away_abbr"]))
            home_color = teams.color_for_abbr(teams.normalize_mlb_abbr(row["home_abbr"]))
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
                    if pred:
                        st.markdown(
                            f"<div style='font-size:1.2rem;font-weight:700'>{pred['away_odds']}</div>"
                            f"<div style='color:#9AA3B5'>{pred['away_prob']*100:.0f}% win probability</div>",
                            unsafe_allow_html=True,
                        )
                with mid:
                    if started and live.get("away_score") is not None and live.get("home_score") is not None:
                        st.markdown(
                            f"<div style='text-align:center;font-size:1.6rem;font-weight:700'>"
                            f"{int(live['away_score'])} - {int(live['home_score'])}</div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown("<div style='text-align:center;color:#9AA3B5;padding-top:8px'>@</div>", unsafe_allow_html=True)
                    status_line = live.get("inning") if status == "In Progress" and live.get("inning") else status
                    st.caption(f"<div style='text-align:center'>{status_line}</div>", unsafe_allow_html=True)
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
                    if pred:
                        st.markdown(
                            f"<div style='font-size:1.2rem;font-weight:700'>{pred['home_odds']}</div>"
                            f"<div style='color:#9AA3B5'>{pred['home_prob']*100:.0f}% win probability</div>",
                            unsafe_allow_html=True,
                        )

# --- Yesterday's performances for followed players --------------------------
style.colored_header("Yesterday's Performances", "pitching")
if not followed_players:
    st.caption("Follow a player to see their performances here.")
else:
    followed_ids = {p["mlbID"] for p in followed_players}
    recent_batting = db.load_recent_batting(season, mtime)
    recent_pitching = db.load_recent_pitching(season, mtime)
    # recent_pitching.mlbID is stored as text in SQLite (unlike every other
    # table's mlbID) — cast before comparing against followed_ids (ints).
    if not recent_pitching.empty:
        recent_pitching = recent_pitching.assign(mlbID=recent_pitching["mlbID"].astype(int))

    day_batting = recent_batting[(recent_batting["period"] == "day") & recent_batting["mlbID"].isin(followed_ids)] if not recent_batting.empty else recent_batting
    day_pitching = recent_pitching[(recent_pitching["period"] == "day") & recent_pitching["mlbID"].isin(followed_ids)] if not recent_pitching.empty else recent_pitching

    if day_batting.empty and day_pitching.empty:
        st.caption("None of your followed players played yesterday.")
    else:
        for _, row in day_batting.iterrows():
            with st.container(border=True):
                abbr, _, color = teams.team_meta_from_city(row["Tm"], row.get("Lev"))
                tb = int(row["H"] + row["2B"] + 2 * row["3B"] + 3 * row["HR"])
                text = f"{tb} TB, {int(row['H'])} H, {int(row['HR'])} HR, {int(row['RBI'])} RBI"
                style.milestone_card(row["mlbID"], row["Name"], abbr, color, text)
        for _, row in day_pitching.iterrows():
            with st.container(border=True):
                abbr, _, color = teams.team_meta_from_city(row["Tm"], row.get("Lev"))
                if pd.notna(row.get("GSc")):
                    text = f"Game Score {int(row['GSc'])}, {row['ERA']:.2f} ERA ({row['IP']:.1f} IP)"
                else:
                    text = f"{row['ERA']:.2f} ERA, {int(row['SO'])} SO ({row['IP']:.1f} IP)"
                style.milestone_card(row["mlbID"], row["Name"], abbr, color, text)
