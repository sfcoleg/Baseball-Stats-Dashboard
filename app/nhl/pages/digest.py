"""NHL Daily Digest — yesterday in one page: every final score, the
milestones (hat tricks, shutouts, season marks crossed), the top skater
and goalie lines, and who's on a streak. The hockey analog of the MLB
Daily Digest, built from the schedule API plus the nightly per-game log
(ingest/nhl_daily_log.py).

Registered in main.py but kept out of the sidebar until the season
starts (SHOW_NHL_DIGEST) — in the offseason every section would be empty.
Reachable directly at /nhl-digest for previewing."""
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nhl import db as ndb
from nhl import style as nstyle
from nhl import teams as nteams

st.set_page_config(page_title="NHL Daily Digest | Diamond Metrics", layout="wide")
st.title("Daily Digest")

mtime = ndb.nhl_db_mtime()
seasons = ndb.skater_seasons(mtime)
if not seasons:
    st.info("No NHL data yet — run ingest/nhl_refresh.py to backfill.")
    st.stop()
season = seasons[0]

today = ndb.today_pacific()
# ?date=YYYY-MM-DD lets any past day be revisited (and the offseason
# previewed); default is yesterday, the last complete slate.
qp = st.query_params.get("date")
try:
    day = pd.Timestamp(qp).date() if qp else today - timedelta(days=1)
except (ValueError, TypeError):
    day = today - timedelta(days=1)
day_str = day.isoformat()
st.caption(f"Everything that happened on {day.strftime('%A, %B %-d, %Y')}.")


def _headshot(player_id, team_abbr) -> str:
    return f"https://assets.nhle.com/mugs/nhl/{season}{season + 1}/{team_abbr}/{int(player_id)}.png"


def _player_card(label, name, player_id, team_abbr, stat_line):
    color = nteams.color_for_abbr(team_abbr)
    st.markdown(
        f"<div style='display:flex;align-items:flex-start;gap:12px'>"
        f"<img src='{_headshot(player_id, team_abbr)}' style='width:64px;height:64px;border-radius:10px;"
        f"object-fit:cover;object-position:center 15%;flex-shrink:0;background:#1A1F2E' />"
        f"<div style='flex:1;min-width:0'>"
        f"<div style='color:var(--dm-dim);font-size:0.85rem'>{label}</div>"
        f"<div style='font-size:1.15rem;font-weight:700;line-height:1.3'>"
        f"<a href='{nstyle.player_link(player_id, season)}' target='_self' style='color:inherit;"
        f"text-decoration:none'>{name}</a> "
        f"<span style='background-color:{color}66;color:var(--dm-text);padding:2px 9px;border-radius:8px;"
        f"font-size:0.65em;vertical-align:middle;font-weight:600'>{team_abbr}</span></div>"
        f"<div style='margin-top:6px'><span style='background-color:var(--dm-blue-soft);color:var(--dm-blue-text);padding:3px 10px;"
        f"border-radius:8px;font-weight:600;font-size:0.9rem'>{stat_line}</span></div>"
        "</div></div>",
        unsafe_allow_html=True,
    )


def _cards(rows, per_row=4):
    """Rows of cards, a fresh st.columns() per row so mobile stacking keeps
    the order (see the Home page's note on column-major stacking)."""
    for start in range(0, len(rows), per_row):
        cols = st.columns(per_row)
        for col, r in zip(cols, rows[start:start + per_row]):
            with col:
                with st.container(border=True):
                    _player_card(*r)


# --- Scores ----------------------------------------------------------------
games = [g for g in ndb.load_schedule_for_date(day_str) if g.get("gameState") in ("OFF", "FINAL")]
style.colored_header("Final Scores", "headliners")
if not games:
    st.caption("No games were played.")
else:
    for start in range(0, len(games), 3):
        cols = st.columns(3)
        for col, g in zip(cols, games[start:start + 3]):
            away, home = g["awayTeam"], g["homeTeam"]
            a_s, h_s = away.get("score", 0), home.get("score", 0)
            outcome = (g.get("gameOutcome") or {}).get("lastPeriodType", "REG")
            suffix = "" if outcome == "REG" else f" ({outcome})"
            winner = home["abbrev"] if h_s > a_s else away["abbrev"]
            gwg = g.get("winningGoalScorer") or {}
            wg = g.get("winningGoalie") or {}
            notes = []
            if gwg:
                notes.append(f"GWG: {gwg.get('firstInitial', {}).get('default', '')} {gwg.get('lastName', {}).get('default', '')}")
            if wg:
                notes.append(f"W: {wg.get('firstInitial', {}).get('default', '')} {wg.get('lastName', {}).get('default', '')}")
            with col:
                with st.container(border=True):
                    def _row(team, score, won):
                        color = nteams.color_for_abbr(team["abbrev"])
                        weight = "800" if won else "500"
                        return (
                            "<div style='display:flex;align-items:center;justify-content:space-between;padding:3px 0'>"
                            f"<div style='display:flex;align-items:center;gap:8px'>"
                            f"<img src='{team.get('logo', '')}' style='height:26px;width:26px;object-fit:contain'>"
                            f"<span style='background-color:{color}66;color:var(--dm-text);padding:2px 8px;border-radius:6px;"
                            f"font-weight:700;font-size:0.8rem'>{team['abbrev']}</span>"
                            f"<span style='font-weight:{weight}'>{nteams.nickname_for_abbr(team['abbrev'])}</span></div>"
                            f"<span style='font-size:1.3rem;font-weight:{weight}'>{score}</span></div>"
                        )
                    st.markdown(
                        _row(away, a_s, winner == away["abbrev"]) + _row(home, h_s, winner == home["abbrev"])
                        + f"<div style='color:var(--dm-dim);font-size:0.8rem;margin-top:4px'>Final{suffix}"
                        + (" · " + " · ".join(notes) if notes else "") + "</div>",
                        unsafe_allow_html=True,
                    )
                    if st.button("Game Center", key=f"gc{g['id']}", use_container_width=True):
                        st.session_state["nhl_selected_game"] = int(g["id"])
                        st.switch_page("nhl/pages/game.py")

# --- Milestones --------------------------------------------------------------
milestones = ndb.get_daily_milestones(day_str, season, mtime)
if milestones:
    style.colored_header("Milestones", "headliners")
    _cards([(m["category"], m["name"], m["playerId"], m["Tm"], m["text"]) for m in milestones])

# --- Top performances ----------------------------------------------------------
skater_log = ndb.load_daily_skater_log(day_str)
goalie_log = ndb.load_daily_goalie_log(day_str)

if not skater_log.empty:
    names = ndb.load_skaters(season, mtime)[["playerId", "skaterFullName"]]
    top = (skater_log.merge(names, on="playerId", how="left")
           .sort_values(["points", "goals"], ascending=False).head(8))
    style.colored_header("Top Skater Performances", "batting")
    _cards([
        (f"#{i + 1}", r["skaterFullName"], r["playerId"], r["Tm"],
         f"{int(r['goals'])} G, {int(r['assists'])} A, {int(r['points'])} PTS")
        for i, (_, r) in enumerate(top.iterrows())
    ])

if not goalie_log.empty:
    names = ndb.load_goalies(season, mtime)[["playerId", "goalieFullName"]]
    g = goalie_log.merge(names, on="playerId", how="left")
    g = g[g["shotsAgainst"] >= 10].assign(saves=lambda d: d["shotsAgainst"] - d["goalsAgainst"])
    g["sv_pct"] = g["saves"] / g["shotsAgainst"] * 100
    top_g = g.sort_values(["shutout", "sv_pct", "saves"], ascending=False).head(4)
    if not top_g.empty:
        style.colored_header("Top Goalie Performances", "pitching")
        _cards([
            ("Shutout" if r["shutout"] else f"#{i + 1}", r["goalieFullName"], r["playerId"], r["Tm"],
             f"{int(r['saves'])} saves on {int(r['shotsAgainst'])} shots ({r['sv_pct']:.1f}%)")
            for i, (_, r) in enumerate(top_g.iterrows())
        ])

if skater_log.empty and goalie_log.empty and games:
    st.caption("Per-game lines for this date haven't been ingested yet (they land with the nightly refresh).")

# --- Streaks ------------------------------------------------------------------
standings = ndb.load_standings(day_str if day < today else "now")
if not standings.empty:
    hot = standings[(standings["streakCode"] == "W") & (standings["streakCount"] >= 3)].sort_values("streakCount", ascending=False)
    cold = standings[(standings["streakCode"] == "L") & (standings["streakCount"] >= 3)].sort_values("streakCount", ascending=False)
    if not hot.empty or not cold.empty:
        style.colored_header("Streaks", "fielding")
        c1, c2 = st.columns(2)
        for col, label, df in ((c1, "Winning", hot), (c2, "Losing", cold)):
            with col:
                st.markdown(f"**{label} streaks (3+)**")
                if df.empty:
                    st.caption("None right now.")
                for _, r in df.iterrows():
                    abbr = r["teamAbbrev"]
                    color = nteams.color_for_abbr(abbr)
                    st.markdown(
                        f"<div style='margin-bottom:6px'><a href='{nstyle.team_link(abbr)}' target='_self' "
                        f"style='background-color:{color}66;color:var(--dm-text);padding:2px 9px;border-radius:6px;"
                        f"font-weight:700;text-decoration:none'>{abbr}</a> "
                        f"<b>{int(r['streakCount'])} straight</b> "
                        f"<span style='color:var(--dm-dim)'>({int(r['wins'])}-{int(r['losses'])}-{int(r['otLosses'])}, {int(r['points'])} pts)</span></div>",
                        unsafe_allow_html=True,
                    )
