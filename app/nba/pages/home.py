"""NBA Home — today's games plus the same shape MLB/NHL Home pages use in
their own offseasons: a real leaderboard and standings snapshot built from
the last completed season's data, so the page still has something to show
when nothing is being played today. Confirmed directly against the live
scoreboard endpoint that an empty slate is a real state (outside the
season it genuinely returns zero rows, not an error), not a failure to
handle."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nba import db as ndb
from nba import style as nstyle
from nba import teams as nteams

st.set_page_config(page_title="NBA | Diamond Metrics", layout="wide")
st.title("NBA")

mtime = ndb.nba_db_mtime()

# --- Today's games --------------------------------------------------------
games = ndb.load_todays_games(mtime)
if games.empty:
    st.caption(f"No games today. {ndb.current_season_label()} season status: check Standings.")
else:
    for _, g in games.iterrows():
        away, home = g.get("away_abbr") or "?", g.get("home_abbr") or "?"
        # gameStatus: 1 scheduled (no score yet), 2 live, 3 final.
        status_code = g.get("game_status")
        a_score = g.get("away_score") if status_code != 1 else None
        h_score = g.get("home_score") if status_code != 1 else None
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 1, 2])
            a_line = f"**{nteams.nickname_for_abbr(away)}** ({away})"
            h_line = f"**{nteams.nickname_for_abbr(home)}** ({home})"
            if a_score is not None:
                a_line += f" — {int(a_score)}"
            if h_score is not None:
                h_line += f" — {int(h_score)}"
            c1.markdown(a_line)
            live_chip = " 🔴" if status_code == 2 else ""
            c2.markdown(f"<div style='text-align:center;color:var(--dm-dim)'>"
                       f"{g.get('game_status_text', '')}{live_chip}</div>", unsafe_allow_html=True)
            c3.markdown(h_line)

players = ndb.load_player_stats(mtime)
if players.empty:
    st.info("No NBA player data yet — run `python ingest/nba_refresh.py` to build it.")
    st.stop()

season_label = ndb.player_stats_season(mtime)
st.divider()
st.caption(f"{season_label} season" + (
    " — the most recently completed one; this season hasn't tipped off yet."
    if season_label and season_label != ndb.current_season_label() else "."
))

# --- Points Leaders card grid ---------------------------------------------
style.colored_header("Points Leaders", "batting")
pool = ndb.qualified_players(players)
top = pool.sort_values("PTS_PG", ascending=False).head(10)
cards = ""
for i, (_, p) in enumerate(top.iterrows()):
    tm = p["TEAM_ABBREVIATION"]
    color = nteams.color_for_abbr(tm)
    badge_text = style.readable_text_color(color)
    points_color = style.team_text_color(color)
    pid = int(p["PLAYER_ID"])
    cards += (
        f"<div style='position:relative;text-align:center;background:linear-gradient(180deg,{color}26,transparent);"
        f"border:1px solid {color}55;border-radius:12px;padding:14px 8px 10px'>"
        f"<div style='position:absolute;top:6px;left:8px;background:{color};color:{badge_text};"
        f"font-weight:800;font-size:0.75rem;width:20px;height:20px;border-radius:50%;"
        f"display:flex;align-items:center;justify-content:center'>{i + 1}</div>"
        f"<img src='{nstyle.headshot_url(pid)}' style='width:72px;height:72px;border-radius:50%;object-fit:cover;"
        f"object-position:top;border:2px solid {color};background:var(--dm-surface-mute)' "
        f"onerror=\"this.style.display='none'\" />"
        f"<div style='margin-top:8px;font-weight:700;font-size:0.92rem;line-height:1.2'>"
        f"<a href='{nstyle.player_link(pid, season_label)}' target='_self' "
        f"style='color:var(--dm-text);text-decoration:none'>{p['PLAYER_NAME']}</a></div>"
        f"<span style='display:inline-block;margin-top:4px;background-color:{color}66;color:var(--dm-text);"
        f"padding:1px 8px;border-radius:6px;font-size:0.75rem;font-weight:700'>{tm}</span>"
        f"<div style='margin-top:6px;font-size:1.4rem;font-weight:800;color:{points_color}'>{p['PTS_PG']:.1f}"
        f"<span style='font-size:0.7rem;font-weight:600;color:var(--dm-dim)'> PPG</span></div>"
        "</div>"
    )
st.markdown(
    "<div style='display:grid;grid-template-columns:repeat(auto-fit, minmax(120px, 1fr));gap:12px'>" + cards + "</div>",
    unsafe_allow_html=True,
)

st.divider()

# --- Standings snapshot -----------------------------------------------
standings = ndb.load_standings(mtime)
if not standings.empty:
    style.colored_header("Standings", "chart")
    abbr_map = ndb.team_abbr_map(mtime)
    conferences = [c for c in ("East", "West") if c in standings["Conference"].unique()]
    s_cols = st.columns(len(conferences)) if conferences else []
    for col, conf in zip(s_cols, conferences):
        with col:
            st.markdown(f"**{conf}**")
            conf_standings = standings[standings["Conference"] == conf].sort_values("PlayoffRank")
            rows = "".join(
                f"<tr style='border-top:1px solid var(--dm-line)'>"
                f"<td style='padding:4px 8px'><span style='background-color:"
                f"{nteams.color_for_abbr(abbr_map.get(r.team_id, '?'))}66;color:var(--dm-text);"
                f"padding:2px 8px;border-radius:6px;font-weight:700'>{abbr_map.get(r.team_id, '?')}</span></td>"
                f"<td style='padding:4px 8px;text-align:center'>{int(r.WINS)}</td>"
                f"<td style='padding:4px 8px;text-align:center'>{int(r.LOSSES)}</td></tr>"
                for r in conf_standings.itertuples()
            )
            st.markdown(
                f"<table style='width:100%;border-collapse:collapse;font-size:0.85rem'>{rows}</table>",
                unsafe_allow_html=True,
            )
    if ndb.standings_are_preseason(mtime):
        st.caption(f"{ndb.current_season_label()} hasn't tipped off yet — this is the real, unplayed record.")
    else:
        st.caption("See the Standings page for conference and division detail.")
    st.divider()

# --- Full leader table ----------------------------------------------------
style.colored_header(f"Scoring Leaders (min {ndb.MIN_GAMES} GP)", "batting")
st.caption(f"Top 50 of {len(pool)} qualified players by points per game — see Player Stats for the full filterable list.")
display = pool.sort_values("PTS_PG", ascending=False).head(50)
display = display.rename(columns={"TEAM_ABBREVIATION": "Tm"})[
    ["PLAYER_NAME", "Tm", "GP", "MIN_PG", "PTS_PG", "REB_PG", "AST_PG"]
].rename(columns={"PLAYER_NAME": "Player", "MIN_PG": "MPG", "PTS_PG": "PPG", "REB_PG": "RPG", "AST_PG": "APG"})
st.dataframe(
    style.style_stats_table(
        display, team_col="Tm", team_color_fn=nteams.color_for_abbr,
        higher_better=["PPG", "RPG", "APG"],
        precision={"MPG": "{:.1f}", "PPG": "{:.1f}", "RPG": "{:.1f}", "APG": "{:.1f}"},
    ),
    use_container_width=True, hide_index=True, height=400,
)

st.info("Use the pages in the sidebar for filterable Player Stats, Team rosters, and Compare.")
