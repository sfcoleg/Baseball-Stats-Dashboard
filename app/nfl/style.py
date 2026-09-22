"""NFL-specific presentation. Shared chrome (headers, stat tables) still
comes from app/style.py; this is the football-only furniture."""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import style

# nflverse serves these from its own repo, the same place the team logos come
# from, and all three are verified to resolve. There is no Super Bowl mark
# among them — hence the conference logos below, which are arguably the
# better answer anyway: that game IS the AFC champion against the NFC one.
LEAGUE_MARK = "https://raw.githubusercontent.com/nflverse/nflverse-pbp/master/NFL.png"
CONFERENCE_MARKS = {
    "AFC": "https://raw.githubusercontent.com/nflverse/nflverse-pbp/master/AFC.png",
    "NFC": "https://raw.githubusercontent.com/nflverse/nflverse-pbp/master/NFC.png",
}

# Deliberately built in the Today's Games language rather than as its own
# thing: a neutral card, a 4px rail in the team's colour, dim type with the
# winner promoted. The first version filled each half with a big field of
# team colour, which read as a graphic dropped onto the page instead of a
# component belonging to it.
LAST_GAME_CSS = """
<style>
.nlg-card{background:var(--dm-card);border-radius:0 12px 12px 0;
  border-left:4px solid var(--dm-blue);padding:0;overflow:hidden;}
.nlg-head{display:flex;align-items:center;gap:9px;flex-wrap:wrap;
  padding:11px 16px 9px;font-size:0.64rem;letter-spacing:1.1px;
  text-transform:uppercase;color:var(--dm-dim);}
.nlg-head b{color:var(--dm-text);font-weight:700;letter-spacing:1.1px;}
.nlg-mark{height:19px;width:auto;object-fit:contain;}
.nlg-rows{padding:0 16px 6px;}
/* One row per team, each with its own colour as a left rail — the same
   device the game cards use, at the row level so both clubs get one. */
.nlg-row{display:flex;align-items:center;gap:11px;padding:9px 0 9px 11px;
  border-left:4px solid var(--nlg-c);margin-bottom:7px;}
.nlg-logo{width:38px;height:38px;object-fit:contain;flex:0 0 auto;}
.nlg-conf{height:17px;width:auto;object-fit:contain;flex:0 0 auto;opacity:0.75;}
.nlg-id{display:flex;flex-direction:column;min-width:0;flex:1 1 auto;}
.nlg-abbr{font-family:'Archivo Narrow',sans-serif;font-weight:600;font-size:1rem;
  color:var(--dm-dim);letter-spacing:0.4px;}
.nlg-row.win .nlg-abbr{color:var(--dm-text);font-weight:700;}
.nlg-qb{font-size:0.72rem;color:var(--dm-dim);}
.nlg-score{font-family:'Archivo Narrow',sans-serif;font-weight:700;font-size:1.6rem;
  color:var(--dm-dim);flex:0 0 auto;}
.nlg-row.win .nlg-score{color:var(--dm-blue);}
.nlg-foot{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
  padding:2px 16px 12px;font-size:0.72rem;color:var(--dm-dim);}
.nlg-foot b{color:var(--dm-text);font-weight:700;}
@media (max-width:640px){.nlg-logo{width:30px;height:30px;}.nlg-score{font-size:1.3rem;}}
</style>
"""


# The week's slate as a card grid — MLB's Today's Games and the NHL home
# strip both use small colour-railed cards with a live/final/scheduled
# badge rather than a plain table, and this is the same idiom sized for a
# grid instead of a single row.
WEEK_GAMES_CSS = """
<style>
.wk-grid{display:grid;grid-template-columns:repeat(auto-fill, minmax(230px, 1fr));gap:10px;}
.wk-card{background:var(--dm-card);border-radius:10px;border-left:4px solid var(--wk-c);
  padding:10px 12px;}
.wk-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;}
.wk-meta{font-size:0.68rem;color:var(--dm-dim);}
.wk-live{background-color:var(--dm-red);color:#FFFFFF;padding:1px 8px;border-radius:6px;
  font-weight:700;font-size:0.66rem;letter-spacing:0.4px;}
.wk-final{color:var(--dm-dim);font-size:0.7rem;font-weight:600;}
.wk-row{display:flex;align-items:center;justify-content:space-between;padding:3px 0;}
.wk-team{display:flex;align-items:center;gap:7px;overflow:hidden;}
.wk-logo{width:22px;height:22px;object-fit:contain;flex:0 0 auto;}
.wk-abbr{font-size:0.86rem;white-space:nowrap;color:var(--dm-dim);}
.wk-row.win .wk-abbr{color:var(--dm-text);font-weight:700;}
.wk-score{font-weight:700;font-size:1rem;color:var(--dm-dim);flex:0 0 auto;margin-left:8px;}
.wk-row.win .wk-score{color:var(--dm-text);}
</style>
"""


def week_game_card(game: dict, live: dict | None, teams) -> str:
    """One card for the week's slate grid: logos, current/final score, and a
    LIVE badge with quarter/clock when ESPN has an in-progress state for it.
    `live` is one entry from db.load_live_scores(), or None/empty when the
    game hasn't been matched to a live event (bye-week bug, off-week, etc)."""
    away, home = game["away_team"], game["home_team"]
    live = live or {}
    state = live.get("state")  # "pre" | "in" | "post" | None (no live match)
    is_live = state == "in"
    is_final = state == "post" or (state is None and bool(game.get("played")))
    started = is_live or is_final

    if state in ("in", "post"):
        # ESPN scores are "0", never null, even for a game that hasn't
        # kicked off — only trust them once ESPN itself says the game is
        # live or over, otherwise every upcoming game would read "0 – 0"
        # instead of its kickoff time.
        away_score, home_score = live.get("away_score"), live.get("home_score")
    elif state is None and game.get("played"):
        away_score, home_score = int(game["away_score"]), int(game["home_score"])
    else:
        away_score = home_score = None

    if is_live:
        detail = live.get("detail") or (f"Q{live['period']} {live.get('clock') or ''}".strip() if live.get("period") else "")
        status_html = f"<span class='wk-live'>LIVE</span><span class='wk-meta'> {detail}</span>"
    elif is_final:
        status_html = "<span class='wk-final'>Final</span>"
    else:
        status_html = f"<span class='wk-meta'>{game.get('weekday') or ''} {game.get('gametime') or ''}</span>"

    away_win = started and away_score > home_score
    home_win = started and home_score > away_score

    def row(abbr, score, won):
        logo = teams.logo_url(abbr)
        img = f"<img class='wk-logo' src='{logo}' alt='{abbr}' />" if logo else ""
        score_txt = score if started else "—"
        return (
            f"<div class='wk-row{' win' if won else ''}'>"
            f"<div class='wk-team'>{img}<span class='wk-abbr'>{abbr}</span></div>"
            f"<span class='wk-score'>{score_txt}</span></div>"
        )

    rail_color = teams.color_for_abbr(home if home_win else away)
    return (
        f"<div class='wk-card' style='--wk-c:{rail_color}'>"
        f"<div class='wk-head'>{status_html}</div>"
        + row(away, away_score, away_win)
        + row(home, home_score, home_win)
        + "</div>"
    )


def _pretty_date(value) -> str:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").strftime("%b %-d, %Y")
    except (ValueError, TypeError):
        return str(value or "")


def last_game_card(game: dict, round_label: str, teams) -> str:
    """A scoreboard card for one finished game, in the site's game-card
    idiom. `teams` is the nfl.teams module, passed in rather than imported
    so this stays a pure formatting function."""
    away, home = game["away_team"], game["home_team"]
    away_score, home_score = int(game["away_score"]), int(game["home_score"])
    kind = game.get("game_type") or "REG"
    is_super_bowl = kind == "SB"

    def row(abbr: str, score: int, won: bool, qb) -> str:
        logo = teams.logo_url(abbr)
        img = f"<img class='nlg-logo' src='{logo}' alt='{abbr}' />" if logo else ""
        # Only in the Super Bowl, where "AFC champion vs NFC champion" is the
        # whole framing. On any other game the conference is noise.
        conf = teams.conference_for_abbr(abbr) if is_super_bowl else ""
        conf_img = (
            f"<img class='nlg-conf' src='{CONFERENCE_MARKS[conf]}' alt='{conf}' />"
            if conf in CONFERENCE_MARKS else ""
        )
        qb_line = f"<span class='nlg-qb'>{qb}</span>" if qb and pd.notna(qb) else ""
        return (
            f"<div class='nlg-row{' win' if won else ''}' "
            f"style='--nlg-c:{teams.color_for_abbr(abbr)}'>"
            f"{img}{conf_img}"
            f"<span class='nlg-id'><span class='nlg-abbr'>{abbr} "
            f"{teams.nickname_for_abbr(abbr)}</span>{qb_line}</span>"
            f"<span class='nlg-score'>{score}</span>"
            "</div>"
        )

    head = []
    if kind != "REG":
        head.append(f"<img class='nlg-mark' src='{LEAGUE_MARK}' alt='NFL' />")
    head.append(f"<b>{round_label}</b>")
    head.append(f"<span>{_pretty_date(game.get('gameday'))}</span>")
    if game.get("stadium"):
        head.append(f"<span>{game['stadium']}</span>")
    head.append(f"<span>Final{' / OT' if game.get('overtime') else ''}</span>")

    foot = []
    for side, abbr in (("away_coach", away), ("home_coach", home)):
        coach = game.get(side)
        if coach and pd.notna(coach):
            foot.append(f"<span>{abbr} <b>{coach}</b></span>")
    total = game.get("total")
    if total is not None and pd.notna(total):
        foot.append(f"<span>Total <b>{int(total)}</b></span>")

    return (
        "<div class='nlg-card'>"
        f"<div class='nlg-head'>{''.join(head)}</div>"
        "<div class='nlg-rows'>"
        + row(away, away_score, away_score > home_score, game.get("away_qb_name"))
        + row(home, home_score, home_score > away_score, game.get("home_qb_name"))
        + "</div>"
        + (f"<div class='nlg-foot'>{''.join(foot)}</div>" if foot else "")
        + "</div>"
    )
