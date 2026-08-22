"""NHL Schedule — the week ahead, league-wide: every game day by day with
our Elo odds, the matchups worth circling (two strong teams, close odds),
and who's on a back-to-back. Today's Games covers one day in depth; this
is the forward view, with week-to-week paging."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nhl import db as ndb
from nhl import teams as nteams

st.set_page_config(page_title="NHL Schedule | Diamond Metrics", layout="wide")
st.title("Schedule")

if "nhl_schedule_start" not in st.session_state:
    st.session_state["nhl_schedule_start"] = "now"
week = ndb.load_schedule_week(st.session_state["nhl_schedule_start"])

nav1, nav2, nav3 = st.columns([1, 2, 1])
with nav1:
    if st.button("← Previous week", disabled=not week["prev"]):
        st.session_state["nhl_schedule_start"] = week["prev"]
        st.rerun()
with nav3:
    if st.button("Next week →", disabled=not week["next"]):
        st.session_state["nhl_schedule_start"] = week["next"]
        st.rerun()
with nav2:
    team_filter = st.selectbox(
        "Team", ["All teams"] + [a for a, _ in nteams.all_teams()],
        format_func=lambda a: a if a == "All teams" else f"{a} — {nteams.nickname_for_abbr(a)}",
        label_visibility="collapsed",
    )

days = week["days"]
if not days or not any(d["games"] for d in days):
    st.info("No games scheduled this week.")
    st.stop()

elo = ndb.load_elo_model()
ratings = (elo or {}).get("ratings", {})


def _badge(abbr: str) -> str:
    color = nteams.color_for_abbr(abbr)
    return (f"<span style='background-color:{color}66;color:#FAFAFA;padding:2px 8px;border-radius:6px;"
            f"font-weight:700'>{abbr}</span>")


def _odds(game: dict):
    """(favorite abbr, favorite win%) from the Elo model, or None."""
    p_home = ndb.game_win_prob(game["homeTeam"]["abbrev"], game["awayTeam"]["abbrev"])
    if p_home is None:
        return None
    if p_home >= 0.5:
        return game["homeTeam"]["abbrev"], p_home
    return game["awayTeam"]["abbrev"], 1 - p_home


rows = []
for d in days:
    for g in d["games"]:
        a, h = g["awayTeam"]["abbrev"], g["homeTeam"]["abbrev"]
        if team_filter != "All teams" and team_filter not in (a, h):
            continue
        rows.append({
            "date": d["date"], "game": g, "away": a, "home": h, "type": g.get("gameType"),
            "state": g.get("gameState"), "utc": g.get("startTimeUTC", ""),
            "elo_a": ratings.get(a, 1500.0), "elo_h": ratings.get(h, 1500.0),
        })
if not rows:
    st.info(f"{team_filter} doesn't play this week.")
    st.stop()
sched = pd.DataFrame(rows)

# --- Games to watch ---------------------------------------------------------
# Two good teams AND a close game: rank regular-season games by the pair's
# combined Elo, then by how even the odds are.
watch = sched[(sched["type"] == 2) & (sched["state"] == "FUT")].copy()
if ratings and not watch.empty and team_filter == "All teams":
    watch["combined"] = watch["elo_a"] + watch["elo_h"]
    watch["gap"] = (watch["elo_a"] - watch["elo_h"]).abs()
    watch["score"] = watch["combined"] - 2 * watch["gap"]
    top = watch.sort_values("score", ascending=False).head(5)
    style.colored_header("Games to Watch", "headliners")
    for _, r in top.iterrows():
        o = _odds(r["game"])
        odds_txt = f"{o[0]} {o[1] * 100:.0f}%" if o else ""
        st.markdown(
            f"<div style='background-color:#1B243866;border-left:4px solid #F5B942;padding:8px 14px;"
            f"border-radius:6px;margin:5px 0;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px'>"
            f"<div><span style='color:#9AA3B5;font-size:0.85rem'>{pd.to_datetime(r['date']).strftime('%a %b %-d')}</span><br>"
            f"{_badge(r['away'])} <span style='color:#9AA3B5;font-size:0.85rem'>Elo {r['elo_a']:.0f}</span>"
            f" <span style='color:#9AA3B5'>@</span> "
            f"{_badge(r['home'])} <span style='color:#9AA3B5;font-size:0.85rem'>Elo {r['elo_h']:.0f}</span></div>"
            f"<span style='color:#DCE1EA;font-weight:700;white-space:nowrap'>{odds_txt}</span></div>",
            unsafe_allow_html=True,
        )

# --- Back-to-backs ------------------------------------------------------------
# Teams playing on consecutive calendar days this week (second night of a
# back-to-back is the classic spot for a backup goalie and a tired third
# period). Computed from the unfiltered week so a filtered team still sees
# its own.
all_games = [(d["date"], g["awayTeam"]["abbrev"], g["homeTeam"]["abbrev"]) for d in days for g in d["games"] if g.get("gameType") == 2]
by_team: dict[str, list] = {}
for date_str, a, h in all_games:
    by_team.setdefault(a, []).append(date_str)
    by_team.setdefault(h, []).append(date_str)
b2b = []
for abbr, dates in by_team.items():
    ds = sorted(set(pd.to_datetime(x).date() for x in dates))
    for d1, d2 in zip(ds, ds[1:]):
        if (d2 - d1).days == 1:
            b2b.append((abbr, d1, d2))
if team_filter != "All teams":
    b2b = [x for x in b2b if x[0] == team_filter]
if b2b:
    style.colored_header("Back-to-Backs", "fielding")
    b2b.sort(key=lambda x: (x[1], x[0]))
    chips = " ".join(
        f"<span style='display:inline-block;margin:3px 6px 3px 0'>{_badge(abbr)} "
        f"<span style='color:#9AA3B5;font-size:0.85rem'>{d1.strftime('%a')} → {d2.strftime('%a')}</span></span>"
        for abbr, d1, d2 in b2b
    )
    st.markdown(chips, unsafe_allow_html=True)

# --- Day by day -----------------------------------------------------------------
for date_str, day_games in sched.groupby("date", sort=True):
    style.colored_header(pd.to_datetime(date_str).strftime("%A, %B %-d"), "batting")
    for _, r in day_games.sort_values("utc").iterrows():
        g = r["game"]
        tag = ""
        if r["type"] == 1:
            tag = "<span style='color:#9AA3B5;font-size:0.75rem;border:1px solid #4A5266;padding:1px 6px;border-radius:6px;margin-left:6px'>PRESEASON</span>"
        elif r["type"] == 3:
            tag = "<span style='color:#F5B942;font-size:0.75rem;border:1px solid #F5B942;padding:1px 6px;border-radius:6px;margin-left:6px'>PLAYOFFS</span>"
        if r["state"] in ("OFF", "FINAL"):
            right = (f"<span style='color:#DCE1EA;font-weight:700'>{g['awayTeam'].get('score', '')} – {g['homeTeam'].get('score', '')}</span>"
                     f" <span style='color:#9AA3B5;font-size:0.85rem'>Final</span>")
        elif r["state"] in ("LIVE", "CRIT"):
            right = "<span style='background-color:#D32F2F;color:#FFF;padding:2px 8px;border-radius:6px;font-weight:700;font-size:0.75rem'>LIVE</span>"
        else:
            o = _odds(g) if r["type"] != 1 else None
            right = f"<span style='color:#9AA3B5;font-size:0.85rem;white-space:nowrap'>{o[0]} {o[1] * 100:.0f}%</span>" if o else ""
        venue = (g.get("venue") or {}).get("default", "")
        st.markdown(
            f"<div style='background-color:#1B243866;padding:8px 14px;border-radius:6px;margin:4px 0;"
            f"display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap'>"
            f"<div style='min-width:0'>{_badge(r['away'])} <span style='color:#9AA3B5'>@</span> {_badge(r['home'])}"
            f" <span class='game-time-local' data-utc='{r['utc']}' style='color:#9AA3B5;font-size:0.85rem'></span>{tag}"
            f"<div style='color:#9AA3B5;font-size:0.8rem;margin-top:2px'>{venue}</div></div>"
            f"{right}</div>",
            unsafe_allow_html=True,
        )

# Localize game times to the viewer's clock — same data-utc pattern as the
# MLB Schedule page (the server can't know the browser's timezone).
components.html(
    """
    <script>
    (function() {
        const els = window.parent.document.querySelectorAll('.game-time-local[data-utc]');
        els.forEach(function(el) {
            const d = new Date(el.dataset.utc);
            if (isNaN(d.getTime())) return;
            el.textContent = '· ' + d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
        });
    })();
    </script>
    """,
    height=0,
)
