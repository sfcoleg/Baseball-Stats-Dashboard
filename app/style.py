"""Reusable pandas Styler helpers for dashboard tables: color-coded stat
columns (green = better, red = worse) and team-color badges."""
import base64
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Category accent colors, used to visually distinguish sections throughout
# the dashboard (Batting/Pitching/Fielding headers, etc.)
def headshot_url(mlbID, width=180):
    """MLB's public headshot CDN, keyed by mlbID. Falls back to a generic
    silhouette (via Cloudinary's `d_` default-image param) when a player
    doesn't have a photo on file, so this never 404s."""
    return (
        "https://img.mlbstatic.com/mlb-photos/image/upload/"
        f"d_people:generic:headshot:67:current.png/w_{width},q_auto:best/"
        f"v1/people/{int(mlbID)}/headshot/67/current"
    )


def team_logo_url(team_id: int) -> str:
    """MLB's public team-logo CDN, keyed by team_id (see teams.team_id_for_abbr).
    Only ever serves each team's CURRENT logo — see team_logo_for_season()
    for season-correct historical logos."""
    return f"https://www.mlbstatic.com/team-logos/{int(team_id)}.svg"


_LOGO_ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "team_logos"

# Historical logo overrides for teams whose design has changed since 2010 —
# the live CDN (team_logo_url) only has each team's CURRENT logo, so a past
# era needs a local static asset instead. (abbr -> [(start_season,
# end_season_or_None, filename), ...]); a season with no matching entry
# falls through to the live CDN. Files live in assets/team_logos/, named
# "{abbr}_{start_season}.png" to match the entry below.
_HISTORICAL_LOGOS = {
    "ARI": [(2010, 2015, "ARI_2010.png"), (2016, 2023, "ARI_2016.png")],
    "HOU": [(2010, 2012, "HOU_2010.png")],
    "MIA": [(2010, 2011, "MIA_2010.png"), (2012, 2016, "MIA_2012.png"), (2017, 2018, "MIA_2017.png")],
    "TOR": [(2010, 2011, "TOR_2010.png"), (2012, 2019, "TOR_2012.png")],
}


def team_logo_for_season(abbr: str, team_id: int, season: int | None) -> str:
    """Season-correct team logo: a historical override (see
    _HISTORICAL_LOGOS) if this team/season has one, embedded as a base64
    data URI since it's a local file; otherwise the live CDN's current
    logo (team_logo_url)."""
    if season is not None:
        for start, end, filename in _HISTORICAL_LOGOS.get(abbr, []):
            if season >= start and (end is None or season <= end):
                data = base64.b64encode((_LOGO_ASSETS_DIR / filename).read_bytes()).decode()
                return f"data:image/png;base64,{data}"
    return team_logo_url(team_id)


ACCENT = "#3B82F6"

# The gemstone-diamond logo's main facet color — also used to color the
# Home page title text (see Home.py), so the two stay in sync if this ever
# changes rather than needing the hex repeated in two places.
DIAMOND_COLOR = "#93C5FD"


def diamond_logo(size=64):
    """A small faceted-gemstone SVG (a literal diamond, not a baseball
    diamond) — brilliant-cut top view: a hexagonal crown facet, four
    pavilion facets shaded from light to dark for a 3D-ish look, dark
    outlines for the facet edges, and a white highlight streak for shine."""
    return f"""
    <svg width="{size}" height="{size}" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
        <polygon points="30,20 70,20 85,35 15,35" fill="#BFE0FF" />
        <polygon points="15,35 50,90 30,20" fill="{DIAMOND_COLOR}" />
        <polygon points="85,35 50,90 70,20" fill="#7DB8F5" />
        <polygon points="15,35 85,35 50,90" fill="{ACCENT}" />
        <g stroke="#1E3A66" stroke-width="1.5" stroke-linejoin="round">
            <line x1="30" y1="20" x2="15" y2="35" />
            <line x1="70" y1="20" x2="85" y2="35" />
            <line x1="15" y1="35" x2="85" y2="35" />
            <line x1="30" y1="20" x2="50" y2="90" />
            <line x1="70" y1="20" x2="50" y2="90" />
            <line x1="15" y1="35" x2="50" y2="90" />
            <line x1="85" y1="35" x2="50" y2="90" />
            <polygon points="30,20 70,20 85,35 15,35" fill="none" />
        </g>
        <polygon points="35,23 45,23 39,31" fill="#FFFFFF" opacity="0.65" />
        <polygon points="30,20 70,20 85,35 50,90 15,35" fill="none"
            stroke="#FFFFFF" stroke-width="2.5" stroke-linejoin="round" />
    </svg>
    """


# All section headers share one accent color now (see colored_header) rather
# than a different hue per category — kept as a dict (not a bare constant)
# so existing colored_header(..., category) call sites don't need to change.
CATEGORY_COLORS = {
    "batting": ACCENT,
    "pitching": ACCENT,
    "fielding": ACCENT,
    "headliners": ACCENT,
    "chart": ACCENT,
}


def colored_header(text, category, color=None):
    """A subheader with a colored left accent bar, keyed by CATEGORY_COLORS
    — or `color` (a hex string) to override it, e.g. tinting toward a
    player's own team color on their profile page."""
    color = color or CATEGORY_COLORS.get(category, ACCENT)
    st.markdown(
        f"<h3 style='border-left: 5px solid {color}; padding-left: 14px; "
        f"margin-top: 1.2em; margin-bottom: 0.6em;'>{text}</h3>",
        unsafe_allow_html=True,
    )


def batting_day_stat_line(row) -> str:
    """One-game batting stat line for the Home page's "Hot Yesterday" card
    and the Daily Digest's Top Batting Performances — H/HR/RBI always
    shown, 2B/3B/SB only when the player actually did them (no padding a
    single-and-a-walk game with "0 2B, 0 3B, 0 SB"), and Total Bases only
    when it's actually a notable total (>10) rather than just double-
    counting H/HR for an ordinary game."""
    tb = int(row["H"] + row["2B"] + 2 * row["3B"] + 3 * row["HR"])
    parts = []
    if tb > 10:
        parts.append(f"{tb} TB")
    parts.append(f"{int(row['H'])} H")
    if int(row.get("2B") or 0) > 0:
        parts.append(f"{int(row['2B'])} 2B")
    if int(row.get("3B") or 0) > 0:
        parts.append(f"{int(row['3B'])} 3B")
    parts.append(f"{int(row['HR'])} HR")
    parts.append(f"{int(row['RBI'])} RBI")
    if int(row.get("SB") or 0) > 0:
        parts.append(f"{int(row['SB'])} SB")
    return ", ".join(parts)


def pitching_day_stat_line(row) -> str:
    """One-game pitching stat line for the Home page's "Hot Yesterday" card
    and the Daily Digest's Top Pitching Performances — earned runs, hits
    allowed, and strikeouts, in place of the old Game Score/ERA line."""
    return f"{int(row['ER'])} ER, {int(row['H'])} H, {int(row['SO'])} K ({row['IP']:.1f} IP)"


def headliner_card(label, name, team_abbr, team_color, stat_line, mlbID=None):
    """A stat card with a headshot (photo left, name/badge/stat stacked
    right) — mirrors milestone_card's layout. Shows the FULL player name
    (st.metric truncates long values with an ellipsis, which cuts off names
    like 'Heriberto Hernández'). `mlbID` is optional since the rare
    hardcoded Home page overrides (see HOT_YESTERDAY_OVERRIDES) have no
    real player behind them — falls back to a photo-less layout then."""
    st.caption(label)
    name_html = (
        f"<div style='font-size:1.4rem;font-weight:700;line-height:1.3;overflow-wrap:break-word'>{name} "
        f"<span style='background-color:{team_color}66;color:#FAFAFA;padding:2px 9px;"
        f"border-radius:8px;font-size:0.65em;vertical-align:middle;font-weight:600'>{team_abbr}</span></div>"
    )
    stat_html = (
        f"<div style='margin-top:6px;margin-bottom:12px'><span style='background-color:#2e7d3244;"
        f"color:#7CFC9A;padding:3px 10px;border-radius:8px;font-weight:600;font-size:0.9rem'>"
        f"&uarr; {stat_line}</span></div>"
    )
    if mlbID is not None:
        st.markdown(
            f"<div style='display:flex;align-items:flex-start;gap:12px'>"
            f"<img src='{headshot_url(mlbID, width=180)}' style='width:56px;height:56px;"
            f"border-radius:10px;object-fit:cover;object-position:center 25%;flex-shrink:0' />"
            f"<div style='flex:1;min-width:0'>{name_html}{stat_html}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(name_html + stat_html, unsafe_allow_html=True)


def milestone_card(mlbID, name, team_abbr, team_color, text):
    """Photo on the left, name/badge + the achievement stacked to its
    right, for the Home page's Milestones section."""
    st.markdown(
        f"<div style='display:flex;align-items:flex-start;gap:12px;margin-bottom:20px'>"
        f"<img src='{headshot_url(mlbID, width=180)}' style='width:80px;height:80px;"
        f"border-radius:10px;object-fit:cover;object-position:center 25%;flex-shrink:0' />"
        f"<div style='flex:1;min-width:0'>"
        f"<div style='font-size:1.1rem;font-weight:700;line-height:1.3;overflow-wrap:break-word'>{name} "
        f"<span style='background-color:{team_color}66;color:#FAFAFA;padding:2px 9px;"
        f"border-radius:8px;font-size:0.65em;vertical-align:middle;font-weight:600'>{team_abbr}</span>"
        f"</div>"
        f"<div style='margin-top:6px;'><span style='background-color:#3B4A8244;"
        f"color:#B9C4FF;padding:3px 10px;border-radius:8px;font-weight:600;font-size:0.9rem'>"
        f"{text}</span></div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def milestone_achieved_card(mlbID, name, team_abbr, team_color, text):
    """Same layout as milestone_card, but with a gold border/glow and a
    celebratory badge instead of the plain blue one — for a player who
    actually crossed a milestone recently (see db.recent_milestone_achievers),
    as opposed to one who's just getting close."""
    st.markdown(
        f"<div style='display:flex;align-items:flex-start;gap:12px;background-color:#F5B94214;"
        f"border:1px solid #F5B94266;border-radius:12px;padding:10px;margin-bottom:20px'>"
        f"<img src='{headshot_url(mlbID, width=180)}' style='width:80px;height:80px;"
        f"border-radius:10px;object-fit:cover;object-position:center 25%;flex-shrink:0;border:2px solid #F5B942' />"
        f"<div style='flex:1;min-width:0'>"
        f"<div style='font-size:1.1rem;font-weight:700;line-height:1.3;overflow-wrap:break-word'>{name} "
        f"<span style='background-color:{team_color}66;color:#FAFAFA;padding:2px 9px;"
        f"border-radius:8px;font-size:0.65em;vertical-align:middle;font-weight:600'>{team_abbr}</span>"
        f"</div>"
        f"<div style='margin-top:6px;'><span style='background-color:#F5B94233;"
        f"color:#F5B942;padding:3px 10px;border-radius:8px;font-weight:700;font-size:0.9rem'>"
        f"\U0001f389 {text}</span></div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


_ON_THIS_DAY_KIND_COLORS = {
    "Cycle": "#3B82F6", "3+ HR": "#F5B942", "5+ Hits": "#7CFC9A",
    "No-Hitter": "#F87171", "Perfect Game": "#C084FC",
}


def on_this_day_highlight_card(h: dict) -> str:
    """One player milestone from db.load_on_this_day's `highlights` list
    (cycle, 3+ HR game, 5+ hit game, no-hitter, perfect game) as an HTML
    card matching the "On This Day" game cards' visual language. Batting
    milestones get a headshot (real mlbID); a combined no-hitter/perfect
    game has no single mlbID, so those render without one."""
    color = _ON_THIS_DAY_KIND_COLORS.get(h["kind"], "#3B82F6")
    photo_html = (
        f"<img src='{headshot_url(h['mlbID'], width=90)}' style='width:44px;height:44px;"
        f"border-radius:8px;object-fit:cover;object-position:center 25%;flex-shrink:0;margin-right:12px' />"
        if h.get("mlbID") else ""
    )
    return (
        f"<div style='display:flex;align-items:center;background-color:#1B243866;"
        f"border-left:4px solid {color};padding:8px 14px;border-radius:6px;margin:4px 0'>"
        f"{photo_html}"
        f"<div style='flex:1;min-width:0'>"
        f"<span style='color:#9AA3B5;font-size:0.85rem'>{h['years_ago']} year{'s' if h['years_ago'] != 1 else ''} ago ({h['year']})</span>"
        f"<span style='background-color:{color}33;color:{color};padding:2px 8px;border-radius:6px;"
        f"font-weight:700;font-size:0.75rem;margin-left:8px'>{h['kind']}</span>"
        f"<div style='color:#DCE1EA'><b>{h['player']}</b> ({h['team']}) — {h['text']}</div>"
        f"</div></div>"
    )


def box_score_table(linescore: dict, away_abbr: str, home_abbr: str, away_color: str, home_color: str) -> str:
    """Traditional scoreboard-style box score: one row per team, one column
    per inning, R/H/E totals set off with a heavier left border — the same
    layout as the scoreboard at an actual ballpark, rather than a plain
    innings-as-rows dataframe."""
    innings = linescore.get("innings", [])
    totals = linescore.get("teams", {})
    away_totals, home_totals = totals.get("away", {}), totals.get("home", {})

    def inning_cell(inning, side):
        val = inning.get(side, {}).get("runs")
        return "X" if val is None else str(int(val))

    def team_row(abbr, color, side, side_totals):
        cells = "".join(
            f"<td style='padding:5px 12px;text-align:center;font-variant-numeric:tabular-nums'>{inning_cell(i, side)}</td>"
            for i in innings
        )
        totals_cells = "".join(
            f"<td style='padding:5px 14px;text-align:center;font-weight:700;font-variant-numeric:tabular-nums;"
            f"{'border-left:2px solid #4A5266;' if stat == 'runs' else ''}'>{side_totals.get(stat, '—')}</td>"
            for stat in ("runs", "hits", "errors")
        )
        return (
            "<tr style='border-top:1px solid #4A5266'>"
            f"<td style='padding:5px 10px;white-space:nowrap'><span style='background-color:{color}66;"
            f"color:#FAFAFA;padding:2px 9px;border-radius:6px;font-weight:700'>{abbr}</span></td>"
            f"{cells}{totals_cells}</tr>"
        )

    inning_headers = "".join(
        f"<th style='padding:5px 12px;text-align:center;color:#9AA3B5;font-weight:600'>{i['num']}</th>"
        for i in innings
    )
    totals_headers = "".join(
        f"<th style='padding:5px 14px;text-align:center;color:#9AA3B5;font-weight:600;"
        f"{'border-left:2px solid #4A5266;' if h == 'R' else ''}'>{h}</th>"
        for h in ("R", "H", "E")
    )
    return (
        "<table style='width:100%;border-collapse:collapse'>"
        f"<thead><tr><th style='padding:5px 10px'></th>{inning_headers}{totals_headers}</tr></thead>"
        "<tbody>"
        f"{team_row(away_abbr, away_color, 'away', away_totals)}"
        f"{team_row(home_abbr, home_color, 'home', home_totals)}"
        "</tbody></table>"
    )


def game_state_html(status_line: str, bases: dict, outs) -> str:
    """The inning line, a small rotated-square-corner diamond (filled
    corner = runner on that base), and filled/empty out-dots — the same
    compact "mini diamond" convention most scoreboard apps use. All three
    rows share ONE flex column with a single `gap`, so the inning-to-diamond
    distance and the diamond-to-dots distance are identical by construction
    rather than one coming from st.caption's own margin and the other from
    a separate div (which drifted out of sync before). `bases` is
    {"first"/"second"/"third": bool} (see db.load_live_scores); `outs` is
    an int 0-3 or None if the game isn't actually in progress (in which
    case only the status line renders, no diamond/dots)."""
    GAP = 6  # px — the single source of truth both rows below are spaced by
    status_html = f"<div style='color:#9AA3B5;font-size:0.85rem'>{status_line}</div>"
    if outs is None:
        return f"<div style='display:flex;flex-direction:column;align-items:center;gap:{GAP}px'>{status_html}</div>"

    on = "#F5B942"
    off = "#4A5266"

    def corner(top, left, occupied):
        return (
            f"<div style='position:absolute;top:{top}px;left:{left}px;width:10px;height:10px;"
            f"transform:rotate(45deg);background-color:{occupied and on or off}'></div>"
        )

    diamond = (
        "<div style='position:relative;width:34px;height:34px'>"
        + corner(0, 12, bases.get("second"))
        + corner(12, 24, bases.get("first"))
        + corner(12, 0, bases.get("third"))
        + "</div>"
    )
    dots = "".join(
        f"<span style='display:inline-block;width:7px;height:7px;border-radius:50%;"
        f"background-color:{on if i < outs else off};margin-right:3px'></span>"
        for i in range(3)
    )
    return (
        f"<div style='display:flex;flex-direction:column;align-items:center;gap:{GAP}px'>"
        f"{status_html}{diamond}<div>{dots}</div></div>"
    )


def _readable_text_color(bg_hex: str) -> str:
    """Black or white, whichever has the higher WCAG contrast ratio against
    `bg_hex` — used instead of a hardcoded per-team lookup so it stays
    correct automatically (e.g. a team rebrand or color tweak in teams.py
    just works) rather than needing a second table kept in sync by hand."""
    bg_hex = bg_hex.lstrip("#")
    r, g, b = int(bg_hex[0:2], 16), int(bg_hex[2:4], 16), int(bg_hex[4:6], 16)

    def _linear(channel: int) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)
    white_contrast = 1.05 / (luminance + 0.05)
    black_contrast = (luminance + 0.05) / 0.05
    return "#FFFFFF" if white_contrast > black_contrast else "#000000"


def run_scored_badge_html(runs: int, team_color: str, fly_x: str) -> str:
    """A circular "+N" badge in the scoring team's own color that pops in
    next to the score, then flies the short distance `fly_x` (a CSS length
    with sign, e.g. "10px" or "-10px" — positive travels right) into the
    score digit and shrinks away, timed (see main.py's diamondRunFlyIn
    keyframes) to land right as that digit's own diamondScorePop animation
    peaks — the "jumps into the score" effect. Meant to be rendered ONLY on
    the fragment rerun where Today's Games detects a team's score just went
    up (comparing against the previous poll's score in st.session_state),
    so it naturally appears once per run scored rather than needing to be
    explicitly dismissed. Text color is computed per-team (see
    _readable_text_color) rather than a fixed dark color, since several
    team colors (e.g. the Athletics' dark green) are too dark for black
    text to read against."""
    text_color = _readable_text_color(team_color)
    return (
        f"<span class='run-scored-badge' style='background-color:{team_color};"
        f"color:{text_color};--fly-x:{fly_x}'>+{runs}</span>"
    )


def _playoff_pct_color(pct: float) -> str:
    """Red (0%) -> yellow (50%) -> green (100%) — same visual language as
    the rest of the app's background_gradient(cmap="RdYlGn") stat columns,
    hand-rolled here since this table is raw HTML, not a pandas Styler."""
    pct = max(0.0, min(100.0, pct))
    if pct <= 50:
        t = pct / 50
        r, g, b = (217, int(107 + t * (196 - 107)), int(96 + t * (94 - 96)))
    else:
        t = (pct - 50) / 50
        r, g, b = (int(196 + t * (76 - 196)), int(196 + t * (175 - 196)), int(94 + t * (80 - 94)))
    return f"rgb({r},{g},{b})"


_CLINCH_SYMBOLS = {"division_clinch": "z", "wildcard_clinch": "x", "eliminated": "e"}


def standings_table(div_standings, team_color_fn, clinch_symbols=None, compact=False) -> str:
    """One division's standings as a plain HTML table, with each team's
    abbreviation rendered as a colored badge that's also a link to
    `?team=ABBR` — clicking the team name itself (not a checkbox/selector
    column, which is all st.dataframe's row-selection offers) is what
    navigates. The Standings page reads that query param on load, stashes
    the team in session_state, and st.switch_page()s to the Team page.

    `div_standings` must have Team/W/L/PCT/GB/Streak plus RS/RA/Diff (runs
    scored/allowed/differential) and Playoff% (db.compute_playoff_odds) —
    except in `compact` mode, which only ever reads Team/W/L (everything
    else can be present and is simply ignored), for a condensed Team/W/L-
    only table like Home's space-constrained standings section.
    `clinch_symbols`, if given, is {team_abbr: "z"/"x"/"e"} from
    db.clinch_elimination_status — the standard newspaper-standings
    notation (z = clinched division, x = clinched a playoff spot,
    e = eliminated), rendered as a small superscript after the team badge."""
    has_playoff_pct = not compact and "Playoff%" in div_standings.columns
    clinch_symbols = clinch_symbols or {}
    rows = ""
    for _, row in div_standings.iterrows():
        color = team_color_fn(row["Team"])
        symbol = clinch_symbols.get(row["Team"])
        symbol_html = f"<sup style='color:#9AA3B5;font-weight:700;margin-left:2px'>{symbol}</sup>" if symbol else ""
        team_cell = (
            f"<td style='padding:5px 10px'><a href='?team={row['Team']}' target='_self' "
            f"style='background-color:{color}66;color:#FAFAFA;padding:2px 9px;border-radius:6px;"
            f"font-weight:700;text-decoration:none;cursor:pointer'>{row['Team']}</a>{symbol_html}</td>"
        )
        if compact:
            rows += (
                "<tr style='border-top:1px solid #4A5266'>"
                f"{team_cell}"
                f"<td style='padding:5px 10px;text-align:center'>{row['W']}</td>"
                f"<td style='padding:5px 10px;text-align:center'>{row['L']}</td>"
                "</tr>"
            )
            continue
        streak = row["Streak"] if pd.notna(row["Streak"]) else "—"
        gb = row["GB"] if pd.notna(row["GB"]) else "—"
        diff = row["Diff"]
        diff_str = f"+{diff:.0f}" if pd.notna(diff) and diff > 0 else (f"{diff:.0f}" if pd.notna(diff) else "—")
        playoff_cell = ""
        if has_playoff_pct:
            pct = row["Playoff%"]
            pct_str = f"{pct:.1f}%" if pd.notna(pct) else "—"
            bar_color = _playoff_pct_color(pct) if pd.notna(pct) else "#4A5266"
            playoff_cell = (
                "<td style='padding:5px 10px;text-align:center'>"
                f"<span style='background-color:{bar_color}40;color:{bar_color};padding:2px 8px;"
                f"border-radius:6px;font-weight:700'>{pct_str}</span></td>"
            )
        rows += (
            "<tr style='border-top:1px solid #4A5266'>"
            f"{team_cell}"
            f"<td style='padding:5px 10px;text-align:center'>{row['W']}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{row['L']}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{row['PCT']}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{gb}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{streak}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{row['RS']}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{row['RA']}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{diff_str}</td>"
            f"{playoff_cell}"
            "</tr>"
        )
    header_cols = ["Team", "W", "L"] if compact else ["Team", "W", "L", "PCT", "GB", "Streak", "RS", "RA", "Diff"]
    if has_playoff_pct:
        header_cols.append("Playoff%")
    headers = "".join(
        f"<th style='padding:5px 10px;text-align:{'left' if h == 'Team' else 'center'};"
        f"color:#9AA3B5;font-weight:600'>{'Playoff Odds' if h == 'Playoff%' else h}</th>"
        for h in header_cols
    )
    return (
        "<table style='width:100%;border-collapse:collapse'>"
        f"<thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>"
    )


def playoff_odds_table(df, team_color_fn) -> str:
    """One league's full playoff/World Series odds table (see
    db.compute_playoff_odds) — every team in the league, not just the
    current top 12, so a fringe contender's long-shot odds are visible
    too. `df` needs Team/W/L/Playoff%/Division%/Wildcard%/WS%."""
    rows = ""
    for _, row in df.iterrows():
        color = team_color_fn(row["Team"])

        def _pct_cell(col):
            pct = row[col]
            pct_str = f"{pct:.1f}%" if pd.notna(pct) else "—"
            bar_color = _playoff_pct_color(pct) if pd.notna(pct) else "#4A5266"
            return (
                "<td style='padding:5px 10px;text-align:center'>"
                f"<span style='background-color:{bar_color}40;color:{bar_color};padding:2px 8px;"
                f"border-radius:6px;font-weight:700'>{pct_str}</span></td>"
            )

        rows += (
            "<tr style='border-top:1px solid #4A5266'>"
            f"<td style='padding:5px 10px'><a href='?team={row['Team']}' target='_self' "
            f"style='background-color:{color}66;color:#FAFAFA;padding:2px 9px;border-radius:6px;"
            f"font-weight:700;text-decoration:none;cursor:pointer'>{row['Team']}</a></td>"
            f"<td style='padding:5px 10px;text-align:center'>{row['W']}-{row['L']}</td>"
            f"{_pct_cell('Playoff%')}{_pct_cell('Division%')}{_pct_cell('Wildcard%')}{_pct_cell('WS%')}"
            "</tr>"
        )
    headers = "".join(
        f"<th style='padding:5px 10px;text-align:{'left' if h == 'Team' else 'center'};"
        f"color:#9AA3B5;font-weight:600'>{h}</th>"
        for h in ("Team", "W-L", "Playoff%", "Division%", "Wildcard%", "WS%")
    )
    return (
        "<table style='width:100%;border-collapse:collapse'>"
        f"<thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>"
    )


# One-time CSS for playoff_bracket_tree()'s tree shape: a `.br-pair` is a
# flex column of exactly 2 equal-height `.br-slot`s (so their content
# naturally centers at 25%/75% of the pair's own height); nesting pairs
# inside pairs is what produces the WC -> Division Series -> Championship
# Series funnel, with each level's connector lines exact by construction
# (no manual pixel math, no JS layout pass — just flexbox arithmetic).
# The mirrored variants (.mirror) put every line/stub/shift on the LEFT
# instead of the right, so the NL tree can grow leftward — AL and NL then
# sit on either side of a centered World Series box, flowing toward each
# other exactly like the real TV bracket graphic, converging leagues
# lining up automatically since both trees share the same symmetric
# 4-leaf structure (their own Championship Series slot always lands at
# their own vertical center, so align-items:center on the row aligns
# both of them — and the World Series box — to the same line).
PLAYOFF_BRACKET_CSS = """
<style>
.bracket-tree { display:flex; align-items:center; }
.bracket-row { display:flex; align-items:center; justify-content:center; flex-wrap:wrap; gap:0; }
.br-pair { display:flex; flex-direction:column; position:relative; }
.br-pair::after {
  content:''; position:absolute; right:0; top:25%; bottom:25%; width:1px; background:#4A5266;
}
.br-pair.mirror::after { right:auto; left:0; }
.br-slot { flex:1; display:flex; align-items:center; position:relative; padding-right:18px; min-height:36px; }
.br-slot::after {
  content:''; position:absolute; right:0; top:50%; width:18px; height:1px; background:#4A5266;
}
.br-slot.mirror { padding-right:0; padding-left:18px; justify-content:flex-end; }
.br-slot.mirror::after { right:auto; left:0; }
.br-bye-shift { margin-left:88px; }
.br-bye-shift.mirror { margin-left:0; margin-right:88px; }
.br-team {
  display:flex; align-items:center; gap:6px; background-color:#1B243866; border-radius:6px;
  padding:4px 10px; white-space:nowrap; font-size:0.8rem;
}
.br-seed { color:#9AA3B5; font-weight:700; font-size:0.75rem; }
.br-badge {
  background-color:var(--br-color) !important; color:#FAFAFA !important; padding:1px 7px; border-radius:5px;
  font-weight:700; text-decoration:none !important; font-size:0.8rem;
}
.br-rec { color:#9AA3B5; font-size:0.75rem; }
.br-tag { color:#F5B942; font-size:0.7rem; font-weight:700; }
.br-matchbox { display:flex; flex-direction:column; gap:3px; }
.br-ws-box {
  display:flex; flex-direction:column; align-items:center; gap:6px; background-color:#1B243866;
  border:1px solid #4A5266; border-radius:8px; padding:14px 22px; font-size:0.85rem; color:#9AA3B5;
  position:relative; margin:0 24px;
}
.br-ws-box::before, .br-ws-box::after {
  content:''; position:absolute; top:50%; width:24px; height:1px; background:#4A5266;
}
.br-ws-box::before { left:-24px; }
.br-ws-box::after { right:-24px; }
.br-ws-title { color:#F5B942; font-weight:700; letter-spacing:0.5px; }
</style>
"""


def playoff_bracket_tree(seeded: pd.DataFrame, team_color_fn, mirror: bool = False) -> str:
    """One league's "if the season ended today" bracket, drawn as an
    actual bracket TREE (Wild Card -> Division Series -> Championship
    Series, converging with connector lines) rather than a stacked list —
    see PLAYOFF_BRACKET_CSS for how the nesting produces the shape.
    Seeds 1-2 get a bye (shown starting one column in, at the same depth
    their Division Series opponent — the Wild Card round's winner — will
    join them); seed 3 vs 6 and seed 4 vs 5 play the Wild Card round.
    `mirror=True` flips every connector to the left side, so the tree
    grows right-to-left — for pairing an AL tree (normal) with an NL tree
    (mirrored) around a centered World Series box, like the real bracket.
    `seeded` needs seed/team_abbr/wins/losses, seed 1-6."""
    by_seed = {int(r["seed"]): r for _, r in seeded.iterrows()}
    if len(by_seed) < 6:
        return "<div style='color:#9AA3B5'>Not enough teams to seed a bracket yet.</div>"

    mirror_cls = " mirror" if mirror else ""

    def team_html(row, tag=None):
        abbr = row["team_abbr"]
        color = team_color_fn(abbr)
        tag_html = f"<span class='br-tag'>{tag}</span>" if tag else ""
        return (
            "<div class='br-team'>"
            f"<span class='br-seed'>{int(row['seed'])}</span>"
            f"<a href='?team={abbr}' target='_self' class='br-badge' style='--br-color:{color}66'>{abbr}</a>"
            f"<span class='br-rec'>{int(row['wins'])}-{int(row['losses'])}</span>{tag_html}</div>"
        )

    def match_html(row_a, row_b):
        return f"<div class='br-matchbox'>{team_html(row_a)}{team_html(row_b)}</div>"

    def pair(left_html, right_html):
        return (
            f"<div class='br-pair{mirror_cls}'>"
            f"<div class='br-slot{mirror_cls}'>{left_html}</div>"
            f"<div class='br-slot{mirror_cls}'>{right_html}</div></div>"
        )

    bye1 = f"<div class='br-bye-shift{mirror_cls}'>{team_html(by_seed[1], 'BYE')}</div>"
    bye2 = f"<div class='br-bye-shift{mirror_cls}'>{team_html(by_seed[2], 'BYE')}</div>"
    wc_top = match_html(by_seed[3], by_seed[6])
    wc_bottom = match_html(by_seed[4], by_seed[5])

    tree = pair(pair(bye1, wc_top), pair(wc_bottom, bye2))
    return f"<div class='bracket-tree'>{tree}</div>"


def full_playoff_bracket_html(al_seeded: pd.DataFrame, nl_seeded: pd.DataFrame, team_color_fn) -> str:
    """The complete postseason picture, both leagues at once: AL tree on
    the left (Wild Card -> Division Series -> Championship Series flowing
    left to right), NL tree on the right (same rounds, mirrored to flow
    right to left), meeting at a centered World Series box — the same
    shape as the real MLB bracket graphic, showing every round from Wild
    Card through the World Series in one continuous connected path."""
    al_html = playoff_bracket_tree(al_seeded, team_color_fn, mirror=False)
    nl_html = playoff_bracket_tree(nl_seeded, team_color_fn, mirror=True)
    ws_html = (
        "<div class='br-ws-box'><span class='br-ws-title'>World Series</span>"
        "<span>AL Champion (TBD)</span><span>vs.</span><span>NL Champion (TBD)</span></div>"
    )
    return f"<div class='bracket-row'>{al_html}{ws_html}{nl_html}</div>"


_SCHEDULE_STATUS_LABELS = {"Preview": "Scheduled", "Live": "Live"}


def team_schedule_table(sched: pd.DataFrame, team_color_fn) -> str:
    """A team's full-season schedule (see db.team_schedule) as a plain HTML
    table — one row per game, played games showing a W/L-colored final
    score, upcoming games showing "Scheduled" (and a live game showing
    "Live") with no score yet. Each game's local kickoff time is rendered
    client-side (see the '.game-time-local[data-utc]' script pattern used
    on the Today's Games page) from the UTC timestamp in `data-utc`, since
    the server has no idea what timezone the viewer is in.

    The most recent played/live game gets id='sched-anchor' — the Team
    page scrolls the schedule container to it on load, so the schedule
    opens already positioned at "now" instead of opening scrolled to
    Opening Day; scrolling up reveals earlier games, down reveals later
    ones, in normal date order."""
    sched = sched.reset_index(drop=True)
    anchor_positions = sched.index[sched["status"] != "Preview"]
    anchor_idx = anchor_positions[-1] if len(anchor_positions) else (len(sched) - 1 if len(sched) else None)

    rows = ""
    for i, row in sched.iterrows():
        opp_color = team_color_fn(row["opponent"])
        vs_at = "vs" if row["home"] else "@"
        matchup = (
            f"{vs_at} <span style='background-color:{opp_color}66;color:#FAFAFA;padding:2px 8px;"
            f"border-radius:6px;font-weight:700'>{row['opponent']}</span>"
        )
        if row["result"] == "W":
            score_cell = (
                f"<span style='color:#4ADE80;font-weight:700'>W</span> "
                f"{row['runs_for']:.0f}-{row['runs_against']:.0f}"
            )
        elif row["result"] == "L":
            score_cell = (
                f"<span style='color:#F87171;font-weight:700'>L</span> "
                f"{row['runs_for']:.0f}-{row['runs_against']:.0f}"
            )
        else:
            label = _SCHEDULE_STATUS_LABELS.get(row["status"], row["status"])
            score_cell = f"<span style='color:#9AA3B5'>{label}</span>"
        time_cell = (
            f"<span class='game-time-local' data-utc='{row['game_time']}'>&nbsp;</span>"
            if pd.notna(row.get("game_time")) else "—"
        )
        row_id = " id='sched-anchor'" if i == anchor_idx else ""
        rows += (
            f"<tr{row_id} style='border-top:1px solid #4A5266'>"
            f"<td style='padding:5px 10px'>{row['date']}</td>"
            f"<td style='padding:5px 10px;color:#9AA3B5;font-size:0.85rem'>{time_cell}</td>"
            f"<td style='padding:5px 10px'>{matchup}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{score_cell}</td>"
            "</tr>"
        )
    headers = "".join(
        f"<th style='padding:5px 10px;text-align:{'left' if h != 'Result' else 'center'};"
        f"color:#9AA3B5;font-weight:600'>{h}</th>"
        for h in ("Date", "Time", "Opponent", "Result")
    )
    return (
        "<table style='width:100%;border-collapse:collapse'>"
        f"<thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>"
    )


def style_stats_table(df, higher_better=None, lower_better=None, team_col=None,
                       team_color_fn=None, team_abbr_fn=None, precision=None):
    """Return a pandas Styler for st.dataframe with:
    - background_gradient on `higher_better`/`lower_better` numeric columns
    - a team-color badge (background tint + abbreviation) on `team_col`
    - optional per-column number formatting via `precision` (dict of col -> format string)
    """
    higher_better = [c for c in (higher_better or []) if c in df.columns]
    lower_better = [c for c in (lower_better or []) if c in df.columns]

    styler = df.style

    # Default every float column to 3 decimal places (pandas Styler shows
    # full float precision otherwise), then let explicit `precision` override.
    float_cols = df.select_dtypes(include="float").columns
    fmt = {c: "{:.3f}" for c in float_cols}
    if precision:
        fmt.update({c: f for c, f in precision.items() if c in df.columns})
    if fmt:
        styler = styler.format(fmt, na_rep="—")

    for col in higher_better:
        styler = styler.background_gradient(subset=[col], cmap="RdYlGn")
    for col in lower_better:
        styler = styler.background_gradient(subset=[col], cmap="RdYlGn_r")

    if team_col and team_col in df.columns and team_color_fn:
        def _team_bg(val):
            color = team_color_fn(val)
            return f"background-color: {color}66; color: #FAFAFA; font-weight: 600"

        styler = styler.map(_team_bg, subset=[team_col])
        if team_abbr_fn:
            styler = styler.format({team_col: team_abbr_fn})

    return styler


# The field itself is the user-supplied image (app/assets/baseballfield.png),
# embedded as a data URI so it's self-contained HTML — Streamlit has no route
# to serve a plain local file path into markdown/HTML. Player cards are
# positioned as x%/y% over it, measured directly from the image's pixels
# (a 265x265 PNG) so each card lines up with that image's actual bases.
_FIELD_IMAGE_PATH = Path(__file__).resolve().parent / "assets" / "baseballfield.png"
_FIELD_IMAGE_B64 = base64.b64encode(_FIELD_IMAGE_PATH.read_bytes()).decode() if _FIELD_IMAGE_PATH.exists() else ""

_DIAMOND_FIELD_SVG = (
    f"<img src='data:image/png;base64,{_FIELD_IMAGE_B64}' "
    "style='position:absolute;top:0;left:0;width:100%;height:100%;object-fit:contain;z-index:0' />"
)

# (depth-chart position code, on-field label, x%, y%) — measured from the
# actual base/mound pixel positions in app/assets/baseballfield.png (265x265).
_DIAMOND_POSITIONS = [
    ("CF", "CF", 50, 20),
    ("LF", "LF", 24, 35),
    ("RF", "RF", 76, 35),
    ("2B", "2B", 62, 45),
    ("SS", "SS", 38, 45),
    ("1B", "1B", 74, 60),
    ("3B", "3B", 26, 60),
    ("SP", "P", 50, 62),
    ("C", "C", 50, 85),
    ("DH", "DH", 74, 85),  # horizontally aligned with C (same y), vertically with 1B (same x)
    ("RP", "RP", 26, 85),  # horizontally aligned with C (same y), vertically with 3B (same x)
]

# Photo diameter for _DIAMOND_POSITIONS cards — used to anchor each card by
# the photo's own vertical center (see baseball_diamond), not the block's.
_DIAMOND_PHOTO_SIZE = 56


def baseball_diamond(starters: dict, team_color: str) -> str:
    """HTML+SVG baseball diamond showing each defensive position's current
    starter (photo + name), from db.load_depth_chart() or
    db.build_composite_team(). `starters` maps a depth-chart position code
    ("SP", "C", "1B", ...) to {"name", "mlbID"}, plus an optional "note"
    (e.g. "0.950 OPS") shown under the position label when present — used
    by composite (rookie/all-MLB/hot-month) teams to show why a player was
    picked. A position with no data just renders as a "TBD" placeholder card."""
    cards = []
    for key, label, x, y in _DIAMOND_POSITIONS:
        player = starters.get(key)
        if player:
            name = player["name"]
            note = player.get("note")
            photo_html = (
                f"<img src='{headshot_url(player['mlbID'], width=120)}' "
                f"style='width:56px;height:56px;border-radius:50%;object-fit:cover;object-position:center 25%;"
                f"border:2px solid {team_color};box-shadow:0 2px 6px rgba(0,0,0,0.5)' />"
            )
        else:
            name = "TBD"
            note = None
            photo_html = (
                f"<div style='width:56px;height:56px;border-radius:50%;background:#4A5266;"
                f"border:2px solid {team_color};display:flex;align-items:center;justify-content:center;"
                f"font-size:0.7rem;color:#FAFAFA;margin:0 auto'>?</div>"
            )
        note_html = (
            f"<div style='font-size:0.6rem;color:#F5B942;text-shadow:0 1px 3px rgba(0,0,0,0.8)'>{note}</div>"
            if note else ""
        )
        cards.append(
            f"<div style='position:absolute;left:{x}%;top:{y}%;"
            f"transform:translate(-50%,-{_DIAMOND_PHOTO_SIZE / 2:.0f}px);"
            f"text-align:center;z-index:1;width:90px'>"
            f"{photo_html}"
            f"<div style='margin-top:4px;font-size:0.75rem;font-weight:700;color:#FAFAFA;"
            f"text-shadow:0 1px 3px rgba(0,0,0,0.8);overflow-wrap:break-word'>{name}</div>"
            f"<div style='font-size:0.65rem;color:#D8DEE9;text-shadow:0 1px 3px rgba(0,0,0,0.8)'>{label}</div>"
            f"{note_html}"
            f"</div>"
        )
    return (
        "<div style='position:relative;width:min(560px,100%);aspect-ratio:1/1;margin:0 auto 1.5rem;"
        "border-radius:12px;overflow:hidden'>" + _DIAMOND_FIELD_SVG + "".join(cards) + "</div>"
    )


def _fmt_compare_value(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if isinstance(v, str):
        return v
    if float(v) == int(v):
        return f"{int(v)}"
    return f"{v:.3f}"


def style_comparison(df, higher_better=None, lower_better=None):
    """df: index = stat name, two columns = the two players' values.
    Highlights whichever cell in each row is the better value."""
    higher_better = set(higher_better or [])
    lower_better = set(lower_better or [])
    win_style = "background-color: #2e7d3244; color: #7CFC9A; font-weight: 700"

    def highlight_row(row):
        stat = row.name
        vals = row.values
        blank = ["", ""]
        if stat not in higher_better and stat not in lower_better:
            return blank
        if pd.isna(vals[0]) or pd.isna(vals[1]) or vals[0] == vals[1]:
            return blank
        better_is_first = vals[0] > vals[1] if stat in higher_better else vals[0] < vals[1]
        return [win_style, ""] if better_is_first else ["", win_style]

    return df.style.apply(highlight_row, axis=1).format(_fmt_compare_value, na_rep="—")


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Plotly's color validator rejects 8-digit hex (hex + alpha suffix) in
    some versions — convert to an explicit rgba() string instead, which is
    always accepted."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def radar_chart(categories, values_a, values_b, name_a, name_b, color_a=ACCENT, color_b="#93C5FD"):
    """Percentile radar (0-100 scale) comparing two players across `categories`."""
    theta = categories + [categories[0]]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values_a + [values_a[0]], theta=theta, fill="toself", name=name_a,
        line_color=color_a, fillcolor=_hex_to_rgba(color_a, 0.2),
    ))
    fig.add_trace(go.Scatterpolar(
        r=values_b + [values_b[0]], theta=theta, fill="toself", name=name_b,
        line_color=color_b, fillcolor=_hex_to_rgba(color_b, 0.2),
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], color="#FAFAFA", gridcolor=_hex_to_rgba("#4A5266", 0.2)),
            angularaxis=dict(color="#FAFAFA"),
            bgcolor="rgba(0,0,0,0)",
        ),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.15),
        paper_bgcolor="rgba(0,0,0,0)",
        font_color="#FAFAFA",
        height=420,
        margin=dict(l=50, r=50, t=30, b=30),
    )
    return fig


_PITCH_RESULT_COLORS = {"in_play": "#F5B942", "strike": "#F87171", "ball": "#7CFC9A"}


def strike_zone_chart(pitches: list[dict]) -> "go.Figure":
    """Catcher's-eye-view strike zone for the CURRENT at-bat's pitches so
    far (see db.load_live_pitch_tracker) — each pitch plotted at its real
    plate location in feet, numbered in sequence, colored by result. The
    strike zone box uses the most recent pitch's own top/bottom bounds
    rather than an average across pitches, since those bounds are set by
    the batter's stance and averaging across an at-bat (let alone a whole
    game, across different batters) would blur the box away from what any
    single pitch was actually judged against."""
    fig = go.Figure()
    sz_top = pitches[-1]["sz_top"] if pitches else 3.5
    sz_bottom = pitches[-1]["sz_bottom"] if pitches else 1.5
    fig.add_shape(
        type="rect", x0=-0.708, x1=0.708, y0=sz_bottom, y1=sz_top,
        line=dict(color="#9AA3B5", width=2), fillcolor="rgba(0,0,0,0)",
    )
    for p in pitches:
        kind = "in_play" if p["is_in_play"] else ("strike" if p["is_strike"] else "ball")
        speed_bit = f"{p['speed']:.1f} mph " if p.get("speed") else ""
        fig.add_trace(go.Scatter(
            x=[p["px"]], y=[p["pz"]], mode="markers+text",
            marker=dict(size=28, color=_PITCH_RESULT_COLORS[kind], line=dict(color="#12141C", width=1.5)),
            text=[str(p["number"])], textfont=dict(color="#12141C", size=12, family="Arial Black"),
            hovertext=f"{speed_bit}{p['pitch_type']} — {p['description']}", hoverinfo="text",
            showlegend=False,
        ))
    fig.update_xaxes(range=[-2.5, 2.5], visible=False, fixedrange=True)
    fig.update_yaxes(range=[0, 5], visible=False, fixedrange=True, scaleanchor="x", scaleratio=1)
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=380, margin=dict(l=10, r=10, t=10, b=10),
    )
    return fig


def win_probability_chart(wp_df, away_abbr: str, home_abbr: str, away_color: str, home_color: str) -> "go.Figure":
    """Home-team win probability across the game so far (see
    db.load_win_probability) — the filled area is colored by the home
    team's own color above the 50% line, but the line itself doesn't
    change color when the away team takes the lead below it, since
    plotly's single-trace fill can't cleanly split into two colors without
    duplicating the series; away_color is used for the 50% reference
    line's label instead so both teams' colors appear somewhere on the
    chart."""
    fig = go.Figure()
    fig.add_hline(
        y=50, line=dict(color=_hex_to_rgba(away_color, 0.5), width=1, dash="dot"),
        annotation_text=f"{away_abbr} favored below", annotation_font_color="#9AA3B5", annotation_font_size=10,
    )
    fig.add_trace(go.Scatter(
        x=wp_df["atBatIndex"], y=wp_df["home_win_pct"], mode="lines",
        line=dict(color=home_color, width=2.5), fill="tozeroy", fillcolor=_hex_to_rgba(home_color, 0.15),
        hovertemplate=f"{home_abbr} %{{y:.0f}}%<extra></extra>",
    ))
    fig.update_yaxes(range=[0, 100], gridcolor=_hex_to_rgba("#4A5266", 0.25), color="#9AA3B5", ticksuffix="%")
    fig.update_xaxes(visible=False)
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA",
        height=220, margin=dict(l=10, r=10, t=10, b=10), showlegend=False,
    )
    return fig


# (label, profile key, higher_is_better, format string) — used by
# matchup_preview_html to compare two teams stat-by-stat. Order matters:
# it's also the display order.
_MATCHUP_METRICS = [
    ("Offense (OPS)", "ops", True, "{:.3f}"),
    ("Rotation (Starter ERA)", "starter_era", False, "{:.2f}"),
    ("Bullpen (ERA)", "bullpen_era", False, "{:.2f}"),
    ("Power (HR)", "hr", True, "{:,.0f}"),
    ("Speed (SB)", "sb", True, "{:,.0f}"),
    ("Defense (OAA)", "oaa", True, "{:+.0f}"),
]


def matchup_preview_html(profile_a: dict, profile_b: dict, team_color_fn) -> str:
    """A stat-driven strengths/weaknesses comparison for two playoff teams
    (see db.team_strength_profile) — purely derived from the numbers
    already on the site, not researched/written commentary (that's the
    player-bios approach, which didn't land well as a site feature; this
    is meant to be the automatable, no-manual-upkeep alternative). Every
    metric in _MATCHUP_METRICS gets a winner; the "Watch for" callouts are
    just the metrics with the largest relative gap between the two teams,
    not any kind of prediction."""
    color_a, color_b = team_color_fn(profile_a["team_abbr"]), team_color_fn(profile_b["team_abbr"])
    rows, gaps = [], []
    for label, key, higher_better, fmt in _MATCHUP_METRICS:
        va, vb = profile_a.get(key), profile_b.get(key)
        if va is None or vb is None or pd.isna(va) or pd.isna(vb):
            continue
        a_wins = (va > vb) if higher_better else (va < vb)
        denom = (abs(va) + abs(vb)) / 2 or 1
        gaps.append((abs(va - vb) / denom, label))
        winner_color = color_a if a_wins else color_b
        rows.append(
            "<tr style='border-top:1px solid #4A5266'>"
            f"<td style='padding:6px 10px;text-align:right;font-weight:{700 if a_wins else 400};"
            f"color:{'#FAFAFA' if a_wins else '#9AA3B5'}'>{fmt.format(va)}</td>"
            f"<td style='padding:6px 14px;text-align:center;color:#9AA3B5;white-space:nowrap'>{label}</td>"
            f"<td style='padding:6px 10px;text-align:left;font-weight:{700 if not a_wins else 400};"
            f"color:{'#FAFAFA' if not a_wins else '#9AA3B5'}'>{fmt.format(vb)}</td>"
            "</tr>"
        )
    table = (
        "<table style='width:100%;border-collapse:collapse'>"
        "<thead><tr>"
        f"<th style='padding:6px 10px;text-align:right;color:{color_a}'>{profile_a['team_abbr']}</th>"
        "<th></th>"
        f"<th style='padding:6px 10px;text-align:left;color:{color_b}'>{profile_b['team_abbr']}</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    top_gaps = [label for _, label in sorted(gaps, reverse=True)[:2]]
    focus = (
        f"<p style='color:#9AA3B5;margin-top:10px'>Biggest mismatches: {', '.join(top_gaps)}.</p>"
        if top_gaps else ""
    )
    return table + focus
