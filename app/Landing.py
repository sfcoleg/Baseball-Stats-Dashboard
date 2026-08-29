"""The cross-sport landing page — the site's front door.

Three sports used to mean three separate front doors, with `/` quietly
meaning "baseball". This is the one page that knows about all of them, and
it leads with the most alive things the site has: last night's best home run
as video, real faces on the league leaders, live scores with team colour.
The depth stays in each league's own pages — this answers "what should I
look at right now" and hands you off."""
import re
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
MTIME = db.db_mtime()
LOGO_SEASON = TODAY.year

# Optional sports: resolved once, defensively. The front door must render
# even if one league's module or database is broken — a missing sport costs
# its column, never the page.
try:
    from nhl import db as ndb
    from nhl import teams as nteams
except Exception:
    ndb = nteams = None
try:
    from nfl import db as fdb
    from nfl import teams as fteams
except Exception:
    fdb = fteams = None


def _mlb_logo(abbr: str) -> str | None:
    ab = teams.normalize_mlb_abbr(abbr)
    team_id = teams.team_id_for_abbr(ab)
    return style.team_logo_for_season(ab, team_id, LOGO_SEASON) if team_id else None


# --- Header ------------------------------------------------------------------
st.markdown(
    "<div style='display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:2px'>"
    "<span style='font-family:\"Archivo Narrow\",sans-serif;font-weight:800;"
    "font-size:2.4rem;letter-spacing:-0.5px;color:var(--dm-text)'>Diamond Metrics</span>"
    f"<span style='color:var(--dm-dim);font-size:0.95rem'>{TODAY.strftime('%A, %B %-d, %Y')}</span>"
    "</div>",
    unsafe_allow_html=True,
)

# --- Play of the Day ---------------------------------------------------------
# The single most alive asset the site owns: MLB publishes a real clip for
# nearly every home run, and hr_log already stores every one with its
# game_pk. One lookup, cached half an hour, and the front door opens on
# actual footage instead of a wall of numbers.
def _play_of_the_day():
    try:
        with __import__("sqlite3").connect(db.DB_PATH) as conn:
            row = conn.execute(
                "SELECT game_date, game_pk, batter, des, hit_distance_sc, launch_speed "
                "FROM hr_log WHERE des IS NOT NULL ORDER BY game_date DESC, rowid DESC LIMIT 1"
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    game_date, game_pk, batter, des, dist, ev = row
    number = re.search(r"\((\d+)\)", des or "")
    try:
        clip = db.find_home_run_clip(int(batter), int(game_pk), int(number.group(1)) if number else None)
    except Exception:
        clip = None
    if not clip:
        return None
    name = re.split(r" homers | hits a grand slam ", des)[0].strip()
    batting = db.load_batting(TODAY.year, MTIME)
    match = batting[batting["mlbID"] == int(batter)]
    abbr = teams.team_meta_from_city(match.iloc[0]["Tm"], match.iloc[0].get("Lev"))[0] if not match.empty else ""
    color = teams.color_for_abbr(abbr) if abbr else "#2E86DE"
    stats = " · ".join(p for p in (
        f"{int(dist)} ft" if pd.notna(dist) else "", f"{ev:.1f} mph" if pd.notna(ev) else "",
    ) if p)
    return {"clip": clip, "name": name, "abbr": abbr, "color": color,
            "des": des, "stats": stats, "mlbID": int(batter),
            "date": str(game_date)[:10]}


_potd = _play_of_the_day()
if _potd:
    style.colored_header("Play of the Day", "headliners")
    with st.container(border=True):
        vid_col, info_col = st.columns([3, 2])
        with vid_col:
            st.video(_potd["clip"])
        with info_col:
            c = _potd["color"]
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:14px;padding:10px 4px;"
                f"border-left:4px solid {c};padding-left:14px'>"
                f"<img src='{style.headshot_url(_potd['mlbID'], width=180)}' "
                f"style='width:72px;height:72px;border-radius:50%;object-fit:cover;"
                f"object-position:center 20%;border:2.5px solid {c}' />"
                f"<div><div style='font-family:\"Archivo Narrow\",sans-serif;font-weight:800;"
                f"font-size:1.35rem;color:var(--dm-text)'>{_potd['name']} "
                f"<span style='background-color:{c}66;color:var(--dm-text);padding:2px 9px;"
                f"border-radius:8px;font-size:0.6em;vertical-align:middle;font-weight:600'>{_potd['abbr']}</span></div>"
                + (f"<div style='color:{style.team_text_color(c)};font-family:\"Archivo Narrow\",sans-serif;"
                   f"font-weight:700;font-size:1.05rem;margin-top:2px'>{_potd['stats']}</div>" if _potd["stats"] else "")
                + f"</div></div>"
                f"<p style='color:var(--dm-dim);font-size:0.86rem;margin:8px 0 0 18px'>{_potd['des']}</p>",
                unsafe_allow_html=True,
            )


def _fmt_time(raw) -> str:
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%-I:%M %p")
    except Exception:
        return ""


# --- Today -------------------------------------------------------------------
def _mlb_games():
    try:
        games = db.load_todays_games(MTIME, TODAY.isoformat())
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
        score = live.get(int(g["game_pk"]), {}) if isinstance(live, dict) else {}
        away_score, home_score = score.get("away_score"), score.get("home_score")
        status = score.get("status") or str(g.get("status") or "")
        started = status not in ("Scheduled", "Pre-Game", "Delayed Start")
        live_now = started and status != "Final"
        if started and away_score is not None:
            detail = "Final" if status == "Final" else (score.get("inning") or status)
        else:
            away_score = home_score = None
            detail = _fmt_time(g.get("game_time")) or status
        rows.append({
            "away": g["away_abbr"], "home": g["home_abbr"],
            "away_logo": _mlb_logo(g["away_abbr"]), "home_logo": _mlb_logo(g["home_abbr"]),
            "away_score": away_score, "home_score": home_score,
            "detail": detail, "live": live_now,
            "color": teams.color_for_abbr(teams.normalize_mlb_abbr(g["home_abbr"])),
        })
    return rows, None


def _nhl_games():
    if ndb is None:
        return [], None
    try:
        games = ndb.load_schedule_for_date(TODAY.strftime("%Y-%m-%d"))
    except Exception:
        return [], "Schedule unavailable right now."
    if not games:
        return [], "Between seasons — back in October."
    rows = []
    for g in games:
        away = (g.get("awayTeam") or {}).get("abbrev", "?")
        home = (g.get("homeTeam") or {}).get("abbrev", "?")
        state = g.get("gameState") or ""
        rows.append({
            "away": away, "home": home,
            "away_logo": nteams.logo_url(away), "home_logo": nteams.logo_url(home),
            "away_score": (g.get("awayTeam") or {}).get("score"),
            "home_score": (g.get("homeTeam") or {}).get("score"),
            "detail": state.title() if state else "", "live": state == "LIVE",
            "color": nteams.color_for_abbr(home),
        })
    return rows, None


def _nfl_games():
    if fdb is None:
        return [], None
    try:
        mtime = fdb.nfl_db_mtime()
        available = fdb.seasons(mtime)
        season = available[0] if available else None
        games = fdb.load_games(season, mtime) if season else pd.DataFrame()
    except Exception:
        return [], None
    if games.empty:
        return [], "No schedule loaded."
    today_games = games[games["gameday"].astype(str).str.startswith(TODAY.isoformat())]
    if today_games.empty:
        upcoming = games[games["gameday"].astype(str) > TODAY.isoformat()]
        if upcoming.empty:
            return [], "Season complete."
        nxt = upcoming.iloc[0]
        return [], (f"Kicks off {nxt['gameday']}", f"{nxt['away_team']} at {nxt['home_team']}")
    rows = []
    for _, g in today_games.iterrows():
        played = pd.notna(g.get("home_score"))
        rows.append({
            "away": g["away_team"], "home": g["home_team"],
            "away_logo": fteams.logo_url(g["away_team"]), "home_logo": fteams.logo_url(g["home_team"]),
            "away_score": int(g["away_score"]) if played else None,
            "home_score": int(g["home_score"]) if played else None,
            "detail": "Final" if played else str(g.get("gametime") or ""), "live": False,
            "color": fteams.color_for_abbr(g["home_team"]),
        })
    return rows, None


def _render_games(rows):
    """One card per game in the Today's-Games idiom: a rail in the home
    team's colour, logos, the winner promoted, a LIVE chip while play is
    on. Everything var(--dm-*) so both themes hold."""
    html = []
    for r in rows:
        a_s = "" if r["away_score"] is None else int(r["away_score"])
        h_s = "" if r["home_score"] is None else int(r["home_score"])
        a_win = a_s != "" and h_s != "" and a_s > h_s
        h_win = a_s != "" and h_s != "" and h_s > a_s

        def side(abbr, logo, score, won):
            img = (f"<img src='{logo}' style='width:18px;height:18px;object-fit:contain;"
                   f"flex-shrink:0' />" if logo else "")
            colour = "var(--dm-text)" if won or score == "" else "var(--dm-dim)"
            return (
                "<span style='display:flex;align-items:center;gap:6px;min-width:0'>"
                f"{img}<span style='font-family:\"Archivo Narrow\",sans-serif;font-weight:{700 if won else 600};"
                f"color:{colour}'>{abbr}</span>"
                f"<span style='font-family:\"Archivo Narrow\",sans-serif;font-weight:700;color:"
                f"{'var(--dm-blue)' if won else colour};margin-left:auto'>{score}</span></span>"
            )

        live_chip = ("<span style='background:var(--dm-red);color:#fff;font-size:0.56rem;"
                     "font-weight:800;letter-spacing:1px;padding:1px 6px;border-radius:999px'>LIVE</span> "
                     if r.get("live") else "")
        html.append(
            f"<div style='background:var(--dm-card);border-left:4px solid {r['color']};"
            f"border-radius:0 9px 9px 0;padding:8px 12px;margin-bottom:8px'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px'>"
            f"<span style='font-size:0.62rem;letter-spacing:1px;text-transform:uppercase;"
            f"color:var(--dm-dim)'>{live_chip}{r['detail']}</span></div>"
            f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'>"
            f"{side(r['away'], r['away_logo'], a_s, a_win)}"
            f"{side(r['home'], r['home_logo'], h_s, h_win)}"
            "</div></div>"
        )
    st.markdown("".join(html), unsafe_allow_html=True)


style.colored_header("Today", "headliners")
_sections = [("MLB", _mlb_games(), "Home.py"),
             ("NHL", _nhl_games(), "nhl/pages/home.py"),
             ("NFL", _nfl_games(), "nfl/pages/home.py")]
_cols = st.columns(3)
for _col, (_label, (_rows, _note), _target) in zip(_cols, _sections):
    with _col:
        st.markdown(
            f"<div style='font-family:\"Archivo Narrow\",sans-serif;font-weight:700;"
            f"letter-spacing:1px;color:var(--dm-text);margin-bottom:6px'>{_label}</div>",
            unsafe_allow_html=True,
        )
        if _rows:
            _render_games(_rows[:7])
            if len(_rows) > 7:
                st.caption(f"+{len(_rows) - 7} more")
        else:
            if isinstance(_note, tuple):
                st.markdown(
                    f"<div style='background:var(--dm-card);border-left:4px solid var(--dm-line);"
                    f"border-radius:0 9px 9px 0;padding:10px 12px'>"
                    f"<div style='font-size:0.62rem;letter-spacing:1px;text-transform:uppercase;"
                    f"color:var(--dm-dim)'>{_note[0]}</div>"
                    f"<div style='font-family:\"Archivo Narrow\",sans-serif;font-weight:700;"
                    f"color:var(--dm-text);margin-top:2px'>{_note[1]}</div></div>",
                    unsafe_allow_html=True,
                )
            else:
                st.caption(_note or "Nothing scheduled.")
        st.page_link(_target, label=f"Go to {_label} →")

st.caption("MLB and NHL scores update live. NFL results appear after games finish.")

# --- League leaders: a face per sport ---------------------------------------
def _leader_cards():
    cards = []
    try:
        rb = db.load_recent_batting(TODAY.year, MTIME)
        hot = db.top_recent_performer(rb, "day")
        if hot is not None:
            abbr = teams.team_meta_from_city(hot["Tm"], hot.get("Lev"))[0]
            cards.append({
                "sport": "MLB", "label": db.daily_label(db.data_as_of(MTIME)),
                "name": hot["Name"], "abbr": abbr, "color": teams.color_for_abbr(abbr),
                "photo": style.headshot_url(hot["mlbID"], width=240),
                "line": style.batting_day_stat_line(hot),
            })
    except Exception:
        pass
    try:
        if ndb is not None:
            nm = ndb.nhl_db_mtime()
            season = ndb.skater_seasons(nm)[0]
            top = ndb.load_skaters(season, nm).sort_values("points", ascending=False).iloc[0]
            abbr = nteams._primary(top["teamAbbrevs"])
            cards.append({
                "sport": "NHL", "label": f"{ndb.season_label(season)} points leader",
                "name": top["skaterFullName"], "abbr": abbr, "color": nteams.color_for_abbr(abbr),
                "photo": f"https://assets.nhle.com/mugs/nhl/{season}{season + 1}/{abbr}/{int(top['playerId'])}.png",
                "line": f"{int(top['goals'])} G · {int(top['assists'])} A · {int(top['points'])} P",
            })
    except Exception:
        pass
    try:
        if fdb is not None:
            fm = fdb.nfl_db_mtime()
            season = fdb.default_season(fm)
            depa = fdb.quarterback_depa(season, fm)
            if not depa.empty:
                top = depa.iloc[0]
                shot = fdb._read(
                    "SELECT headshot_url FROM player_season_stats WHERE player_id = ? "
                    "AND headshot_url IS NOT NULL LIMIT 1", (str(top["player_id"]),))
                cards.append({
                    "sport": "NFL", "label": f"{fdb.season_label(season)} dEPA leader",
                    "name": top["player_display_name"], "abbr": top["team"],
                    "color": fteams.color_for_abbr(top["team"]),
                    "photo": shot.iloc[0, 0] if not shot.empty else None,
                    "line": f"{top['dEPA']:+.3f} dEPA · {top['epa_att']:+.3f} EPA/Att",
                })
    except Exception:
        pass
    return cards


_cards = _leader_cards()
if _cards:
    style.colored_header("Leading the Leagues", "batting")
    _cols = st.columns(len(_cards))
    for _col, c in zip(_cols, _cards):
        with _col:
            photo = (f"<img src='{c['photo']}' style='width:84px;height:84px;border-radius:50%;"
                     f"object-fit:cover;object-position:center 18%;border:3px solid {c['color']};"
                     f"background:var(--dm-surface-mute);flex-shrink:0' />" if c.get("photo") else "")
            st.markdown(
                # The colour is a soft radial of the club's own shade behind
                # the face — the NFL last-game treatment, at card scale.
                f"<div style='background:radial-gradient(ellipse 90% 130% at 18% 30%,{c['color']}2E 0%,"
                f"transparent 70%),var(--dm-card);border:1px solid var(--dm-line);border-radius:12px;"
                f"padding:16px;display:flex;gap:14px;align-items:center'>"
                f"{photo}"
                f"<div style='min-width:0'>"
                f"<div style='font-size:0.62rem;letter-spacing:1.1px;text-transform:uppercase;"
                f"color:var(--dm-dim)'>{c['sport']} · {c['label']}</div>"
                f"<div style='font-family:\"Archivo Narrow\",sans-serif;font-weight:800;font-size:1.25rem;"
                f"color:var(--dm-text);margin:2px 0'>{c['name']} "
                f"<span style='background-color:{c['color']}66;color:var(--dm-text);padding:2px 8px;"
                f"border-radius:7px;font-size:0.62em;vertical-align:middle;font-weight:600'>{c['abbr']}</span></div>"
                f"<div style='color:var(--dm-green);font-weight:600;font-size:0.88rem'>{c['line']}</div>"
                "</div></div>",
                unsafe_allow_html=True,
            )

# --- Your teams --------------------------------------------------------------
_TEAM_META = {"MLB": (teams.color_for_abbr, _mlb_logo)}
if nteams is not None:
    _TEAM_META["NHL"] = (nteams.color_for_abbr, nteams.logo_url)
if fteams is not None:
    _TEAM_META["NFL"] = (fteams.color_for_abbr, fteams.logo_url)

_lists = following_page._lists()
_followed = [(label, v["teams"]) for label, v in _lists.items() if v["teams"]]
if _followed:
    style.colored_header("Your Teams", "batting")
    _chips = []
    for _label, _teams_list in _followed:
        colour_fn, logo_fn = _TEAM_META.get(_label, (None, None))
        for _t in _teams_list:
            _c = colour_fn(_t["abbr"]) if colour_fn else "#666666"
            _logo = logo_fn(_t["abbr"]) if logo_fn else None
            _img = (f"<img src='{_logo}' style='width:20px;height:20px;object-fit:contain' />"
                    if _logo else "")
            _chips.append(
                f"<span style='display:inline-flex;align-items:center;gap:8px;"
                f"background:var(--dm-card);border:1px solid var(--dm-line);"
                f"border-left:4px solid {_c};border-radius:0 9px 9px 0;padding:7px 13px'>"
                f"{_img}<span style='font-family:\"Archivo Narrow\",sans-serif;font-weight:700;"
                f"color:var(--dm-text)'>{_t['abbr']}</span>"
                f"<span style='color:var(--dm-dim);font-size:0.84rem'>{_t.get('nickname', '')}</span>"
                f"<span style='font-size:0.6rem;letter-spacing:0.8px;color:var(--dm-dim)'>{_label}</span></span>"
            )
    st.markdown(
        "<div style='display:flex;flex-wrap:wrap;gap:10px'>" + "".join(_chips) + "</div>",
        unsafe_allow_html=True,
    )
    st.page_link("views/13_Following.py", label="Manage who you follow →")
