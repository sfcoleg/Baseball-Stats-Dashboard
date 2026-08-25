"""NHL-side display helpers — the hockey analog of app/style.py. Kept
separate since headshot/logo CDNs, routes, and chart shapes are all
different from the MLB side."""
import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import sys as _sys
from pathlib import Path as _Path
_sys.path.append(str(_Path(__file__).resolve().parent.parent))
# Chart colours live in the MLB-side style module; re-exported here so NHL
# pages can reach them through nstyle.* like everything else.
from style import (CHART_TEXT, CHART_DIM, CHART_GRID, CHART_SURFACE,  # noqa: F401
                   CHART_BLUE, CHART_AMBER, CHART_RED, CHART_GREEN,
                   BLUE_SCALE, HEAT_SCALE, HEAT_SCALE_R)

_CLINCH_LABELS = {"p": "Presidents' Trophy", "z": "Clinched conference", "y": "Clinched division", "x": "Clinched playoff berth"}


def player_link(player_id, season: int | None = None) -> str:
    """Relative URL to a skater/goalie's profile page — same pattern as the
    MLB side's style.player_link()."""
    url = f"nhl-player?nhlid={int(player_id)}"
    if season is not None:
        url += f"&season={int(season)}"
    return url


def team_link(abbr: str) -> str:
    return f"nhl-team?team={abbr}"


def standings_table(div_standings: pd.DataFrame, team_color_fn, elo_fn=None) -> str:
    """One division's standings as a plain HTML table — same clickable
    colored-badge pattern as the MLB side's style.standings_table(), with
    hockey's own columns (points, regulation+OT wins as the classic
    tiebreaker, goal differential) instead of run differential. Expects
    Team/GP/W/L/OTL/PTS/PTPCT/ROW/GD/Streak/L10/Clinch columns.
    `elo_fn`, if given, maps team abbr -> current Elo rating for an extra
    column (the trained game-odds model's own power ranking, which often
    disagrees with points early in a season before results catch up)."""
    has_odds = elo_fn is not None
    header_extra = "<th style='padding:5px 10px' title=\"Our Elo model's current power rating\">Elo</th>" if has_odds else ""
    rows = ""
    for _, row in div_standings.iterrows():
        color = team_color_fn(row["Team"])
        clinch = row.get("Clinch")
        clinch_title = _CLINCH_LABELS.get(clinch, "")
        symbol_html = (
            f"<sup style='color:var(--dm-dim);font-weight:700;margin-left:2px' title='{clinch_title}'>{clinch}</sup>"
            if isinstance(clinch, str) and clinch else ""
        )
        team_cell = (
            f"<td style='padding:5px 10px'><a href='{team_link(row['Team'])}' target='_self' "
            f"style='background-color:{color}66;color:var(--dm-text);padding:2px 9px;border-radius:6px;"
            f"font-weight:700;text-decoration:none;cursor:pointer'>{row['Team']}</a>{symbol_html}</td>"
        )
        streak = row["Streak"] if pd.notna(row.get("Streak")) else "—"
        gd = row["GD"]
        gd_str = f"+{gd:.0f}" if pd.notna(gd) and gd > 0 else (f"{gd:.0f}" if pd.notna(gd) else "—")
        odds_cell = ""
        if has_odds:
            elo = elo_fn(row["Team"])
            elo_str = f"{elo:.0f}" if elo is not None else "—"
            odds_cell = f"<td style='padding:5px 10px;text-align:center'>{elo_str}</td>"
        rows += (
            "<tr style='border-top:1px solid var(--dm-line)'>"
            f"{team_cell}"
            f"<td style='padding:5px 10px;text-align:center'>{row['GP']}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{row['W']}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{row['L']}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{row['OTL']}</td>"
            f"<td style='padding:5px 10px;text-align:center;font-weight:700'>{row['PTS']}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{row['ROW']}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{gd_str}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{streak}</td>"
            f"<td style='padding:5px 10px;text-align:center'>{row['L10']}</td>"
            f"{odds_cell}"
            "</tr>"
        )
    return (
        # No fixed width: inside the page's overflow-x:auto wrapper, a
        # width:100% table gets squeezed to fit (cramping L10/Streak/Elo)
        # instead of actually scrolling — letting it size to its content
        # and nowrap-ping every cell means it's exactly as wide as it needs
        # to be, and only THEN does the wrapper's horizontal scroll kick in
        # on narrow/mobile screens.
        "<table style='border-collapse:collapse;font-size:0.9rem;white-space:nowrap'>"
        "<thead><tr style='color:var(--dm-dim);text-align:center'>"
        "<th style='padding:5px 10px;text-align:left'>Team</th>"
        "<th style='padding:5px 10px'>GP</th><th style='padding:5px 10px'>W</th>"
        "<th style='padding:5px 10px'>L</th><th style='padding:5px 10px'>OTL</th>"
        "<th style='padding:5px 10px'>PTS</th><th style='padding:5px 10px' title='Regulation + OT wins (tiebreaker)'>ROW</th>"
        "<th style='padding:5px 10px'>GD</th><th style='padding:5px 10px'>Streak</th>"
        "<th style='padding:5px 10px'>L10</th>" + header_extra +
        "</tr></thead><tbody>" + rows + "</tbody></table>"
    )


_RESULT_STYLE = {
    "goal": ("#FACC15", "star", 15),
    "shot-on-goal": ("#2563EB", "circle", 8),
    "missed-shot": ("#6B7280", "circle-open", 7),
    "blocked-shot": ("#D97706", "x", 7),
}
_RESULT_LABELS = {"goal": "Goal", "shot-on-goal": "Shot on net", "missed-shot": "Missed", "blocked-shot": "Blocked"}


def _arc(cx, cy, r, a0, a1, n=24):
    """Points along a circular arc (degrees), for building rink paths —
    plotly shape paths only support straight segments and beziers, not
    SVG arcs, so every curve is a short polyline."""
    return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
            for a in [a0 + (a1 - a0) * i / n for i in range(n + 1)]]


def _path(points, close=True) -> str:
    d = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in points)
    return d + (" Z" if close else "")


# Regulation NHL sheet, in feet, center ice at (0, 0): 200 x 85 with
# 28-ft corner radii; goal lines 11 ft from the end boards (x = ±89),
# blue lines at ±25, faceoff circles (r = 15) at (±69, ±22).
RINK_LEN, RINK_WID, CORNER_R = 200.0, 85.0, 28.0
GOAL_LINE_X, BLUE_LINE_X = 89.0, 25.0
ICE = "#EEF3F8"
BOARDS = "#7B8494"
RED = "#D63B3B"
BLUE = "#2E6BD3"
CREASE_FILL = "rgba(46,107,211,0.22)"


def _rink_outline_points():
    hx, hy, r = RINK_LEN / 2, RINK_WID / 2, CORNER_R
    pts = []
    pts += _arc(hx - r, hy - r, r, 0, 90)       # top-right corner
    pts += _arc(-hx + r, hy - r, r, 90, 180)    # top-left
    pts += _arc(-hx + r, -hy + r, r, 180, 270)  # bottom-left
    pts += _arc(hx - r, -hy + r, r, 270, 360)   # bottom-right
    return pts


def _corner_clip_y(x: float) -> float:
    """Half-height of the ice at a given |x| inside the corner radius —
    goal lines stop where they meet the curved boards."""
    hx, hy, r = RINK_LEN / 2, RINK_WID / 2, CORNER_R
    dx = abs(x) - (hx - r)
    if dx <= 0:
        return hy
    return (hy - r) + math.sqrt(max(r * r - dx * dx, 0))


def rink_outline(fig: "go.Figure") -> "go.Figure":
    """Draws a regulation NHL rink (to scale, in feet, center ice at 0,0)
    as plotly shapes: white ice with rounded boards, center red line, blue
    lines, goal lines, center + four faceoff circles with dots, the
    neutral-zone dots, both creases, goal frames, and the goalie
    trapezoids. Plot axes should be hidden with scaleanchor so 1 ft = 1 ft
    in both directions."""
    hy = RINK_WID / 2
    # Ice surface
    fig.add_shape(type="path", path=_path(_rink_outline_points()), fillcolor=ICE,
                  line=dict(color=BOARDS, width=3), layer="below")
    # Blue lines (1 ft wide) and center red line
    for x in (-BLUE_LINE_X, BLUE_LINE_X):
        fig.add_shape(type="rect", x0=x - 0.5, x1=x + 0.5, y0=-hy, y1=hy, fillcolor=BLUE, line_width=0, layer="below")
    fig.add_shape(type="rect", x0=-0.5, x1=0.5, y0=-hy, y1=hy, fillcolor=RED, line_width=0, layer="below")
    # Goal lines, clipped to the boards' corner radius
    gy = _corner_clip_y(GOAL_LINE_X)
    for x in (-GOAL_LINE_X, GOAL_LINE_X):
        fig.add_shape(type="line", x0=x, x1=x, y0=-gy, y1=gy, line=dict(color=RED, width=2), layer="below")
    # Center circle + dot
    fig.add_shape(type="circle", x0=-15, x1=15, y0=-15, y1=15, line=dict(color=BLUE, width=2), layer="below")
    fig.add_shape(type="circle", x0=-1, x1=1, y0=-1, y1=1, fillcolor=BLUE, line_width=0, layer="below")
    # End-zone faceoff circles + dots, and the neutral-zone dots
    for x in (-69, 69):
        for y in (-22, 22):
            fig.add_shape(type="circle", x0=x - 15, x1=x + 15, y0=y - 15, y1=y + 15,
                          line=dict(color=RED, width=2), layer="below")
            fig.add_shape(type="circle", x0=x - 1, x1=x + 1, y0=y - 1, y1=y + 1, fillcolor=RED, line_width=0, layer="below")
            # Hash marks on each circle (2 ft long, 5.67 ft apart)
            for sx in (-1, 1):
                for sy in (-1, 1):
                    fig.add_shape(type="line", x0=x + sx * 2.83, x1=x + sx * 2.83,
                                  y0=y + sy * 15, y1=y + sy * 17, line=dict(color=RED, width=1.5), layer="below")
    for x in (-20, 20):
        for y in (-22, 22):
            fig.add_shape(type="circle", x0=x - 1, x1=x + 1, y0=y - 1, y1=y + 1, fillcolor=RED, line_width=0, layer="below")
    # Creases (6-ft radius semicircles, 8 ft wide at the goal line), goal
    # frames (6 x 3.33 ft) and trapezoids — both ends
    for sign in (-1, 1):
        gx = sign * GOAL_LINE_X
        a0, a1 = (90, 270) if sign > 0 else (-90, 90)
        # 6-ft-radius arc bulging toward center ice, cut to 8 ft wide at
        # the goal line (|y| <= 4), closed along the goal line.
        half = math.degrees(math.asin(4 / 6))
        crease = [(gx, -4.0)] + [(gx - sign * 6 * math.cos(math.radians(t)), 6 * math.sin(math.radians(t)))
                                 for t in [-half + 2 * half * i / 20 for i in range(21)]] + [(gx, 4.0)]
        fig.add_shape(type="path", path=_path(crease), fillcolor=CREASE_FILL,
                      line=dict(color=RED, width=1.5), layer="below")
        fig.add_shape(type="rect", x0=gx, x1=gx + sign * 3.33, y0=-3, y1=3,
                      fillcolor="rgba(214,59,59,0.15)", line=dict(color=RED, width=2), layer="below")
        fig.add_shape(type="line", x0=gx, x1=sign * 100, y0=11, y1=14, line=dict(color=RED, width=1.5), layer="below")
        fig.add_shape(type="line", x0=gx, x1=sign * 100, y0=-11, y1=-14, line=dict(color=RED, width=1.5), layer="below")
    return fig


def rink_layout(fig: "go.Figure", height: int = 460, **kwargs) -> "go.Figure":
    """Axes/aspect settings every rink chart shares."""
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=kwargs.pop("top", 10), b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA",
        # constrain="domain" is what keeps this robust: with the default
        # (constrain="range"), plotly satisfies the 1:1 scaleanchor by
        # EXPANDING an axis range, and on Streamlit's first layout pass (when
        # the container can briefly measure ~0 px) that expansion blows the
        # ranges up by hundreds of x and the rink renders as a dot. Shrinking
        # the axis domain instead leaves the ranges exactly as given.
        xaxis=dict(range=[-103, 103], visible=False, scaleanchor="y", scaleratio=1, constrain="domain"),
        yaxis=dict(range=[-46, 46], visible=False, constrain="domain"),
        **kwargs,
    )
    return fig


def shot_map_chart(shots: pd.DataFrame, name: str) -> "go.Figure":
    """One player's or team's shots on the regulation rink, colored/shaped
    by result. `shots` needs x/y/result columns (see ingest/nhl_shots.py)."""
    fig = go.Figure()
    rink_outline(fig)
    for result, (color, symbol, size) in _RESULT_STYLE.items():
        sub = shots[shots["result"] == result]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["x"], y=sub["y"], mode="markers", name=f"{_RESULT_LABELS[result]} ({len(sub)})",
            marker=dict(color=color, symbol=symbol, size=size, opacity=0.85, line=dict(width=1, color="#FFFFFF")),
            hoverinfo="skip",
        ))
    rink_layout(fig, height=470, top=40, title=dict(text=name, x=0.5, xanchor="center"),
                legend=dict(orientation="h", yanchor="bottom", y=-0.06, x=0))
    return fig


def glossary_link():
    """Small, muted link to the NHL stat glossary — call near the top of a
    stat-heavy page, the hockey analog of the MLB side's
    style.glossary_link(). Styled via a href-matching CSS selector because
    page_link renders as a DOM sibling, not a child of any wrapper."""
    st.markdown(
        "<style>"
        "[data-testid='stMain'] a[href*='nhl-glossary'] { font-size: 0.8rem !important; opacity: 0.6; }"
        "[data-testid='stMain'] a[href*='nhl-glossary']:hover { opacity: 1; }"
        "</style>",
        unsafe_allow_html=True,
    )
    st.page_link("nhl/pages/glossary.py", label="ℹ️ What do these stats mean?", use_container_width=False)
