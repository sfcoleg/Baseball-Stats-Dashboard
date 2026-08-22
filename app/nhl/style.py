"""NHL-side display helpers — the hockey analog of app/style.py. Kept
separate since headshot/logo CDNs, routes, and chart shapes are all
different from the MLB side."""
import pandas as pd
import plotly.graph_objects as go

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
            f"<sup style='color:#9AA3B5;font-weight:700;margin-left:2px' title='{clinch_title}'>{clinch}</sup>"
            if isinstance(clinch, str) and clinch else ""
        )
        team_cell = (
            f"<td style='padding:5px 10px'><a href='{team_link(row['Team'])}' target='_self' "
            f"style='background-color:{color}66;color:#FAFAFA;padding:2px 9px;border-radius:6px;"
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
            "<tr style='border-top:1px solid #4A5266'>"
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
        "<thead><tr style='color:#9AA3B5;text-align:center'>"
        "<th style='padding:5px 10px;text-align:left'>Team</th>"
        "<th style='padding:5px 10px'>GP</th><th style='padding:5px 10px'>W</th>"
        "<th style='padding:5px 10px'>L</th><th style='padding:5px 10px'>OTL</th>"
        "<th style='padding:5px 10px'>PTS</th><th style='padding:5px 10px' title='Regulation + OT wins (tiebreaker)'>ROW</th>"
        "<th style='padding:5px 10px'>GD</th><th style='padding:5px 10px'>Streak</th>"
        "<th style='padding:5px 10px'>L10</th>" + header_extra +
        "</tr></thead><tbody>" + rows + "</tbody></table>"
    )


_RESULT_STYLE = {
    "goal": ("#22C55E", "star", 13),
    "shot-on-goal": ("#60A5FA", "circle", 7),
    "missed-shot": ("#9AA3B5", "circle", 5),
    "blocked-shot": ("#F59E0B", "x", 6),
}
_RESULT_LABELS = {"goal": "Goal", "shot-on-goal": "Shot on net", "missed-shot": "Missed", "blocked-shot": "Blocked"}


def rink_outline(fig: "go.Figure") -> "go.Figure":
    """Draws a simplified half-length-normalized NHL rink (200x85 ft, center
    ice at 0,0) as plotly shapes: boundary, center/blue/goal lines, center
    circle, and both goal creases. Shots are normalized so every shot
    attacks the right-hand goal (see ingest/nhl_shots.py's
    _normalize_side) — the rink is drawn full-length so that clustering is
    visible against the whole sheet."""
    line = dict(color="rgba(154,163,181,0.5)", width=1.5)
    fig.add_shape(type="rect", x0=-100, x1=100, y0=-42.5, y1=42.5, line=line)
    fig.add_shape(type="line", x0=0, x1=0, y0=-42.5, y1=42.5, line=dict(color="rgba(239,68,68,0.5)", width=1.5))
    for x in (-25, 25):
        fig.add_shape(type="line", x0=x, x1=x, y0=-42.5, y1=42.5, line=dict(color="rgba(96,165,250,0.5)", width=1.5))
    for x in (-89, 89):
        fig.add_shape(type="line", x0=x, x1=x, y0=-42.5, y1=42.5, line=line)
        crease_dir = 1 if x > 0 else -1
        fig.add_shape(
            type="circle", x0=x - 6 * crease_dir, x1=x + 6 * crease_dir, y0=-4, y1=4,
            line=dict(color="rgba(96,165,250,0.35)", width=1),
        )
    fig.add_shape(type="circle", x0=-15, x1=15, y0=-15, y1=15, line=line)
    return fig


def shot_map_chart(shots: pd.DataFrame, name: str) -> "go.Figure":
    """One player's or team's shots on the normalized rink, colored/shaped
    by result. `shots` needs x/y/result columns (see ingest/nhl_shots.py)."""
    fig = go.Figure()
    rink_outline(fig)
    for result, (color, symbol, size) in _RESULT_STYLE.items():
        sub = shots[shots["result"] == result]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["x"], y=sub["y"], mode="markers", name=f"{_RESULT_LABELS[result]} ({len(sub)})",
            marker=dict(color=color, symbol=symbol, size=size, line=dict(width=1, color="#1A1F2E")),
            hoverinfo="skip",
        ))
    fig.update_layout(
        title=name, height=450, margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(20,24,36,0.4)", font_color="#FAFAFA",
        xaxis=dict(range=[-101, 101], visible=False, scaleanchor="y", scaleratio=1),
        yaxis=dict(range=[-43.5, 43.5], visible=False),
        legend=dict(orientation="h", yanchor="bottom", y=-0.08, x=0),
    )
    return fig
