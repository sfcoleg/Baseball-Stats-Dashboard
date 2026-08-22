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
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nhl import db as ndb
from nhl import style as nstyle
from nhl import teams as nteams

st.set_page_config(page_title="NHL | Diamond Metrics", layout="wide")
st.title("NHL")
st.caption(
    "Skater and goalie stats, standings, live scores, head-to-head comparisons, shot maps, and a "
    "trained game-odds model — built on the same free NHL and MoneyPuck data as the rest of the site."
)

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
                "<span style='background-color:#D32F2F;color:#FFFFFF;padding:1px 8px;"
                f"border-radius:6px;font-weight:700;font-size:0.68rem'>LIVE</span>"
                f"<span style='color:#9AA3B5;font-size:0.72rem;margin-left:6px'>{'Period ' + str(period) if period else ''}</span>"
            )
        elif started:
            status_html = "<span style='color:#9AA3B5;font-size:0.72rem'>Final</span>"
        else:
            status_html = "<span style='color:#9AA3B5;font-size:0.72rem'>Scheduled</span>"
        card_html = (
            "<div style='flex:0 0 auto;width:160px;background-color:#1B243866;border-radius:10px;"
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

st.divider()


def _headshot(player_id, team_abbr) -> str:
    return f"https://assets.nhle.com/mugs/nhl/{season}{season + 1}/{team_abbr}/{int(player_id)}.png"


def _headliner_card(label, name, player_id, team_abbr, stat_line):
    color = nteams.color_for_abbr(team_abbr)
    st.markdown(
        f"<div style='display:flex;align-items:flex-start;gap:12px'>"
        f"<img src='{_headshot(player_id, team_abbr)}' style='width:64px;height:64px;border-radius:10px;"
        f"object-fit:cover;object-position:center 15%;flex-shrink:0;background:#1A1F2E' />"
        f"<div style='flex:1;min-width:0'>"
        f"<div style='color:#9AA3B5;font-size:0.85rem'>{label}</div>"
        f"<div style='font-size:1.15rem;font-weight:700;line-height:1.3'>"
        f"<a href='{nstyle.player_link(player_id, season)}' target='_self' style='color:inherit;"
        f"text-decoration:none'>{name}</a> "
        f"<span style='background-color:{color}66;color:#FAFAFA;padding:2px 9px;border-radius:8px;"
        f"font-size:0.65em;vertical-align:middle;font-weight:600'>{team_abbr}</span></div>"
        f"<div style='margin-top:6px'><span style='background-color:#3B4A8244;color:#93C5FD;padding:3px 10px;"
        f"border-radius:8px;font-weight:600;font-size:0.9rem'>{stat_line}</span></div>"
        "</div></div>",
        unsafe_allow_html=True,
    )


# --- Daily milestones (yesterday's hat tricks, shutouts, milestones) ----
yesterday = ndb.today_pacific() - timedelta(days=1)
daily_milestones = ndb.get_daily_milestones(yesterday.isoformat(), season, mtime)

if daily_milestones:
    style.colored_header("Milestones", "headliners")
    st.caption(f"Notable achievements from {yesterday.strftime('%B %-d')}'s games.")
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
qualified_goalies = goalies[goalies["gamesPlayed"] >= 20]  # also used by Team Snapshot below

if season == latest_season:
    has_recent_skaters = ndb.top_recent_skater("day", season, mtime) is not None
    has_recent_goalies = ndb.top_recent_goalie("day", season, mtime) is not None

    if has_recent_skaters:
        style.colored_header("Skater Headliners", "batting")
        h1, h2, h3 = st.columns(3)
        for col, period, label in [(h1, "day", "Hot Yesterday"), (h2, "week", "Hot This Week"), (h3, "month", "Hot This Month")]:
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
        for col, period, label in [(g1, "day", "Hot Yesterday"), (g2, "week", "Hot This Week"), (g3, "month", "Hot This Month")]:
            with col:
                with st.container(border=True):
                    top = ndb.top_recent_goalie(period, season, mtime)
                    if top is None:
                        st.caption(label)
                        st.markdown("Not enough games yet")
                    elif period == "day":
                        stat_line = f"{int(top['saves'])} saves, {int(top['goalsAgainst'])} GA"
                        _headliner_card(label, top["goalieFullName"], top["playerId"], top["Tm"], stat_line)
                    else:
                        stat_line = f"{top['savePct']:.1f} SV% in {int(top['games'])} GP"
                        _headliner_card(label, top["goalieFullName"], top["playerId"], top["Tm"], stat_line)

    if has_recent_skaters or has_recent_goalies:
        st.divider()


# --- Top 10 goal scorers chart -------------------------------------------
style.colored_header("Top 10 Goal Leaders", "chart")
top10_goals = skaters.sort_values("goals", ascending=False).head(10).iloc[::-1]
g_min, g_max = top10_goals["goals"].min(), top10_goals["goals"].max()
color_floor = g_min - (g_max - g_min) * 0.6 - 1
fig = px.bar(
    top10_goals, x="goals", y="skaterFullName", orientation="h",
    color="goals", color_continuous_scale="Blues", range_color=[color_floor, g_max], text="goals",
    labels={"goals": "Goals", "skaterFullName": ""},
)
fig.update_layout(
    showlegend=False, coloraxis_showscale=False, height=400, margin=dict(l=0, r=0, t=10, b=0),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA",
)
st.plotly_chart(fig, use_container_width=True)

st.divider()


# --- Team snapshot ----------------------------------------------------
style.colored_header("Team Snapshot", "chart")
qualified_skaters = skaters[skaters["gamesPlayed"] >= 20]
team_cf = qualified_skaters.groupby("Tm", observed=True)["satPercentage"].mean().round(1).reset_index().sort_values("satPercentage", ascending=False)
team_svpct = qualified_goalies.groupby("Tm", observed=True)["savePct"].mean().round(1).reset_index().sort_values("savePct", ascending=False)

tcol1, tcol2 = st.columns(2)
with tcol1:
    st.caption("Average skater CF% by team (20+ GP)")
    fig = px.bar(team_cf, x="Tm", y="satPercentage", color="Tm",
                 color_discrete_map={t: nteams.color_for_abbr(t) for t in team_cf["Tm"]},
                 labels={"satPercentage": "CF%"})
    fig.update_layout(showlegend=False, height=380, margin=dict(l=0, r=0, t=10, b=0),
                       paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA", xaxis_title=None)
    st.plotly_chart(fig, use_container_width=True)
with tcol2:
    st.caption("Average goalie SV% by team (20+ GP)")
    fig = px.bar(team_svpct, x="Tm", y="savePct", color="Tm",
                 color_discrete_map={t: nteams.color_for_abbr(t) for t in team_svpct["Tm"]},
                 labels={"savePct": "SV%"})
    fig.update_layout(showlegend=False, height=380, margin=dict(l=0, r=0, t=10, b=0),
                       paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA", xaxis_title=None)
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
                    f"<tr style='border-top:1px solid #4A5266'>"
                    f"<td style='padding:4px 8px'><span style='background-color:{nteams.color_for_abbr(r.Team)}66;"
                    f"color:#FAFAFA;padding:2px 8px;border-radius:6px;font-weight:700'>{r.Team}</span></td>"
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


# --- Points Leaders card grid --------------------------------------------
style.colored_header(f"{ndb.season_label(season)} Points Leaders", "batting")
top = skaters.sort_values("points", ascending=False).head(10)
cards = ""
for i, (_, p) in enumerate(top.iterrows()):
    tm = p["Tm"]
    color = nteams.color_for_abbr(tm)
    headshot = _headshot(p["playerId"], tm)
    cards += (
        f"<div style='position:relative;text-align:center;background:linear-gradient(180deg,{color}26,transparent);"
        f"border:1px solid {color}55;border-radius:12px;padding:14px 8px 10px'>"
        f"<div style='position:absolute;top:6px;left:8px;background:{color};color:#0E1117;"
        f"font-weight:800;font-size:0.75rem;width:20px;height:20px;border-radius:50%;"
        f"display:flex;align-items:center;justify-content:center'>{i + 1}</div>"
        f"<img src='{headshot}' style='width:72px;height:72px;border-radius:50%;object-fit:cover;"
        f"object-position:center 15%;border:2px solid {color};background:#1A1F2E' />"
        f"<div style='margin-top:8px;font-weight:700;font-size:0.92rem;line-height:1.2'>"
        f"<a href='{nstyle.player_link(p['playerId'], season)}' target='_self' "
        f"style='color:#FAFAFA;text-decoration:none'>{p['skaterFullName']}</a></div>"
        f"<span style='display:inline-block;margin-top:4px;background-color:{color}66;color:#FAFAFA;"
        f"padding:1px 8px;border-radius:6px;font-size:0.75rem;font-weight:700'>{tm}</span>"
        f"<div style='margin-top:6px;font-size:1.4rem;font-weight:800;color:{color}'>{int(p['points'])}"
        f"<span style='font-size:0.7rem;font-weight:600;color:#9AA3B5'> PTS</span></div>"
        "</div>"
    )
st.markdown(
    "<div style='display:grid;grid-template-columns:repeat(auto-fit, minmax(120px, 1fr));gap:12px'>" + cards + "</div>",
    unsafe_allow_html=True,
)

st.divider()


# --- Full leader tables -------------------------------------------------
style.colored_header("Skater Leaders (min 20 GP)", "batting")
qualified = skaters[skaters["gamesPlayed"] >= 20].sort_values("points", ascending=False)
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

style.colored_header("Goalie Leaders (min 20 GP)", "pitching")
qualified_g = goalies[goalies["gamesPlayed"] >= 20].sort_values("wins", ascending=False)
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
