"""The cross-sport landing page — the site's front door.

Three sports used to mean three separate front doors, with `/` quietly
meaning "baseball". This is the one page that knows about all of them: what
is on tonight across every league that is actually playing, the teams you
follow wherever they play, and a way into each sport.

Deliberately does NOT try to be a fourth sport section. It answers "what
should I look at right now" and then gets out of the way — the depth stays
in each league's own pages."""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent))
import db
import following_page
import style
import teams

st.set_page_config(page_title="Diamond Metrics", layout="wide")

TODAY = db.today_pacific()

# --- Header -----------------------------------------------------------------
st.markdown(
    "<div style='display:flex;align-items:baseline;gap:14px;flex-wrap:wrap'>"
    "<span style='font-family:\"Archivo Narrow\",sans-serif;font-weight:800;"
    "font-size:2.6rem;letter-spacing:-0.5px;color:var(--dm-text)'>Diamond Metrics</span>"
    f"<span style='color:var(--dm-dim);font-size:0.95rem'>{TODAY.strftime('%A, %B %-d, %Y')}</span>"
    "</div>",
    unsafe_allow_html=True,
)


def _fmt_time(raw) -> str:
    """MLB stores kickoff as a UTC ISO stamp; show it in Pacific, the
    timezone the rest of the site already thinks in."""
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%-I:%M %p PT")
    except Exception:
        return ""


# --- Tonight ----------------------------------------------------------------
def _mlb_games():
    """(rows, note) for MLB. Rows are dicts the shared renderer understands."""
    try:
        games = db.load_todays_games(db.db_mtime(), TODAY.isoformat())
    except Exception:
        return [], None
    if games.empty:
        return [], "No games scheduled."
    try:
        live = db.load_live_scores(games.iloc[0]["date"])
    except Exception:
        live = {}
    rows = []
    for _, g in games.iterrows():
        # load_live_scores keys on game_pk with away_score/home_score — the
        # stored todays_games table carries no scores at all, only pre-game
        # state, so this join is what makes the column live rather than a
        # list of kickoff times.
        score = live.get(int(g["game_pk"]), {}) if isinstance(live, dict) else {}
        away_score, home_score = score.get("away_score"), score.get("home_score")
        status = score.get("status") or str(g.get("status") or "")
        started = status not in ("Scheduled", "Pre-Game", "Delayed Start")
        if started and away_score is not None:
            # Mid-game shows the inning; a finished game just says Final.
            detail = "Final" if status == "Final" else (score.get("inning") or status)
        else:
            away_score = home_score = None
            detail = _fmt_time(g.get("game_time")) or status
        rows.append({
            "away": g["away_abbr"], "home": g["home_abbr"],
            "away_score": away_score, "home_score": home_score,
            "detail": detail, "color": teams.color_for_abbr,
        })
    return rows, None


def _nhl_games():
    try:
        from nhl import db as ndb
        from nhl import teams as nteams
    except Exception:
        return [], None
    try:
        games = ndb.load_schedule_for_date(TODAY.strftime("%Y-%m-%d"))
    except Exception:
        return [], "Schedule unavailable right now."
    if not games:
        return [], "Between seasons — the NHL returns in October."
    rows = []
    for g in games:
        rows.append({
            "away": (g.get("awayTeam") or {}).get("abbrev", "?"),
            "home": (g.get("homeTeam") or {}).get("abbrev", "?"),
            "away_score": (g.get("awayTeam") or {}).get("score"),
            "home_score": (g.get("homeTeam") or {}).get("score"),
            "detail": g.get("gameState") or "",
            "color": nteams.color_for_abbr,
        })
    return rows, None


def _nfl_games():
    try:
        from nfl import db as fdb
        from nfl import teams as fteams
    except Exception:
        return [], None
    try:
        mtime = fdb.nfl_db_mtime()
        # The NEWEST season, not default_season — that helper deliberately
        # prefers the last season with results so stat pages don't open
        # empty, but here it would report "season complete" all summer while
        # the upcoming schedule sits in the database unread.
        available = fdb.seasons(mtime)
        season = available[0] if available else None
        games = fdb.load_games(season, mtime) if season else pd.DataFrame()
    except Exception:
        return [], None
    if games.empty:
        return [], "No schedule loaded."
    today_games = games[games["gameday"].astype(str).str.startswith(TODAY.isoformat())]
    if today_games.empty:
        # Point at the next kickoff instead of an empty box — during the
        # long NFL week that is far more useful than "nothing today".
        upcoming = games[games["gameday"].astype(str) > TODAY.isoformat()]
        if upcoming.empty:
            return [], "Season complete."
        nxt = upcoming.iloc[0]
        return [], f"Next game {nxt['gameday']} — {nxt['away_team']} at {nxt['home_team']}."
    rows = []
    for _, g in today_games.iterrows():
        played = pd.notna(g.get("home_score"))
        rows.append({
            "away": g["away_team"], "home": g["home_team"],
            "away_score": int(g["away_score"]) if played else None,
            "home_score": int(g["home_score"]) if played else None,
            "detail": "Final" if played else str(g.get("gametime") or ""),
            "color": fteams.color_for_abbr,
        })
    return rows, None


def _render_games(rows):
    for r in rows:
        a_score = "" if r["away_score"] is None else int(r["away_score"])
        h_score = "" if r["home_score"] is None else int(r["home_score"])
        a_win = a_score != "" and h_score != "" and a_score > h_score
        h_win = a_score != "" and h_score != "" and h_score > a_score

        def side(abbr, score, won):
            weight = "700" if won else "600"
            colour = "var(--dm-text)" if won or score == "" else "var(--dm-dim)"
            return (
                f"<span style='display:inline-block;min-width:2.6rem;font-family:\"Archivo Narrow\","
                f"sans-serif;font-weight:{weight};color:{colour}'>{abbr}</span>"
                f"<span style='font-family:\"Archivo Narrow\",sans-serif;font-weight:700;"
                f"color:{colour};min-width:1.6rem;display:inline-block;text-align:right'>{score}</span>"
            )

        st.markdown(
            "<div style='display:flex;align-items:center;justify-content:space-between;"
            "gap:10px;padding:5px 0;border-bottom:1px solid var(--dm-line)'>"
            f"<span>{side(r['away'], a_score, a_win)}"
            "<span style='color:var(--dm-dim);margin:0 6px'>@</span>"
            f"{side(r['home'], h_score, h_win)}</span>"
            f"<span style='color:var(--dm-dim);font-size:0.78rem;white-space:nowrap'>{r['detail']}</span>"
            "</div>",
            unsafe_allow_html=True,
        )


style.colored_header("Today", "headliners")
_sections = [("MLB", _mlb_games()), ("NHL", _nhl_games()), ("NFL", _nfl_games())]
_cols = st.columns(3)
for _col, (_label, (_rows, _note)) in zip(_cols, _sections):
    with _col:
        st.markdown(f"**{_label}**")
        if _rows:
            _render_games(_rows[:8])
            if len(_rows) > 8:
                st.caption(f"+{len(_rows) - 8} more")
        else:
            st.caption(_note or "Nothing scheduled.")

# NFL data comes from nflverse, which publishes after games finish rather
# than during them — saying so beats implying live coverage it can't give.
st.caption("MLB and NHL scores update live. NFL results appear after games finish.")

# --- Your teams -------------------------------------------------------------
# Colour lookups per league, resolved once. Built defensively because this
# page must render even if one sport's module or database is unavailable —
# it's the front door, so a single broken sport must not take it down.
_TEAM_COLOUR = {"MLB": teams.color_for_abbr}
try:
    from nhl import teams as _nteams_c
    _TEAM_COLOUR["NHL"] = _nteams_c.color_for_abbr
except Exception:
    pass
try:
    from nfl import teams as _fteams_c
    _TEAM_COLOUR["NFL"] = _fteams_c.color_for_abbr
except Exception:
    pass

_lists = following_page._lists()
_followed = [(label, v["teams"]) for label, v in _lists.items() if v["teams"]]
if _followed:
    style.colored_header("Your Teams", "batting")
    _cols = st.columns(min(len(_followed), 3))
    for _col, (_label, _teams_list) in zip(_cols, _followed):
        with _col:
            st.markdown(f"**{_label}**")
            _colour = _TEAM_COLOUR.get(_label)
            for _t in _teams_list:
                # Each league has its own colour lookup; fall back to the
                # neutral surface when a sport's module isn't importable, so
                # a missing database costs the colour, not the chip.
                _c = _colour(_t["abbr"]) if _colour else None
                st.markdown(
                    following_page.team_chip(_t["abbr"], _t.get("nickname", ""), _c)
                    if _c else
                    f"<span style='background-color:var(--dm-surface-mute);color:var(--dm-text);"
                    f"padding:3px 10px;border-radius:8px;font-weight:700;margin-right:6px'>"
                    f"{_t['abbr']}</span>{_t.get('nickname', '')}",
                    unsafe_allow_html=True,
                )
    st.page_link("views/13_Following.py", label="Manage who you follow →")
