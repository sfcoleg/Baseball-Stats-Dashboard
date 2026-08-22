"""NHL Team — roster (live) + standings context + our own stat leaders for
one team."""
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nhl import db as ndb
from nhl import style as nstyle
from nhl import teams as nteams

st.set_page_config(page_title="NHL Team | Diamond Metrics", layout="wide")
st.title("Team")

clicked_team = st.query_params.get("team")
if clicked_team:
    st.session_state["nhl_team_page_selected_team"] = clicked_team

team_options = nteams.all_teams()
labels = [f"{abbr} — {nickname}" for abbr, nickname in team_options]

TEAM_CHOICE_KEY = "nhl_team_page_team_choice"
default_abbr = st.session_state.pop("nhl_team_page_selected_team", None)
if default_abbr:
    for label in labels:
        if label.startswith(f"{default_abbr} —"):
            st.session_state[TEAM_CHOICE_KEY] = label
            break
if st.session_state.get(TEAM_CHOICE_KEY) not in labels:
    st.session_state[TEAM_CHOICE_KEY] = labels[0]

choice = st.selectbox("Team", labels, key=TEAM_CHOICE_KEY)
abbr = choice.split(" — ")[0]
color = nteams.color_for_abbr(abbr)

st.markdown(
    f"<div style='display:flex;align-items:center;gap:14px;margin-bottom:8px'>"
    f"<img src='{nteams.logo_url(abbr)}' style='width:64px;height:64px' />"
    f"<div style='font-size:1.6rem;font-weight:800;color:{color}'>{nteams.nickname_for_abbr(abbr)}</div>"
    "</div>", unsafe_allow_html=True,
)

# --- Standings context -------------------------------------------------
standings = ndb.load_standings()
row = standings[standings["teamAbbrev"] == abbr] if not standings.empty else standings
if not row.empty:
    r = row.iloc[0]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Record", f"{int(r['wins'])}-{int(r['losses'])}-{int(r['otLosses'])}")
    m2.metric("Points", int(r["points"]))
    m3.metric(f"{r['divisionName']} Rank", int(r["divisionSequence"]))
    m4.metric("Goal Diff.", f"{int(r['goalDifferential']):+d}")
    streak = f"{r['streakCode']}{int(r['streakCount'])}" if pd.notna(r.get("streakCode")) else "—"
    m5.metric("Streak", streak)
else:
    st.caption("Standings unavailable right now.")

st.divider()

# --- Team stat leaders (from our ingested season tables) ---------------
mtime = ndb.nhl_db_mtime()
seasons = ndb.skater_seasons(mtime)
if seasons:
    stat_season = st.selectbox("Stat leaders — season", seasons, format_func=ndb.season_label)
    skaters = ndb.load_skaters(stat_season, mtime)
    skaters = skaters[skaters["teamAbbrevs"].map(nteams._primary) == abbr]
    goalies_df = ndb.load_goalies(stat_season, mtime) if stat_season in ndb.goalie_seasons(mtime) else pd.DataFrame()
    if not goalies_df.empty:
        goalies_df = goalies_df[goalies_df["teamAbbrevs"].map(nteams._primary) == abbr]

    style.colored_header("Team Leaders", "batting")
    lead_cols = st.columns(4)
    leaders = [
        ("points", "Points", skaters), ("goals", "Goals", skaters),
        ("assists", "Assists", skaters), ("hits", "Hits", skaters),
    ]
    for col, (stat, label, df) in zip(lead_cols, leaders):
        with col:
            st.markdown(f"**{label}**")
            top = df.sort_values(stat, ascending=False).head(5)
            for _, p in top.iterrows():
                st.markdown(
                    f"<a href='{nstyle.player_link(p['playerId'], stat_season)}' target='_self' "
                    f"style='color:inherit;text-decoration:none'>{p['skaterFullName']}</a> "
                    f"<span style='color:#9AA3B5'>— {int(p[stat])}</span>",
                    unsafe_allow_html=True,
                )
    if not goalies_df.empty:
        st.markdown("**Goaltending**")
        top_g = goalies_df.sort_values("wins", ascending=False).head(3)
        gcols = st.columns(3)
        for gcol, (_, g) in zip(gcols, top_g.iterrows()):
            with gcol:
                st.markdown(
                    f"<a href='{nstyle.player_link(g['playerId'], stat_season)}' target='_self' "
                    f"style='color:inherit;text-decoration:none;font-weight:600'>{g['goalieFullName']}</a>",
                    unsafe_allow_html=True,
                )
                st.caption(f"{int(g['wins'])}-{int(g['losses'])}-{int(g['otLosses'])} · {g['savePct']:.1f} SV%")

st.divider()

# --- Schedule ------------------------------------------------------------
style.colored_header("Schedule", "chart")
games = ndb.load_club_schedule(abbr)
if not games:
    st.caption("Schedule unavailable right now.")
else:
    def _opp(g):
        is_home = g["homeTeam"]["abbrev"] == abbr
        opp = g["awayTeam"]["abbrev"] if is_home else g["homeTeam"]["abbrev"]
        return is_home, opp

    def _local_time(g):
        try:
            utc = datetime.fromisoformat(g["startTimeUTC"].replace("Z", "+00:00"))
            return utc.astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M %p ET")
        except Exception:
            return ""

    played = [g for g in games if g.get("gameState") in ("OFF", "FINAL")]
    upcoming = [g for g in games if g.get("gameState") not in ("OFF", "FINAL")]
    wins = sum(
        1 for g in played
        if (g["homeTeam"].get("score", 0) > g["awayTeam"].get("score", 0)) == (g["homeTeam"]["abbrev"] == abbr)
    )
    up_tab, res_tab = st.tabs([f"Upcoming ({len(upcoming)})", f"Results ({len(played)})"])
    with up_tab:
        rows = []
        for g in upcoming:
            is_home, opp = _opp(g)
            p_home = ndb.game_win_prob(g["homeTeam"]["abbrev"], g["awayTeam"]["abbrev"]) if g.get("gameType") != 1 else None
            p_us = None if p_home is None else (p_home if is_home else 1 - p_home)
            rows.append({
                "Date": pd.to_datetime(g["gameDate"]).strftime("%a %b %-d"),
                "": "vs" if is_home else "@", "Opponent": opp, "Time": _local_time(g),
                "Win%": f"{p_us * 100:.0f}%" if p_us is not None else "",
                "Type": {1: "Preseason", 2: "", 3: "Playoffs"}.get(g.get("gameType"), ""),
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=min(520, 38 * (len(rows) + 1)))
        else:
            st.caption("No games left on the schedule.")
    with res_tab:
        if not played:
            st.caption("No games played yet this season.")
        else:
            st.caption(f"{wins}-{len(played) - wins} in games played.")
            rows = []
            for g in reversed(played):
                is_home, opp = _opp(g)
                us = g["homeTeam"].get("score", 0) if is_home else g["awayTeam"].get("score", 0)
                them = g["awayTeam"].get("score", 0) if is_home else g["homeTeam"].get("score", 0)
                last = (g.get("gameOutcome") or {}).get("lastPeriodType", "REG")
                rows.append({
                    "Date": pd.to_datetime(g["gameDate"]).strftime("%a %b %-d"),
                    "": "vs" if is_home else "@", "Opponent": opp,
                    "Result": f"{'W' if us > them else 'L'} {us}-{them}" + ("" if last == "REG" else f" ({last})"),
                    "Type": {1: "Preseason", 2: "", 3: "Playoffs"}.get(g.get("gameType"), ""),
                    "Game Center": f"nhl-game?game={g['id']}",
                })
            st.dataframe(
                pd.DataFrame(rows), hide_index=True, use_container_width=True, height=min(520, 38 * (len(rows) + 1)),
                column_config={"Game Center": st.column_config.LinkColumn("Game Center", display_text="Open")},
            )

st.divider()

# --- Roster (live) -------------------------------------------------------
style.colored_header("Roster", "pitching")
roster = ndb.load_roster(abbr)
if not roster:
    st.info("Roster unavailable right now.")
else:
    group_labels = {"forwards": "Forwards", "defensemen": "Defense", "goalies": "Goalies"}
    tabs = st.tabs(list(group_labels.values()))
    for tab, (key, label) in zip(tabs, group_labels.items()):
        with tab:
            players = sorted(roster.get(key, []), key=lambda p: p.get("sweaterNumber") or 99)
            cols = st.columns(4)
            for i, p in enumerate(players):
                with cols[i % 4]:
                    name = f"{p['firstName']['default']} {p['lastName']['default']}"
                    num = p.get("sweaterNumber", "—")
                    st.markdown(
                        f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:10px'>"
                        f"<img src='{p.get('headshot', '')}' style='width:44px;height:44px;border-radius:8px;"
                        "object-fit:cover' />"
                        f"<div><a href='{nstyle.player_link(p['id'])}' target='_self' style='color:inherit;"
                        f"text-decoration:none;font-weight:600'>{name}</a><br>"
                        f"<span style='color:#9AA3B5;font-size:0.85rem'>#{num} · {p.get('positionCode', '')}</span>"
                        "</div></div>", unsafe_allow_html=True,
                    )
