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
.nlg-card{border-radius:20px;overflow:hidden;border:1px solid var(--dm-line);
  background:var(--dm-surface);box-shadow:0 2px 10px rgba(12,23,37,0.08);}
.nlg-head{display:flex;align-items:center;justify-content:center;gap:10px;
  flex-wrap:wrap;padding:11px 14px 9px;
  font-family:'Archivo Narrow',sans-serif;font-weight:700;letter-spacing:0.8px;
  text-transform:uppercase;font-size:0.78rem;color:var(--dm-dim);}
.nlg-title{color:var(--dm-text);font-size:0.95rem;letter-spacing:1px;}
.nlg-body{display:grid;grid-template-columns:1fr auto 1fr;align-items:stretch;}
.nlg-side{padding:26px 14px 30px;text-align:center;display:flex;
  flex-direction:column;align-items:center;gap:7px;min-width:0;}
/* The team's colour as a wash rather than a fill: a solid panel would force
   every label onto a different text colour per team, and half the league's
   colours are dark enough to swallow a logo. */
/* Each side is FILLED with its club's colour, shaded slightly across the
   panel for depth. Everything sitting on it — score, abbreviation, name —
   takes whichever of black or white actually contrasts with that fill, so
   the treatment works for Green Bay's dark green and Miami's aqua alike
   instead of only for one half of the league. */
/* Radial, not rectangular. Two solid panels meeting at a straight seam read
   as boxes with a line down the middle; a soft orb of colour behind each
   club has no edges of its own, so the card looks like one object rather
   than three stacked rectangles. Each orb is pushed outward so the two
   fade into the card between them instead of meeting. */
/* The orb has to be SMALLER than its panel, or it paints into the corners
   and the panel is a rectangle again — which is what made the first pass
   still look boxy despite being a radial gradient. Inset like this, all four
   corners fade to the card and the colour reads as a soft field behind the
   team rather than as a filled box. */
.nlg-side.away{background:radial-gradient(ellipse 74% 78% at 50% 44%,
  var(--nlg-solid) 0%,var(--nlg-shade) 38%,transparent 72%);}
.nlg-side.home{background:radial-gradient(ellipse 74% 78% at 50% 44%,
  var(--nlg-solid) 0%,var(--nlg-shade) 38%,transparent 72%);}
/* Logos are drawn for their own colour and vanish against it — Seattle's
   navy crest on Seattle navy is invisible. A pale disc behind every one
   guarantees the mark reads on any of the 32 fills. */
.nlg-logo{width:92px;height:92px;object-fit:contain;padding:9px;border-radius:50%;
  background:rgba(255,255,255,0.94);box-shadow:0 3px 10px rgba(0,0,0,0.28);}
.nlg-abbr{font-family:'Archivo Narrow',sans-serif;font-weight:800;font-size:1.1rem;
  letter-spacing:1.2px;color:var(--nlg-ink);}
.nlg-name{font-size:0.78rem;color:var(--nlg-ink);opacity:0.78;margin-top:-4px;}
.nlg-score{font-family:'Archivo Narrow',sans-serif;font-weight:800;font-size:3.1rem;
  line-height:1;color:var(--nlg-ink);letter-spacing:-1px;
  text-shadow:0 2px 6px rgba(0,0,0,0.22);}
/* The loser is dimmed rather than the winner being highlighted — one final
   score is easier to read when one side visibly recedes. */
.nlg-side.lost{filter:saturate(0.55) brightness(0.92);}
.nlg-side.lost .nlg-score,.nlg-side.lost .nlg-abbr{opacity:0.72;}
.nlg-side.lost .nlg-logo{opacity:0.7;}
/* The badge borrows the panel's own ink so it stays legible on every fill. */
.nlg-win{display:inline-block;font-size:0.62rem;font-weight:800;letter-spacing:1px;
  padding:1px 8px;border-radius:999px;border:1.5px solid var(--nlg-ink);
  color:var(--nlg-ink);}
.nlg-mid{display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:6px;padding:0 6px;color:var(--dm-dim);font-family:'Archivo Narrow',sans-serif;
  font-weight:700;letter-spacing:1px;font-size:0.72rem;}
.nlg-dash{font-size:1.4rem;opacity:0.35;line-height:1;}
.nlg-foot{display:flex;justify-content:space-between;gap:12px;padding:6px 18px 12px;
  font-size:0.76rem;color:var(--dm-dim);}
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


# Below this contrast ratio the two fills read as one slab rather than as two
# teams. 1.6 is deliberately low: it only catches genuine collisions (navy on
# navy, black on black) and leaves merely-similar pairs alone.
_FILL_COLLISION = 1.6


def _distinct_fills(away: str, home: str, teams) -> tuple[str, str]:
    """One colour per side, guaranteed to be tellable apart.

    Several clubs share a primary — Las Vegas and Pittsburgh are both black,
    Seattle and New England both navy — and a card whose halves are the same
    colour stops being a scoreboard. When that happens the HOME team falls
    back to its secondary (Pittsburgh gold, New England red), which is still
    genuinely its own colour rather than an invented one. If the secondary
    collides too, the away side is nudged instead."""
    away_fill = teams.color_for_abbr(away)
    home_fill = teams.color_for_abbr(home)
    if style.contrast_ratio(away_fill, home_fill) >= _FILL_COLLISION:
        return away_fill, home_fill

    home_alt = teams.secondary_for_abbr(home)
    if home_alt and style.contrast_ratio(away_fill, home_alt) >= _FILL_COLLISION:
        return away_fill, home_alt

    away_alt = teams.secondary_for_abbr(away)
    if away_alt and style.contrast_ratio(away_alt, home_fill) >= _FILL_COLLISION:
        return away_alt, home_fill
    return away_fill, home_fill


def last_game_card(game: dict, round_label: str, teams) -> str:
    """A scoreboard card for one finished game: logos, colours, final score.

    `teams` is the nfl.teams module, passed in rather than imported so this
    stays a pure formatting function."""
    away, home = game["away_team"], game["home_team"]
    away_score, home_score = int(game["away_score"]), int(game["home_score"])
    away_won, home_won = away_score > home_score, home_score > away_score

    away_fill, home_fill = _distinct_fills(away, home, teams)

    def side(abbr: str, score: int, won: bool, other_won: bool, css_class: str, qb) -> str:
        colour = away_fill if css_class == "away" else home_fill
        logo = teams.logo_url(abbr)
        # Black or white, whichever actually contrasts with THIS club's fill.
        # Half the league is dark enough to need white and half is light
        # enough to need black, so a single hardcoded ink would fail for one
        # of them — the same WCAG helper the team badges use.
        ink = style.readable_text_color(colour)
        # A darker second stop gives the panel some depth. CC is ~80% alpha
        # over the card, which reads as a shade of the same colour rather
        # than as a different one.
        shade = f"{colour}CC"
        badge = "<span class='nlg-win'>WIN</span>" if won else ""
        img = f"<img class='nlg-logo' src='{logo}' alt='{abbr}' />" if logo else ""
        return (
            f"<div class='nlg-side {css_class}{' lost' if other_won else ''}' "
            f"style='--nlg-solid:{colour};--nlg-shade:{shade};--nlg-ink:{ink}'>"
            f"{img}"
            f"<div class='nlg-abbr'>{abbr} {badge}</div>"
            f"<div class='nlg-name'>{teams.nickname_for_abbr(abbr)}</div>"
            f"<div class='nlg-score'>{score}</div>"
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
        + "<div class='nlg-mid'>"
          f"<span>FINAL{' / OT' if overtime else ''}</span></div>"
        + side(home, home_score, home_won, away_won, "home", game.get("home_qb_name"))
        + "</div>"
        + (f"<div class='nlg-foot'>{''.join(foot_bits)}</div>" if foot_bits else "")
        + "</div>"
    )
