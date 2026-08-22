"""NHL Team — roster (live) + standings context + our own stat leaders for
one team."""
import sys
from pathlib import Path

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
