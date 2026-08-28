"""NFL-specific presentation. Shared chrome (headers, stat tables) still
comes from app/style.py; this is the football-only furniture."""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import style

LAST_GAME_CSS = """
<style>
.nlg-card{border-radius:14px;overflow:hidden;border:1px solid var(--dm-line);
  background:var(--dm-surface);box-shadow:0 1px 2px rgba(12,23,37,0.06);}
.nlg-head{display:flex;align-items:center;justify-content:center;gap:10px;
  flex-wrap:wrap;padding:9px 14px;border-bottom:1px solid var(--dm-line);
  font-family:'Archivo Narrow',sans-serif;font-weight:700;letter-spacing:0.8px;
  text-transform:uppercase;font-size:0.78rem;color:var(--dm-dim);}
.nlg-title{color:var(--dm-text);font-size:0.95rem;letter-spacing:1px;}
.nlg-body{display:grid;grid-template-columns:1fr auto 1fr;align-items:stretch;}
.nlg-side{padding:20px 14px 16px;text-align:center;display:flex;
  flex-direction:column;align-items:center;gap:6px;min-width:0;}
/* The team's colour as a wash rather than a fill: a solid panel would force
   every label onto a different text colour per team, and half the league's
   colours are dark enough to swallow a logo. */
/* Each side carries a solid bar of the team's own colour along the top, then
   fades that colour down across the panel. The bar is what actually reads as
   "this team's colour" — a wash alone is too faint to register once it is
   pale enough to keep text legible on top of it. */
.nlg-side{border-top:5px solid var(--nlg-solid);}
.nlg-side.away{background:linear-gradient(165deg,var(--nlg-c) 0%,transparent 72%);}
.nlg-side.home{background:linear-gradient(195deg,var(--nlg-c) 0%,transparent 72%);}
.nlg-logo{width:96px;height:96px;object-fit:contain;filter:drop-shadow(0 3px 6px rgba(0,0,0,0.22));}
.nlg-abbr{font-family:'Archivo Narrow',sans-serif;font-weight:800;font-size:1.05rem;
  letter-spacing:1.2px;color:var(--dm-text);}
.nlg-name{font-size:0.76rem;color:var(--dm-dim);margin-top:-4px;}
.nlg-score{font-family:'Archivo Narrow',sans-serif;font-weight:800;font-size:2.9rem;
  line-height:1;color:var(--dm-text);letter-spacing:-1px;}
/* The loser is dimmed rather than the winner being highlighted — one final
   score is easier to read when one side visibly recedes. */
.nlg-side.lost .nlg-score,.nlg-side.lost .nlg-abbr{opacity:0.55;}
.nlg-side.lost .nlg-logo{opacity:0.45;filter:grayscale(0.35);}
.nlg-win{display:inline-block;font-size:0.62rem;font-weight:800;letter-spacing:1px;
  padding:1px 7px;border-radius:999px;background:var(--dm-blue);color:#fff;}
.nlg-mid{display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:6px;padding:0 6px;color:var(--dm-dim);font-family:'Archivo Narrow',sans-serif;
  font-weight:700;letter-spacing:1px;font-size:0.72rem;}
.nlg-dash{font-size:1.4rem;opacity:0.35;line-height:1;}
.nlg-foot{display:flex;justify-content:space-between;gap:12px;padding:9px 16px;
  border-top:1px solid var(--dm-line);font-size:0.76rem;color:var(--dm-dim);}
.nlg-foot span b{color:var(--dm-text);font-weight:700;}
@media (max-width:640px){
  .nlg-body{grid-template-columns:1fr auto 1fr;}
  .nlg-logo{width:54px;height:54px;}
  .nlg-score{font-size:2rem;}
  .nlg-foot{flex-direction:column;gap:4px;}
}
</style>
"""


def _pretty_date(value) -> str:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").strftime("%b %-d, %Y")
    except (ValueError, TypeError):
        return str(value or "")


def last_game_card(game: dict, round_label: str, teams) -> str:
    """A scoreboard card for one finished game: logos, colours, final score.

    `teams` is the nfl.teams module, passed in rather than imported so this
    stays a pure formatting function."""
    away, home = game["away_team"], game["home_team"]
    away_score, home_score = int(game["away_score"]), int(game["home_score"])
    away_won, home_won = away_score > home_score, home_score > away_score

    def side(abbr: str, score: int, won: bool, other_won: bool, css_class: str, qb) -> str:
        colour = teams.color_for_abbr(abbr)
        logo = teams.logo_url(abbr)
        # 3D is ~24% alpha for the wash; the top bar uses the colour at full
        # strength. Splitting it that way keeps the panel light enough for
        # var(--dm-text) to stay readable while the team still reads clearly.
        badge = "<span class='nlg-win'>WIN</span>" if won else ""
        img = f"<img class='nlg-logo' src='{logo}' alt='{abbr}' />" if logo else ""
        return (
            f"<div class='nlg-side {css_class}{' lost' if other_won else ''}' "
            f"style='--nlg-c:{colour}3D;--nlg-solid:{colour}'>"
            f"{img}"
            f"<div class='nlg-abbr'>{abbr} {badge}</div>"
            f"<div class='nlg-name'>{teams.nickname_for_abbr(abbr)}</div>"
            f"<div class='nlg-score' style='color:{style.team_text_color(colour)}'>{score}</div>"
            + (f"<div class='nlg-name'>{qb}</div>" if qb else "")
            + "</div>"
        )

    overtime = bool(game.get("overtime"))
    venue = str(game.get("stadium") or "")
    head_bits = [f"<span class='nlg-title'>{round_label}</span>"]
    head_bits.append(f"<span>{_pretty_date(game.get('gameday'))}</span>")
    if venue:
        head_bits.append(f"<span>{venue}</span>")

    foot_bits = []
    for label, key in (("Away", "away_coach"), ("Home", "home_coach")):
        coach = game.get(key)
        if coach and pd.notna(coach):
            abbr = away if label == "Away" else home
            foot_bits.append(f"<span>{abbr} <b>{coach}</b></span>")
    total = game.get("total")
    if total is not None and pd.notna(total):
        foot_bits.append(f"<span>Total <b>{int(total)}</b></span>")

    return (
        "<div class='nlg-card'>"
        f"<div class='nlg-head'>{''.join(head_bits)}</div>"
        "<div class='nlg-body'>"
        + side(away, away_score, away_won, home_won, "away", game.get("away_qb_name"))
        + "<div class='nlg-mid'><span class='nlg-dash'>—</span>"
          f"<span>FINAL{' / OT' if overtime else ''}</span></div>"
        + side(home, home_score, home_won, away_won, "home", game.get("home_qb_name"))
        + "</div>"
        + (f"<div class='nlg-foot'>{''.join(foot_bits)}</div>" if foot_bits else "")
        + "</div>"
    )
