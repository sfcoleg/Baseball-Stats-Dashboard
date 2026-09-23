"""NBA-specific presentation. Shared chrome (headers, stat tables) still
comes from app/style.py; add to this as real NBA-only components come up,
following app/nfl/style.py's shape."""
import sys as _sys
from pathlib import Path as _Path

import plotly.graph_objects as go

_sys.path.append(str(_Path(__file__).resolve().parent.parent))
# Chart colours live in the MLB-side style module; re-exported here so NBA
# pages can reach them through nstyle.* like the NHL side does.
from style import (CHART_TEXT, CHART_DIM, CHART_GRID, CHART_SURFACE,  # noqa: F401
                   CHART_BLUE, CHART_AMBER, CHART_RED, CHART_GREEN,
                   BLUE_SCALE, HEAT_SCALE, HEAT_SCALE_R)


def player_link(player_id, season: str | None = None) -> str:
    """Relative URL to a player's profile page — same pattern as
    app/nhl/style.py's player_link(), one query param per sport since each
    player.py reads its own name (nba/pages/player.py reads "player")."""
    url = f"nba-player?player={int(player_id)}"
    if season is not None:
        url += f"&season={season}"
    return url


def headshot_url(player_id) -> str:
    """NBA's own CDN, confirmed directly (200 for a real player id) —
    same idea as app/style.py's headshot_url() for MLB."""
    return f"https://cdn.nba.com/headshots/nba/latest/1040x760/{int(player_id)}.png"


# Half-court outline in nba_api's own shot-chart coordinate system: hoop at
# (0, 0), units are roughly 1/10 ft (LOC_X/LOC_Y run about -250..250 across
# the width of the court, with the 3pt line at ~237.5 on the sides / 239.75
# up top) — a simplified approximation, not a rules-accurate diagram, but
# clean enough to place makes/misses against.
_COURT_LINE = "#7B8494"
_COURT_FILL = "rgba(0,0,0,0)"
HOOP_Y = 0


def court_outline(fig: "go.Figure") -> "go.Figure":
    """Draws a simplified NBA half-court (offensive end, hoop at bottom) as
    plotly shapes: court boundary, key/paint, free-throw circle, restricted
    area, backboard/rim, and the three-point line (corners + arc). Same
    spirit as app/nhl/style.py's rink_outline() but simpler for a first
    pass — good enough to orient shot locations against."""
    # Court boundary (baseline at y=-47, sidelines at x=+-250, half court
    # at y=~422 — we only draw up to a bit past the 3pt arc since shots
    # rarely come from the backcourt).
    fig.add_shape(type="rect", x0=-250, x1=250, y0=-47, y1=422,
                  line=dict(color=_COURT_LINE, width=2), fillcolor=_COURT_FILL, layer="below")
    # Key / paint (16 ft wide, 19 ft from baseline to free-throw line).
    fig.add_shape(type="rect", x0=-80, x1=80, y0=-47, y1=143,
                  line=dict(color=_COURT_LINE, width=2), fillcolor=_COURT_FILL, layer="below")
    # Free-throw circle.
    fig.add_shape(type="circle", x0=-60, x1=60, y0=83, y1=203,
                  line=dict(color=_COURT_LINE, width=2), layer="below")
    # Restricted area arc (4 ft radius around the hoop).
    fig.add_shape(type="circle", x0=-40, x1=40, y0=-40, y1=40,
                  line=dict(color=_COURT_LINE, width=1.5), layer="below")
    # Backboard + rim.
    fig.add_shape(type="line", x0=-30, x1=30, y0=-7.5, y1=-7.5, line=dict(color=_COURT_LINE, width=3), layer="below")
    fig.add_shape(type="circle", x0=-7.5, x1=7.5, y0=-7.5, y1=7.5, line=dict(color="#D97706", width=2), layer="below")
    # Three-point line: straight corners out to the arc, then an arc back.
    corner_y = 92.5  # corner 3 runs along the sideline until the arc takes over
    fig.add_shape(type="line", x0=-220, x1=-220, y0=-47, y1=corner_y, line=dict(color=_COURT_LINE, width=2), layer="below")
    fig.add_shape(type="line", x0=220, x1=220, y0=-47, y1=corner_y, line=dict(color=_COURT_LINE, width=2), layer="below")
    fig.add_shape(type="path", path=_arc_path(0, 0, 237.5, corner_y), line=dict(color=_COURT_LINE, width=2), layer="below")
    return fig


def _arc_path(cx: float, cy: float, r: float, min_y: float) -> str:
    """SVG path for the 3pt arc: the portion of a circle of radius `r`
    centered at (cx, cy) with y >= min_y, as a polyline (plotly shape paths
    only support straight segments/beziers, not true SVG arcs)."""
    import math
    half_angle = math.degrees(math.asin(min(max((min_y - cy) / r, -1), 1)))
    angles = [half_angle + (180 - 2 * half_angle) * i / 40 for i in range(41)]
    pts = [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in angles]
    return "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts)


def court_layout(fig: "go.Figure", height: int = 480, **kwargs) -> "go.Figure":
    """Axes/aspect settings the court chart shares — mirrors
    app/nhl/style.py's rink_layout()."""
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=kwargs.pop("top", 10), b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=CHART_TEXT,
        xaxis=dict(range=[-260, 260], visible=False, scaleanchor="y", scaleratio=1, constrain="domain"),
        yaxis=dict(range=[-60, 430], visible=False, constrain="domain"),
        **kwargs,
    )
    return fig


def shot_chart(shots, name: str) -> "go.Figure":
    """One player's shots on the simplified half-court, colored by make vs.
    miss. `shots` needs LOC_X/LOC_Y/SHOT_MADE_FLAG columns (see
    db.load_shot_chart)."""
    fig = go.Figure()
    court_outline(fig)
    makes = shots[shots["SHOT_MADE_FLAG"] == 1]
    misses = shots[shots["SHOT_MADE_FLAG"] == 0]
    if not misses.empty:
        fig.add_trace(go.Scatter(
            x=misses["LOC_X"], y=misses["LOC_Y"], mode="markers", name=f"Miss ({len(misses)})",
            marker=dict(color=CHART_RED, symbol="x", size=7, opacity=0.75), hoverinfo="skip",
        ))
    if not makes.empty:
        fig.add_trace(go.Scatter(
            x=makes["LOC_X"], y=makes["LOC_Y"], mode="markers", name=f"Make ({len(makes)})",
            marker=dict(color=CHART_GREEN, symbol="circle", size=7, opacity=0.85,
                        line=dict(width=1, color="#FFFFFF")),
            hoverinfo="skip",
        ))
    court_layout(fig, height=500, top=40, title=dict(text=name, x=0.5, xanchor="center"),
                 legend=dict(orientation="h", yanchor="bottom", y=-0.06, x=0))
    return fig
