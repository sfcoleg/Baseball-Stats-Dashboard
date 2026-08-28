"""NHL Following — the teams and players you follow, and how they did.

Persistence rides on the same browser-localStorage bridge as the MLB
Following page (see app/following.py): one storage key, one payload, four
lists. The NHL lists are separate from the MLB ones because a team
abbreviation like "CGY" and a player id mean different things in each sport,
but they save and load together."""
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import following
import style
from nhl import db as ndb
from nhl import teams as nteams

st.set_page_config(page_title="NHL Following | Diamond Metrics", layout="wide")
st.title("Following")

mtime = ndb.nhl_db_mtime()
seasons = ndb.skater_seasons(mtime)
if not seasons:
    st.info("No NHL data yet — run ingest/nhl_refresh.py to backfill.")
    st.stop()
season = seasons[0]

followed_teams = st.session_state.setdefault("followed_nhl_teams", [])
followed_players = st.session_state.setdefault("followed_nhl_players", [])

with st.expander("Manage who you follow", expanded=not (followed_teams or followed_players)):
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Follow a team**")
        followed_abbrs = {t["abbr"] for t in followed_teams}
        labels = [
            f"{abbr} — {nickname}" for abbr, nickname in nteams.all_teams()
            if abbr not in followed_abbrs
        ]
        if labels:
            choice = st.selectbox("Team", labels, label_visibility="collapsed", key="nhl_follow_team_pick")
            if st.button("Follow team", key="nhl_follow_team_btn"):
                abbr, nickname = choice.split(" — ")
                followed_teams.append({"abbr": abbr, "nickname": nickname})
        else:
            st.caption("You're following every team.")

        if followed_teams:
            st.markdown("**Following**")
            for t in list(followed_teams):
                c1, c2 = st.columns([4, 1])
                c1.markdown(
                    f"<span style='background-color:{nteams.color_for_abbr(t['abbr'])}66;"
                    f"color:var(--dm-text);padding:3px 10px;border-radius:8px;font-weight:700'>"
                    f"{t['abbr']}</span> {t['nickname']}",
                    unsafe_allow_html=True,
                )
                if c2.button("Unfollow", key=f"nhl_unfollow_team_{t['abbr']}"):
                    followed_teams.remove(t)
                    st.rerun()

    with col2:
        st.markdown("**Follow a player**")
        query = st.text_input(
            "Search players", label_visibility="collapsed",
            placeholder="e.g. McDavid, Hellebuyck", key="nhl_follow_search",
        )
        followed_ids = {p["playerId"] for p in followed_players}
        if query.strip():
            matches = ndb.search_players(query, season, mtime)
            if not matches.empty:
                matches = matches[~matches["playerId"].isin(followed_ids)]
            for _, row in matches.head(8).iterrows():
                c1, c2 = st.columns([4, 1])
                c1.markdown(f"{row['Name']} ({nteams._primary(row['Tm'])}) — {row['role']}")
                if c2.button("Follow", key=f"nhl_follow_player_{row['playerId']}"):
                    followed_players.append({
                        "playerId": int(row["playerId"]), "name": row["Name"],
                        "role": row["role"],
                    })
                    st.rerun()
            if matches.empty:
                st.caption("No matches.")

        if followed_players:
            st.markdown("**Following**")
            for p in list(followed_players):
                c1, c2 = st.columns([4, 1])
                c1.markdown(p["name"])
                if c2.button("Unfollow", key=f"nhl_unfollow_player_{p['playerId']}"):
                    followed_players.remove(p)
                    st.rerun()

# Cheap and idempotent — see app/following.py.
following.save()

if not followed_teams and not followed_players:
    st.info('You\'re not following any teams or players yet — use "Manage who you follow" above to get started.')
    st.stop()

# --- Followed teams --------------------------------------------------------
if followed_teams:
    style.colored_header("Your Teams", "batting")
    standings = ndb.load_standings()
    for t in followed_teams:
        with st.container(border=True):
            row = standings[standings["teamAbbrev"] == t["abbr"]] if not standings.empty else pd.DataFrame()
            header = (
                f"<span style='background-color:{nteams.color_for_abbr(t['abbr'])}66;color:var(--dm-text);"
                f"padding:3px 10px;border-radius:8px;font-weight:700'>{t['abbr']}</span> "
                f"<span style='font-weight:700'>{t['nickname']}</span>"
            )
            if not row.empty:
                r = row.iloc[0]
                header += (
                    f" <span style='color:var(--dm-dim)'>· {int(r['wins'])}-{int(r['losses'])}-"
                    f"{int(r['otLosses'])}, {int(r['points'])} pts · {r['divisionName']}</span>"
                )
            st.markdown(header, unsafe_allow_html=True)

            # Raw NHL API game objects — same shape the Team page reads.
            schedule = ndb.load_club_schedule(t["abbr"]) or []

            def _side(game, abbr=t["abbr"]):
                at_home = game["homeTeam"]["abbrev"] == abbr
                opponent = game["awayTeam"]["abbrev"] if at_home else game["homeTeam"]["abbrev"]
                return at_home, opponent

            played = [g for g in schedule if g.get("gameState") in ("OFF", "FINAL")]
            upcoming = [g for g in schedule if g.get("gameState") not in ("OFF", "FINAL")]
            if upcoming:
                st.caption("Next up: " + " · ".join(
                    f"{'vs' if at_home else '@'} {opponent} {g.get('gameDate', '')}"
                    for g in upcoming[:3]
                    for at_home, opponent in [_side(g)]
                ))
            elif played:
                parts = []
                for g in played[-3:]:
                    at_home, opponent = _side(g)
                    us = g["homeTeam"].get("score", 0) if at_home else g["awayTeam"].get("score", 0)
                    them = g["awayTeam"].get("score", 0) if at_home else g["homeTeam"].get("score", 0)
                    parts.append(f"{'vs' if at_home else '@'} {opponent} {'W' if us > them else 'L'} {us}-{them}")
                st.caption("Last games: " + " · ".join(parts))
            else:
                st.caption("No games scheduled — the season is over.")

# --- Followed players ------------------------------------------------------
if followed_players:
    style.colored_header("Your Players", "pitching")
    skaters = ndb.load_skaters(season, mtime)
    goalies = ndb.load_goalies(season, mtime)
    rows = []
    for p in followed_players:
        if p.get("role") == "Goalie":
            match = goalies[goalies["playerId"] == p["playerId"]] if not goalies.empty else pd.DataFrame()
            if match.empty:
                continue
            g = match.iloc[0]
            rows.append({
                "Name": p["name"], "Tm": nteams._primary(g["teamAbbrevs"]), "Pos": "G",
                "GP": g["gamesPlayed"], "Line": f"{int(g['wins'])}-{int(g['losses'])}-{int(g['otLosses'])}",
                "Detail": f"{g['savePct']:.1f} SV%, {g['goalsAgainstAverage']:.2f} GAA",
            })
        else:
            match = skaters[skaters["playerId"] == p["playerId"]] if not skaters.empty else pd.DataFrame()
            if match.empty:
                continue
            s = match.iloc[0]
            rows.append({
                "Name": p["name"], "Tm": nteams._primary(s["teamAbbrevs"]),
                "Pos": s["positionCode"], "GP": s["gamesPlayed"],
                "Line": f"{int(s['goals'])}G {int(s['assists'])}A {int(s['points'])}P",
                "Detail": f"{s['pointsPerGame']:.2f} P/GP",
            })
    if rows:
        st.caption(f"{ndb.season_label(season)} season totals.")
        st.dataframe(
            style.style_stats_table(
                pd.DataFrame(rows), team_col="Tm", team_color_fn=nteams.color_for_abbr,
            ),
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("No season stats on file for the players you follow.")
