"""Reusable pandas Styler helpers for dashboard tables: color-coded stat
columns (green = better, red = worse) and team-color badges."""
import math

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


CATEGORY_COLORS = {
    "batting": "#4C9F70",
    "pitching": "#3B82F6",
    "fielding": "#A855F7",
    "headliners": "#F5B942",
    "chart": "#E3572A",
}


def colored_header(text, category):
    """A subheader with a colored left accent bar, keyed by CATEGORY_COLORS."""
    color = CATEGORY_COLORS.get(category, "#E3572A")
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
    """Photo + name + team badge + achievement text, for the Home page's
    Milestones section. Call inside a `with col:` block, same pattern as
    headliner_card."""
    st.image(headshot_url(mlbID, width=180), width=110)
    st.markdown(
        f"<div style='font-size:1.2rem;font-weight:700;line-height:1.3;"
        f"overflow-wrap:break-word'>{name} "
        f"<span style='background-color:{team_color}66;color:#FAFAFA;padding:2px 9px;"
        f"border-radius:8px;font-size:0.65em;vertical-align:middle;font-weight:600'>{team_abbr}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='margin-top:6px;'><span style='background-color:#3B4A8244;"
        f"color:#B9C4FF;padding:3px 10px;border-radius:8px;font-weight:600;font-size:0.9rem'>"
        f"{text}</span></div>",
        unsafe_allow_html=True,
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


# Field geometry, viewBox 0 0 600 600, home plate at the bottom. Home and 2nd
# are opposite corners of a square whose diagonal is D=260; the other two
# corners (1st/3rd) sit at the square's center offset by D/2 each way — NOT
# D/sqrt(2) (that earlier version put 1st/3rd a full side-length off-center,
# stretching the shape into a non-square rhombus).
_HOME = (300, 560)
_D = 260
_SECOND = (300, _HOME[1] - _D)
_FIRST = (_HOME[0] + _D / 2, _HOME[1] - _D / 2)
_THIRD = (_HOME[0] - _D / 2, _HOME[1] - _D / 2)
# Mound sits ~47.5% of the way from home to 2nd (60.5ft of the real 127.28ft).
_MOUND = (300, _HOME[1] - 0.475 * _D)
# Foul lines extend the home->1B / home->3B rays out to the edge of the field.
_FOUL_RIGHT_END = (600, 260)
_FOUL_LEFT_END = (0, 260)


def _rounded_corner_path(points, radius):
    """SVG path for the closed polygon through `points`, with each corner
    replaced by a quadratic-bezier round (like a rounded-rect, generalized
    to any polygon) — real infield dirt cutouts curve at the basepath
    corners instead of coming to a sharp point."""
    n = len(points)

    def unit(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        return dx / length, dy / length

    before, after = [], []
    for i in range(n):
        prev_p, curr, next_p = points[i - 1], points[i], points[(i + 1) % n]
        ux, uy = unit(curr, prev_p)
        before.append((curr[0] + ux * radius, curr[1] + uy * radius))
        ux, uy = unit(curr, next_p)
        after.append((curr[0] + ux * radius, curr[1] + uy * radius))

    parts = [f"M {before[0][0]:.1f},{before[0][1]:.1f}"]
    for i in range(n):
        parts.append(f"Q {points[i][0]:.1f},{points[i][1]:.1f} {after[i][0]:.1f},{after[i][1]:.1f}")
        parts.append(f"L {before[(i + 1) % n][0]:.1f},{before[(i + 1) % n][1]:.1f}")
    parts.append("Z")
    return " ".join(parts)


_BASEPATH_D = _rounded_corner_path([_HOME, _FIRST, _SECOND, _THIRD], radius=45)

# (depth-chart position code, on-field label, x%, y%) — coordinates place
# each card over the field SVG above. Infielders sit on/near their base;
# outfielders are pulled in close to the infield, still inside the fence
# arc (the arc dips as low as y=115 in straightaway center).
_DIAMOND_POSITIONS = [
    ("CF", "CF", 50, 34),
    ("LF", "LF", 28, 40),
    ("RF", "RF", 72, 40),
    ("2B", "2B", 61, 61),
    ("SS", "SS", 39, 61),
    ("1B", "1B", 75, 73),
    ("3B", "3B", 25, 73),
    ("SP", "P", 50, 73),
    ("C", "C", 50, 92),
]

# Alternating light/dark stripes (mowed-grass texture), tiled behind the
# field markings.
_GRASS_PATTERN = (
    "<pattern id='grassStripes' patternUnits='userSpaceOnUse' width='600' height='48' patternTransform='rotate(45)'>"
    "<rect width='600' height='48' fill='#2F6B3A' />"
    "<rect width='600' height='24' fill='#336F3D' />"
    "</pattern>"
)

_DIAMOND_FIELD_SVG = (
    "<svg viewBox='0 0 600 600' preserveAspectRatio='none' "
    "style='position:absolute;top:0;left:0;width:100%;height:100%;z-index:0'>"
    f"<defs>{_GRASS_PATTERN}</defs>"
    "<rect x='0' y='0' width='600' height='600' fill='url(#grassStripes)' />"
    f"<path d='M{_FOUL_LEFT_END[0]},{_FOUL_LEFT_END[1]} Q300,-30 {_FOUL_RIGHT_END[0]},{_FOUL_RIGHT_END[1]}' "
    "fill='none' stroke='#FAFAFA' stroke-width='4' opacity='0.85' />"
    f"<line x1='{_HOME[0]}' y1='{_HOME[1]}' x2='{_FOUL_LEFT_END[0]}' y2='{_FOUL_LEFT_END[1]}' "
    "stroke='#FAFAFA' stroke-width='3' opacity='0.85' />"
    f"<line x1='{_HOME[0]}' y1='{_HOME[1]}' x2='{_FOUL_RIGHT_END[0]}' y2='{_FOUL_RIGHT_END[1]}' "
    "stroke='#FAFAFA' stroke-width='3' opacity='0.85' />"
    f"<circle cx='{_HOME[0]}' cy='{_HOME[1]}' r='70' fill='#B8895F' />"
    f"<path d='{_BASEPATH_D}' fill='none' stroke='#B8895F' stroke-width='34' stroke-linejoin='round' />"
    f"<circle cx='{_MOUND[0]}' cy='{_MOUND[1]}' r='42' fill='#B8895F' />"
    f"<circle cx='{_MOUND[0]}' cy='{_MOUND[1]}' r='13' fill='#C9A578' stroke='#FAFAFA' stroke-width='2' />"
    f"<rect x='{_FIRST[0] - 7}' y='{_FIRST[1] - 7}' width='14' height='14' fill='#FAFAFA' transform='rotate(45 {_FIRST[0]} {_FIRST[1]})' />"
    f"<rect x='{_SECOND[0] - 7}' y='{_SECOND[1] - 7}' width='14' height='14' fill='#FAFAFA' transform='rotate(45 {_SECOND[0]} {_SECOND[1]})' />"
    f"<rect x='{_THIRD[0] - 7}' y='{_THIRD[1] - 7}' width='14' height='14' fill='#FAFAFA' transform='rotate(45 {_THIRD[0]} {_THIRD[1]})' />"
    f"<rect x='{_HOME[0] - 8}' y='{_HOME[1] - 8}' width='16' height='16' fill='#FAFAFA' transform='rotate(45 {_HOME[0]} {_HOME[1]})' />"
    "</svg>"
)


def baseball_diamond(starters: dict, team_color: str) -> str:
    """HTML+SVG baseball diamond showing each defensive position's current
    starter (photo + name), from db.load_depth_chart(). `starters` maps a
    depth-chart position code ("SP", "C", "1B", ...) to {"name", "mlbID"};
    a position with no data just renders as a "TBD" placeholder card."""
    cards = []
    for key, label, x, y in _DIAMOND_POSITIONS:
        player = starters.get(key)
        if player:
            name = player["name"]
            photo_html = (
                f"<img src='{headshot_url(player['mlbID'], width=120)}' "
                f"style='width:56px;height:56px;border-radius:50%;object-fit:cover;"
                f"border:2px solid {team_color};box-shadow:0 2px 6px rgba(0,0,0,0.5)' />"
            )
        else:
            name = "TBD"
            photo_html = (
                f"<div style='width:56px;height:56px;border-radius:50%;background:#4A5266;"
                f"border:2px solid {team_color};display:flex;align-items:center;justify-content:center;"
                f"font-size:0.7rem;color:#FAFAFA;margin:0 auto'>?</div>"
            )
        cards.append(
            f"<div style='position:absolute;left:{x}%;top:{y}%;transform:translate(-50%,-50%);"
            f"text-align:center;z-index:1;width:90px'>"
            f"{photo_html}"
            f"<div style='margin-top:4px;font-size:0.75rem;font-weight:700;color:#FAFAFA;"
            f"text-shadow:0 1px 3px rgba(0,0,0,0.8);overflow-wrap:break-word'>{name}</div>"
            f"<div style='font-size:0.65rem;color:#D8DEE9;text-shadow:0 1px 3px rgba(0,0,0,0.8)'>{label}</div>"
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


def radar_chart(categories, values_a, values_b, name_a, name_b, color_a="#4C9F70", color_b="#3B82F6"):
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
