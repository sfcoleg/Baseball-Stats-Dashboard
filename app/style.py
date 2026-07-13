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


def sparkline_svg(values, color=ACCENT, width=72, height=22):
    """Tiny inline SVG line — no axes, gridlines, or labels, just the shape
    of a season-by-season trend (see db.player_career_arc()), sized to sit
    inline next to a sidebar search result. Returns "" for fewer than 2
    points (a single season has no trend to draw). Doesn't encode whether
    up or down is "good" (that flips between OPS and ERA) — it's just a
    glance at the shape of the career, not a judgment."""
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    n = len(values)
    points = []
    for i, v in enumerate(values):
        x = (i / (n - 1)) * (width - 4) + 2
        y = height - 2 - ((v - lo) / span) * (height - 4)
        points.append((x, y))
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    last_x, last_y = points[-1]
    return (
        f"<svg width='{width}' height='{height}' viewBox='0 0 {width} {height}' "
        f"xmlns='http://www.w3.org/2000/svg' style='vertical-align:middle'>"
        f"<polyline points='{path}' fill='none' stroke='{color}' stroke-width='1.5' "
        f"stroke-linejoin='round' stroke-linecap='round' />"
        f"<circle cx='{last_x:.1f}' cy='{last_y:.1f}' r='2.2' fill='{color}' />"
        f"</svg>"
    )


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


def colored_header(text, category):
    """A subheader with a colored left accent bar, keyed by CATEGORY_COLORS."""
    color = CATEGORY_COLORS.get(category, ACCENT)
    st.markdown(
        f"<h3 style='border-left: 5px solid {color}; padding-left: 14px; "
        f"margin-top: 1.2em; margin-bottom: 0.6em;'>{text}</h3>",
        unsafe_allow_html=True,
    )


def headliner_card(label, name, team_abbr, team_color, stat_line):
    """A stat card that shows the FULL player name (st.metric truncates long
    values with an ellipsis, which cuts off names like 'Heriberto Hernández')."""
    st.caption(label)
    st.markdown(
        f"<div style='font-size:1.4rem;font-weight:700;line-height:1.3;"
        f"overflow-wrap:break-word'>{name} "
        f"<span style='background-color:{team_color}66;color:#FAFAFA;padding:2px 9px;"
        f"border-radius:8px;font-size:0.65em;vertical-align:middle;font-weight:600'>{team_abbr}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='margin-top:6px;'><span style='background-color:#2e7d3244;"
        f"color:#7CFC9A;padding:3px 10px;border-radius:8px;font-weight:600;font-size:0.9rem'>"
        f"&uarr; {stat_line}</span></div>",
        unsafe_allow_html=True,
    )


def milestone_card(mlbID, name, team_abbr, team_color, text):
    """Photo on the left, name/badge + the achievement stacked to its
    right, for the Home page's Milestones section."""
    st.markdown(
        f"<div style='display:flex;align-items:flex-start;gap:12px'>"
        f"<img src='{headshot_url(mlbID, width=180)}' style='width:80px;height:80px;"
        f"border-radius:10px;object-fit:cover;flex-shrink:0' />"
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


def standings_table(div_standings, team_color_fn) -> str:
    """One division's standings as a plain HTML table, with each team's
    abbreviation rendered as a colored badge that's also a link to
    `?team=ABBR` — clicking the team name itself (not a checkbox/selector
    column, which is all st.dataframe's row-selection offers) is what
    navigates. The Standings page reads that query param on load, stashes
    the team in session_state, and st.switch_page()s to the Team page."""
    rows = ""
    for _, row in div_standings.iterrows():
        color = team_color_fn(row["Team"])
        streak = row["Streak"] if pd.notna(row["Streak"]) else "—"
        gb = row["GB"] if pd.notna(row["GB"]) else "—"
        rows += (
            "<tr style='border-top:1px solid #4A5266'>"
            f"<td style='padding:5px 10px'><a href='?team={row['Team']}' target='_self' "
            f"style='background-color:{color}66;color:#FAFAFA;padding:2px 9px;border-radius:6px;"
            f"font-weight:700;text-decoration:none;cursor:pointer'>{row['Team']}</a></td>"
            f"<td style='padding:5px 10px;text-align:center'>{row['W']}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{row['L']}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{row['PCT']}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{gb}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{streak}</td>"
            "</tr>"
        )
    headers = "".join(
        f"<th style='padding:5px 10px;text-align:{'left' if h == 'Team' else 'center'};"
        f"color:#9AA3B5;font-weight:600'>{h}</th>"
        for h in ("Team", "W", "L", "PCT", "GB", "Streak")
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
                f"style='width:56px;height:56px;border-radius:50%;object-fit:cover;"
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
