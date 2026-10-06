"""NHL home — landing page for the hockey side, mirroring the MLB Home
page's shape (today's slate strip, milestones, headliners, leader chart,
team snapshot, standings snapshot, leader tables) with NHL's own data.
The sport switcher in the sidebar (see sidebar.render_sport_switcher)
lands here; every NHL page lives under a url_path starting with "nhl" so
the active sport can be derived from the URL alone."""
import sys
from datetime import timedelta
from pathlib import Path

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nhl import db as ndb
from nhl import style as nstyle
from nhl import teams as nteams

st.set_page_config(page_title="NHL | Diamond Metrics", layout="wide")
st.title("NHL")

mtime = ndb.nhl_db_mtime()
seasons = ndb.skater_seasons(mtime)
if not seasons:
    st.info("No NHL data yet — run `python ingest/nhl_refresh.py` to backfill.")
    st.stop()


# --- Today's slate strip ----------------------------------------------
def _todays_games_strip():
    """Every game scheduled today as a horizontally-scrolling row of small
    cards — a quick glance at the whole slate without leaving Home, same
    idea as the MLB Home page's strip. Full detail stays on Today's Games."""
    games = ndb.load_schedule_for_date(ndb.today_pacific().strftime("%Y-%m-%d"))
    if not games:
        return

    def _team_row(logo, abbr, score):
        logo_html = f"<img src='{logo}' style='height:22px;width:22px;object-fit:contain;margin-right:6px;flex-shrink:0'>" if logo else ""
        return (
            "<div style='display:flex;align-items:center;justify-content:space-between;padding:2px 0'>"
            f"<div style='display:flex;align-items:center;overflow:hidden'>{logo_html}"
            f"<span style='font-size:0.85rem;white-space:nowrap'>{abbr}</span></div>"
            f"<span style='font-weight:700;font-size:0.95rem;margin-left:8px;flex-shrink:0'>{score}</span>"
            "</div>"
        )

    cards = []
    for g in games:
        away, home = g["awayTeam"], g["homeTeam"]
        state = g.get("gameState")
        started = state not in ("FUT", "PRE")
        is_live = state in ("LIVE", "CRIT")
        away_txt = str(away.get("score", "-")) if started else "-"
        home_txt = str(home.get("score", "-")) if started else "-"
        if is_live:
            period = (g.get("periodDescriptor") or {}).get("number")
            status_html = (
                "<span style='background-color:var(--dm-red);color:#FFFFFF;padding:1px 8px;"
                f"border-radius:6px;font-weight:700;font-size:0.68rem'>LIVE</span>"
                f"<span style='color:var(--dm-dim);font-size:0.72rem;margin-left:6px'>{'Period ' + str(period) if period else ''}</span>"
            )
        elif started:
            status_html = "<span style='color:var(--dm-dim);font-size:0.72rem'>Final</span>"
        else:
            status_html = "<span style='color:var(--dm-dim);font-size:0.72rem'>Scheduled</span>"
        card_html = (
            "<div style='flex:0 0 auto;width:160px;background-color:var(--dm-surface-mute);border-radius:10px;"
            "padding:10px 12px;margin-right:10px'>"
            f"<div style='margin-bottom:4px'>{status_html}</div>"
            + _team_row(away.get("logo"), away["abbrev"], away_txt)
            + _team_row(home.get("logo"), home["abbrev"], home_txt)
            + "</div>"
        )
        cards.append((0 if is_live else 1, card_html))
    cards.sort(key=lambda c: c[0])
    st.markdown(
        "<div style='display:flex;overflow-x:auto;padding-bottom:8px'>" + "".join(h for _, h in cards) + "</div>",
        unsafe_allow_html=True,
    )
    st.divider()


_todays_games_strip()

season = st.selectbox("Season", seasons, format_func=ndb.season_label)
latest_season = seasons[0]
skaters = ndb.load_skaters(season, mtime)
goalies = ndb.load_goalies(season, mtime)
skaters["Tm"] = skaters["teamAbbrevs"].map(nteams._primary)
goalies["Tm"] = goalies["teamAbbrevs"].map(nteams._primary)

# Everything below is THIS season's own numbers, however few games in. The
# leaderboards used to fall back to last season's finals until a few weeks
# had passed; they now stay on the current season, and the "minimum games"
# bars scale with how many games have actually been played (see _min_gp).
season_gp = int(skaters["gamesPlayed"].max()) if not skaters.empty else 0


def _min_gp(df, cap: int = 20) -> int:
    """Games-played floor for a leaderboard: the usual `cap` once the season
    is old enough, half of the busiest player's games before that (so week
    one still has a table), and never below 1."""
    most = int(df["gamesPlayed"].max()) if not df.empty else 0
    return max(1, min(cap, (most + 1) // 2))


leaderboard_skaters, leaderboard_goalies = skaters, goalies

st.divider()


def _headshot(player_id, team_abbr, for_season: int | None = None) -> str:
    yr = for_season if for_season is not None else season
    return f"https://assets.nhle.com/mugs/nhl/{yr}{yr + 1}/{team_abbr}/{int(player_id)}.png"


def _headliner_card(label, name, player_id, team_abbr, stat_line):
    color = nteams.color_for_abbr(team_abbr)
    st.markdown(
        # Bottom padding so the stat pill never sits against the card's edge.
        f"<div style='display:flex;align-items:flex-start;gap:12px;padding:2px 0 12px'>"
        f"<img src='{_headshot(player_id, team_abbr)}' style='width:64px;height:64px;border-radius:10px;"
        f"object-fit:cover;object-position:center 15%;flex-shrink:0;background:#1A1F2E' />"
        f"<div style='flex:1;min-width:0'>"
        f"<div style='color:var(--dm-dim);font-size:0.85rem'>{label}</div>"
        f"<div style='font-size:1.15rem;font-weight:700;line-height:1.3'>"
        f"<a href='{nstyle.player_link(player_id, season)}' target='_self' style='color:inherit;"
        f"text-decoration:none'>{name}</a> "
        f"<span style='background-color:{color}66;color:var(--dm-text);padding:2px 9px;border-radius:8px;"
        f"font-size:0.65em;vertical-align:middle;font-weight:600'>{team_abbr}</span></div>"
        f"<div style='margin-top:6px'><span style='background-color:var(--dm-blue-soft);color:var(--dm-blue-text);padding:3px 10px;"
        f"border-radius:8px;font-weight:600;font-size:0.9rem'>{stat_line}</span></div>"
        "</div></div>",
        unsafe_allow_html=True,
    )


# --- Daily milestones (yesterday's hat tricks, shutouts, milestones) ----
# Gated the same way the Headliners section below is: get_daily_milestones
# checks season-total thresholds against `season`'s own totals, so
# browsing a past season would compare yesterday's real game log against
# THAT season's goal/point totals instead of the current one — a bogus
# "crossed 40 goals" reading, not just stale data.
yesterday = ndb.today_pacific() - timedelta(days=1)
# Newest day we have game logs for — normally yesterday. When the nightly
# refresh is late it is older, and the sections below still show it (labelled
# with its date) instead of disappearing. getattr: this page can be re-read
# before an updated nhl/db.py has been.
log_day = (getattr(ndb, "last_logged_day", lambda: None)() or yesterday)
day_word = "Yesterday" if log_day >= yesterday else log_day.strftime("%b %-d")
daily_milestones = ndb.get_daily_milestones(log_day.isoformat(), season, mtime) if season == latest_season else []

if daily_milestones:
    style.colored_header("Milestones", "headliners")
    # A fresh st.columns(4) per row of 4 (not one st.columns(4) reused via
    # i % 4) — columns() stacks column-major on mobile, so reusing one
    # would read item 0, 4, 8, 12, then 1, 5, 9... A new call per row means
    # each column ever holds exactly one item, so stacking can't reorder it.
    for row_start in range(0, len(daily_milestones), 4):
        row_items = daily_milestones[row_start:row_start + 4]
        mcols = st.columns(4)
        for col, m in zip(mcols, row_items):
            with col:
                with st.container(border=True):
                    _headliner_card(m["category"], m["name"], m["playerId"], m["Tm"], m["text"])
    st.divider()


# --- Headliners (hot yesterday / this week / this month) ----------------
# Only rendered when there's real recent game data — during the offseason
# there's nothing to be "hot" from, and six blank "No games yet" cards
# read as broken rather than intentional. "day" is the lowest-bar presence
# check: if even that has nothing, week/month (wider windows) won't either.

if season == latest_season:
    has_recent_skaters = ndb.top_recent_skater("day", season, mtime) is not None
    has_recent_goalies = ndb.top_recent_goalie("day", season, mtime) is not None

    if has_recent_skaters:
        style.colored_header("Skater Headliners", "batting")
        h1, h2, h3 = st.columns(3)
        for col, period, label in [(h1, "day", f"Hot {day_word}"), (h2, "week", "Hot This Week"), (h3, "month", "Hot This Month")]:
            with col:
                with st.container(border=True):
                    top = ndb.top_recent_skater(period, season, mtime)
                    if top is None:
                        st.caption(label)
                        st.markdown("Not enough games yet")
                    elif period == "day":
                        stat_line = f"{int(top['goals'])} G, {int(top['assists'])} A, {int(top['points'])} PTS"
                        _headliner_card(label, top["skaterFullName"], top["playerId"], top["Tm"], stat_line)
                    else:
                        stat_line = f"{int(top['points'])} PTS ({int(top['goals'])} G, {int(top['assists'])} A) in {int(top['games'])} GP"
                        _headliner_card(label, top["skaterFullName"], top["playerId"], top["Tm"], stat_line)

    if has_recent_goalies:
        style.colored_header("Goalie Headliners", "pitching")
        g1, g2, g3 = st.columns(3)
        for col, period, label in [(g1, "day", f"Hot {day_word}"), (g2, "week", "Hot This Week"), (g3, "month", "Hot This Month")]:
            with col:
                with st.container(border=True):
                    top = ndb.top_recent_goalie(period, season, mtime)
                    if top is None:
                        st.caption(label)
                        st.markdown("Not enough games yet")
                    else:
                        # Saves computed here from the two raw columns every
                        # window carries, rather than read off a derived one.
                        saves = int(top["shotsAgainst"]) - int(top["goalsAgainst"])
                        if period == "day":
                            stat_line = f"{saves} saves, {int(top['goalsAgainst'])} GA"
                        elif period == "week":
                            stat_line = f"{saves} saves, {int(top['goalsAgainst'])} GA in {int(top['games'])} GP"
                        else:
                            stat_line = f"{top['savePct']:.1f} SV% in {int(top['games'])} GP"
                        _headliner_card(label, top["goalieFullName"], top["playerId"], top["Tm"], stat_line)

    if has_recent_skaters or has_recent_goalies:
        st.divider()


# --- Points leaders, split into goals and assists ------------------------
# Each bar is a stacked pair (goals, then assists), so the split is the real
# ratio by construction. Goals / Assists are on-off toggles that re-rank the
# chart: both on = top 10 by total points, one on = top 10 by that stat alone.
# Replaces the old "Top 10 Goal Leaders" chart, which this covers.
_GOAL_COLOR, _ASSIST_COLOR = "#2E86DE", "#F2A33A"


@st.fragment
def _points_leaders_chart():
    style.colored_header(f"{ndb.season_label(season)} Points Leaders", "chart")
    picked = st.pills("Show", ["Goals", "Assists"], selection_mode="multi",
                      default=["Goals", "Assists"], key="nhl_home_pts_stats",
                      label_visibility="collapsed")
    show_goals = "Goals" in picked or not picked   # nothing picked == both
    show_assists = "Assists" in picked or not picked
    if show_goals and show_assists:
        rank_col, unit = "points", "PTS"
    elif show_goals:
        rank_col, unit = "goals", "G"
    else:
        rank_col, unit = "assists", "A"

    pool = skaters.dropna(subset=["points"])
    pool = pool[pool[rank_col] > 0]
    other = "assists" if rank_col == "goals" else "goals"
    top = (pool.sort_values([rank_col, other, "skaterFullName"], ascending=[False, False, True])
           .head(10).iloc[::-1])   # reversed: Plotly draws the first category at the bottom
    if top.empty:
        st.caption("No scoring yet this season.")
        return

    text_color = nstyle.session_chart_text_color()
    fig = go.Figure()
    for col, label, color, ink, on in (("goals", "Goals", _GOAL_COLOR, "#FFFFFF", show_goals),
                                       ("assists", "Assists", _ASSIST_COLOR, "#1A1200", show_assists)):
        if not on:
            continue
        vals = top[col].astype(int)
        fig.add_trace(go.Bar(
            x=vals, y=top["skaterFullName"], orientation="h", name=label, marker_color=color,
            text=[str(v) if v else "" for v in vals], textposition="inside", insidetextanchor="middle",
            textfont=dict(color=ink, size=13), hovertemplate=f"%{{y}}: %{{x}} {label.lower()}<extra></extra>",
        ))
    fig.add_trace(go.Scatter(
        x=top[rank_col], y=top["skaterFullName"], mode="text", showlegend=False, hoverinfo="skip",
        text=[f"  {int(v)} {unit}" for v in top[rank_col]], textposition="middle right",
        textfont=dict(color=text_color, size=13), cliponaxis=False,
    ))
    fig.update_layout(
        barmode="stack", height=420, margin=dict(l=0, r=70, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=text_color,
        # The legend only names the colours — the pills above do the toggling,
        # because hiding a bar here wouldn't re-rank the players.
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, traceorder="normal",
                    font=dict(color=text_color), itemclick=False, itemdoubleclick=False),
        xaxis=dict(dtick=1 if top[rank_col].max() <= 10 else None, title=None, tickfont=dict(color=text_color)),
        yaxis=dict(title=None, tickfont=dict(color=text_color)),
    )
    st.plotly_chart(fig, use_container_width=True)


_points_leaders_chart()
st.divider()


# --- Team snapshot ----------------------------------------------------
style.colored_header("Team Snapshot", "chart")
_sk_floor, _g_floor = _min_gp(skaters), _min_gp(goalies)
snapshot_qualified_skaters = skaters[skaters["gamesPlayed"] >= _sk_floor]
snapshot_qualified_goalies = goalies[goalies["gamesPlayed"] >= _g_floor]
team_cf = snapshot_qualified_skaters.groupby("Tm", observed=True)["satPercentage"].mean().round(1).reset_index().sort_values("satPercentage", ascending=False)
team_svpct = snapshot_qualified_goalies.groupby("Tm", observed=True)["savePct"].mean().round(1).reset_index().sort_values("savePct", ascending=False)

tcol1, tcol2 = st.columns(2)
with tcol1:
    st.caption(f"Average skater CF% by team ({_sk_floor}+ GP)")
    fig = px.bar(team_cf, x="Tm", y="satPercentage", color="Tm",
                 color_discrete_map={t: nteams.color_for_abbr(t) for t in team_cf["Tm"]},
                 labels={"satPercentage": "CF%"})
    fig.update_layout(showlegend=False, height=380, margin=dict(l=0, r=0, t=10, b=0),
                       paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=nstyle.session_chart_text_color(), xaxis_title=None)
    st.plotly_chart(fig, use_container_width=True)
with tcol2:
    st.caption(f"Average goalie SV% by team ({_g_floor}+ GP)")
    fig = px.bar(team_svpct, x="Tm", y="savePct", color="Tm",
                 color_discrete_map={t: nteams.color_for_abbr(t) for t in team_svpct["Tm"]},
                 labels={"savePct": "SV%"})
    fig.update_layout(showlegend=False, height=380, margin=dict(l=0, r=0, t=10, b=0),
                       paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=nstyle.session_chart_text_color(), xaxis_title=None)
    st.plotly_chart(fig, use_container_width=True)

st.divider()


# --- Standings snapshot (current season only — live data) ---------------
if season == latest_season:
    standings = ndb.load_standings()
    if not standings.empty:
        style.colored_header("Standings", "chart")
        divisions = sorted(standings["divisionName"].dropna().unique())
        div_cols = st.columns(min(len(divisions), 4))
        for i, division in enumerate(divisions):
            with div_cols[i % 4]:
                st.markdown(f"**{division}**")
                div_standings = standings[standings["divisionName"] == division].sort_values("divisionSequence")
                display = div_standings[["teamAbbrev", "wins", "losses"]].rename(
                    columns={"teamAbbrev": "Team", "wins": "W", "losses": "L"}
                )
                rows = "".join(
                    f"<tr style='border-top:1px solid var(--dm-line)'>"
                    f"<td style='padding:4px 8px'><span style='background-color:{nteams.color_for_abbr(r.Team)}66;"
                    f"color:var(--dm-text);padding:2px 8px;border-radius:6px;font-weight:700'>{r.Team}</span></td>"
                    f"<td style='padding:4px 8px;text-align:center'>{r.W}</td>"
                    f"<td style='padding:4px 8px;text-align:center'>{r.L}</td></tr>"
                    for r in display.itertuples()
                )
                st.markdown(
                    f"<table style='width:100%;border-collapse:collapse;font-size:0.85rem'>{rows}</table>",
                    unsafe_allow_html=True,
                )
        st.caption("See the Standings page for points, streaks, and the full picture.")
        st.divider()


# --- Full leader tables -------------------------------------------------
style.colored_header(f"Skater Leaders (min {_sk_floor} GP)", "batting")
qualified = leaderboard_skaters[leaderboard_skaters["gamesPlayed"] >= _sk_floor].sort_values("points", ascending=False)
st.caption(f"Top 50 of {len(qualified)} qualified skaters by points — see the Skaters page for the full filterable list.")
display = qualified.head(50)[["skaterFullName", "Tm", "positionCode", "gamesPlayed", "goals", "assists", "points", "plusMinus"]].reset_index(drop=True)
st.dataframe(
    style.style_stats_table(
        display.rename(columns=ndb.STAT_LABELS),
        higher_better=[ndb.STAT_LABELS[c] for c in ("goals", "assists", "points", "plusMinus")],
        team_col="Tm", team_color_fn=nteams.color_for_abbr,
    ),
    use_container_width=True, height=400,
)

style.colored_header(f"Goalie Leaders (min {_g_floor} GP)", "pitching")
qualified_g = leaderboard_goalies[leaderboard_goalies["gamesPlayed"] >= _g_floor].sort_values("wins", ascending=False)
st.caption(f"Top of {len(qualified_g)} qualified goalies by wins — see the Goalies page for the full filterable list.")
display_g = qualified_g[["goalieFullName", "Tm", "gamesPlayed", "wins", "losses", "otLosses", "goalsAgainstAverage", "savePct", "shutouts"]].reset_index(drop=True)
st.dataframe(
    style.style_stats_table(
        display_g.rename(columns=ndb.STAT_LABELS),
        higher_better=[ndb.STAT_LABELS[c] for c in ("wins", "savePct", "shutouts")],
        lower_better=[ndb.STAT_LABELS["goalsAgainstAverage"]],
        team_col="Tm", team_color_fn=nteams.color_for_abbr,
        precision={ndb.STAT_LABELS["goalsAgainstAverage"]: "{:.2f}", ndb.STAT_LABELS["savePct"]: "{:.1f}"},
    ),
    use_container_width=True, height=400,
)

st.info("Use the pages in the sidebar for filterable Skaters, Goalies, Compare, and Shot Maps.")
