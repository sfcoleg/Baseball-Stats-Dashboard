import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent))
import db
import localstorage_bridge
import prefs
import style
import teams

st.set_page_config(page_title="Diamond Metrics", layout="wide")

# The actual localStorage->query-param redirect for site-wide prefs (default
# season, favorite team — see prefs.py) has to fire from within a routed
# page's own script, not main.py (see localstorage_bridge.py's docstring).
# Fired here since Home is where most sessions land first, so the saved
# default season is already in session_state by the time someone reaches
# another page. register() was already called once in main.py — calling it
# again here is a harmless no-op (plain dict assignment, not a render).
localstorage_bridge.register("prefs", prefs.STORAGE_KEY)

# db.today_pacific() is the one source of truth for "what day is it"
# anywhere on this page — see its docstring for why plain date.today()
# is wrong on Streamlit Community Cloud (UTC servers).
today_pacific = db.today_pacific


# Temporary: All-Star week has no regular-season games, so the normal "Hot
# Yesterday" query has nothing to show on the day right after the Home Run
# Derby / All-Star Game. Keyed by the Pacific date this page is being
# VIEWED on (i.e. "today"), since "yesterday" is computed from that.
# Remove this whole block once the 2026 All-Star break has passed.
HOT_YESTERDAY_OVERRIDES = {
    "2026-07-14": {
        "batting": {"name": "Jordan Walker", "note": "2026 Home Run Derby champion"},
        "pitching": "No pitcher pitched yesterday — it's All-Star week.",
    },
}

if not db.DB_PATH.exists():
    st.error(
        "No data found yet. Run `./venv/bin/python ingest/refresh_data.py` "
        "from the project folder first to fetch stats."
    )
    st.stop()


def _todays_games_strip():
    """Every game scheduled today as a horizontally-scrolling row of small
    cards (logo/name/score per team) — a quick glance at the whole slate
    without leaving Home, full detail (odds, box scores) stays on the
    Today's Games page. Reuses the same todays_games/live_scores data that
    page already fetches."""
    games = db.load_todays_games(db.db_mtime(), db.today_pacific().isoformat())
    if games.empty:
        return
    live_scores = db.load_live_scores(games.iloc[0]["date"])
    logo_season = today_pacific().year

    def _logo(abbr):
        team_id = teams.team_id_for_abbr(teams.normalize_mlb_abbr(abbr))
        return style.team_logo_for_season(teams.normalize_mlb_abbr(abbr), team_id, logo_season) if team_id else None

    def _team_row(logo, name, score, won=False):
        logo_html = (
            f"<img src='{logo}' style='height:20px;width:20px;object-fit:contain;margin-right:7px;flex-shrink:0'>"
            if logo else ""
        )
        return (
            f"<div class='dm-row{" win" if won else ""}' "
            "style='display:flex;align-items:center;justify-content:space-between;padding:2px 0'>"
            f"<div style='display:flex;align-items:center;overflow:hidden'>{logo_html}"
            f"<span class='dm-team' style='white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>{name}</span></div>"
            f"<span class='dm-score' style='margin-left:8px;flex-shrink:0'>{score}</span>"
            "</div>"
        )

    cards = []
    for _, row in games.iterrows():
        live = live_scores.get(row["game_pk"], {})
        status = live.get("status") or row["status"]
        started = status not in ("Scheduled", "Pre-Game", "Warmup", "Delayed Start", "Postponed")
        is_live = status == "In Progress"
        away_score = live.get("away_score")
        home_score = live.get("home_score")
        away_txt = str(int(away_score)) if started and away_score is not None else "-"
        home_txt = str(int(home_score)) if started and home_score is not None else "-"

        if is_live:
            status_html = (
                f"<span class='live-badge' style='background-color:var(--dm-red);color:#FFFFFF;padding:1px 8px;"
                f"border-radius:6px;font-weight:700;font-size:0.68rem'>LIVE</span>"
                f"<span style='color:var(--dm-dim);font-size:0.72rem;margin-left:6px'>{live.get('inning') or ''}</span>"
            )
        elif started:
            status_html = "<span style='color:var(--dm-dim);font-size:0.72rem'>Final</span>"
        else:
            status_html = "<span style='color:var(--dm-dim);font-size:0.72rem'>Scheduled</span>"

        # Winner is highlighted only once a game is final — mid-game the
        # leader isn't a result yet.
        final = started and not is_live and away_score is not None and home_score is not None
        away_won = bool(final and away_score > home_score)
        home_won = bool(final and home_score > away_score)
        card_html = (
            "<div class='dm-game'>"
            f"<div class='dm-stat'>{status_html}</div>"
            + _team_row(_logo(row["away_abbr"]), row["away_team"], away_txt, away_won)
            + _team_row(_logo(row["home_abbr"]), row["home_team"], home_txt, home_won)
            + "</div>"
        )
        # Live games first (leftmost, no scrolling needed to spot them),
        # then everything else in its original schedule order — Python's
        # sort is stable, so within each group the order is unchanged.
        cards.append((0 if is_live else 1, card_html))

    cards.sort(key=lambda c: c[0])
    st.markdown(
        "<div style='display:flex;overflow-x:auto;padding-bottom:8px'>"
        + "".join(html for _, html in cards) + "</div>",
        unsafe_allow_html=True,
    )
    st.divider()


_MILESTONE_LABELS = {
    "no_hitter_watch": "NO-HITTER WATCH",
    "perfect_watch": "PERFECT GAME WATCH",
    "no_hitter_achieved": "NO-HITTER!",
    "perfect_achieved": "PERFECT GAME!",
    "cycle_watch": "CYCLE WATCH",
    "cycle_achieved": "CYCLE!",
    "four_hr_watch": "4-HR WATCH",
    "four_hr_achieved": "4-HR GAME!",
}
_MILESTONE_ACHIEVED_KINDS = {"no_hitter_achieved", "perfect_achieved", "cycle_achieved", "four_hr_achieved"}


def _milestone_banner(kind, body_html):
    """One banner row. "Watch" kinds (a bid still in progress) render red
    with the pulsing LIVE-badge treatment and vanish the instant the bid
    breaks on the next poll; "achieved" kinds render gold/solid and — since
    db.no_hitter_watch/db.batting_milestone_watch re-derive them from the
    still-queryable final boxscore on every poll rather than storing a
    flag anywhere — keep showing for the rest of the day without any extra
    state to manage."""
    achieved = kind in _MILESTONE_ACHIEVED_KINDS
    color = "#F5B942" if achieved else "#D32F2F"
    badge_class = "" if achieved else "live-badge"
    st.markdown(
        f"<div style='background-color:{color}22;border:1px solid {color}88;border-radius:10px;"
        "padding:12px 16px;margin-bottom:10px;display:flex;align-items:center;gap:12px;flex-wrap:wrap'>"
        f"<span class='{badge_class}' style='background-color:{color};color:var(--dm-surface);padding:3px 10px;"
        f"border-radius:6px;font-weight:700;font-size:0.75rem;flex-shrink:0'>{_MILESTONE_LABELS[kind]}</span>"
        f"<div>{body_html}</div></div>",
        unsafe_allow_html=True,
    )


def _milestone_banners():
    """Same-day milestone banners at the very top of Home: no-hitter/
    perfect-game bids and completions (db.no_hitter_watch), plus cycle and
    4-homer bids and completions (db.batting_milestone_watch). Nothing
    renders at all when there's no bid in progress and nothing achieved
    yet today, so this never takes up space on a normal day."""
    date_str = today_pacific().isoformat()
    pitching_watches = db.no_hitter_watch(date_str)
    batting_watches = db.batting_milestone_watch(date_str)
    if not pitching_watches and not batting_watches:
        return

    for w in pitching_watches:
        pitcher_text = " & ".join(w["pitcher_names"]) if w["combined"] else w["pitcher_names"][0]
        combined_note = " (combined)" if w["combined"] else ""
        line_stats = f"{w['ip_display']} IP, 0 H" + (f", {w['walks']} BB" if w["walks"] else "")
        _milestone_banner(w["kind"], (
            f"<span style='font-weight:700'>{pitcher_text}</span>{combined_note} "
            f"<span style='color:var(--dm-dim)'>({w['pitching_abbr']})</span> — {line_stats} vs {w['opponent']} "
            f"<span style='color:var(--dm-dim)'>· {w['inning'] or 'Final'}</span>"
        ))

    for w in batting_watches:
        if w["kind"] == "cycle_watch":
            detail = f"needs a {w['missing']} for the cycle"
        elif w["kind"] == "cycle_achieved":
            detail = "hit for the cycle"
        elif w["kind"] == "four_hr_watch":
            detail = "has 3 HR, watching for #4"
        else:
            detail = f"hit {w['hr']} home runs"
        _milestone_banner(w["kind"], (
            f"<span style='font-weight:700'>{w['name']}</span> "
            f"<span style='color:var(--dm-dim)'>({w['abbr']})</span> — {detail} vs {w['opponent']} "
            f"<span style='color:var(--dm-dim)'>· {w['inning'] or 'Final'}</span>"
        ))


_milestone_banners()
_todays_games_strip()

seasons = db.get_seasons("batting")
season = st.selectbox("Season", seasons, index=prefs.default_season_index(seasons))

mtime = db.db_mtime()
batting = db.load_batting(season, mtime)
pitching = db.load_pitching(season, mtime)

st.divider()

qualified_batters = batting[batting["PA"] >= db.QUALIFIED_MIN_PA].sort_values("OPS", ascending=False)
qualified_pitchers = pitching[pitching["IP"] >= db.QUALIFIED_MIN_IP].sort_values("ERA", ascending=True)

recent_batting = db.load_recent_batting(season, mtime)
recent_pitching = db.load_recent_pitching(season, mtime)

milestones = db.get_milestones(season, mtime)

# Every "yesterday" below anchors on the day the data actually covers, not
# on today_pacific() - 1 — see db.data_as_of() for why those differ.
as_of = db.data_as_of(mtime)
day_label = f"Hot {db.daily_label(as_of)}"
if milestones:
    style.colored_header("Milestones", "headliners")
    milestone_cols = st.columns(min(len(milestones), 3))
    for i, m in enumerate(milestones):
        with milestone_cols[i % 3]:
            with st.container(border=True):
                abbr, _, color = teams.team_meta_from_city(m["Tm"], m.get("Lev"))
                style.milestone_card(m["mlbID"], m["Name"], abbr, color, m["text"])
    st.divider()

if season == today_pacific().year:
    style.colored_header("Batting Headliners", "batting")
    h1, h2, h3 = st.columns(3)
    batting_override = HOT_YESTERDAY_OVERRIDES.get(today_pacific().isoformat(), {}).get("batting")
    for col, period, label in [(h1, "day", day_label), (h2, "week", "Hot This Week"), (h3, "month", "Hot This Month")]:
        with col:
            with st.container(border=True):
                if period == "day" and batting_override:
                    style.headliner_card(label, batting_override["name"], "—", "#F5B942", batting_override["note"])
                    continue
                performer = db.top_recent_performer(recent_batting, period)
                if performer is not None:
                    abbr, _, color = teams.team_meta_from_city(performer["Tm"], performer.get("Lev"))
                    if period == "day":
                        stat_line = style.batting_day_stat_line(performer)
                    else:
                        stat_line = f"{performer['OPS']:.3f} OPS, {int(performer['HR'])} HR, {int(performer['RBI'])} RBI"
                    style.headliner_card(label, performer["Name"], abbr, color, stat_line, mlbID=performer["mlbID"])
                else:
                    st.caption(label)
                    st.markdown("No data yet")

    style.colored_header("Pitching Headliners", "pitching")
    p1, p2, p3 = st.columns(3)
    pitching_override = HOT_YESTERDAY_OVERRIDES.get(today_pacific().isoformat(), {}).get("pitching")
    for col, period, label in [(p1, "day", day_label), (p2, "week", "Hot This Week"), (p3, "month", "Hot This Month")]:
        with col:
            with st.container(border=True):
                if period == "day" and pitching_override:
                    st.caption(label)
                    st.markdown(pitching_override)
                    continue
                pitcher = db.top_recent_pitcher(recent_pitching, period)
                if pitcher is not None:
                    abbr, _, color = teams.team_meta_from_city(pitcher["Tm"], pitcher.get("Lev"))
                    if period == "day":
                        stat_line = style.pitching_day_stat_line(pitcher)
                    else:
                        stat_line = f"{pitcher['ERA']:.2f} ERA, {int(pitcher['SO'])} SO ({pitcher['IP']:.1f} IP)"
                    style.headliner_card(label, pitcher["Name"], abbr, color, stat_line, mlbID=pitcher["mlbID"])
                else:
                    st.caption(label)
                    st.markdown("No data yet")

    st.divider()

style.colored_header("Top 10 Home Run Leaders", "chart")
top10_hr = batting.sort_values("HR", ascending=False).head(10).iloc[::-1]
# Blues' scale minimum is near-white — with no explicit range_color, Plotly
# auto-scales to the data's actual min/max, so a tight top-10 HR cluster
# washes out to white by the bottom of the chart. Padding the low end below
# the data's minimum keeps every bar a visible shade of blue.
hr_min, hr_max = top10_hr["HR"].min(), top10_hr["HR"].max()
color_floor = hr_min - (hr_max - hr_min) * 0.6 - 1
fig = px.bar(
    top10_hr, x="HR", y="Name", orientation="h",
    color="HR", color_continuous_scale=style.BLUE_SCALE,
    range_color=[color_floor, hr_max],
    text="HR",
)
fig.update_layout(
    showlegend=False, coloraxis_showscale=False,
    height=400, margin=dict(l=0, r=0, t=10, b=0),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font_color=style.CHART_TEXT,
)
st.plotly_chart(fig, use_container_width=True)

st.divider()

style.colored_header("Team Snapshot", "chart")
team_batting = teams.add_team_abbr(qualified_batters)
team_ops = (
    team_batting.groupby("Tm", observed=True)["OPS"].mean().round(3)
    .reset_index().sort_values("OPS", ascending=False)
)
team_pitching = teams.add_team_abbr(qualified_pitchers)
team_era = (
    team_pitching.groupby("Tm", observed=True)["ERA"].mean().round(2)
    .reset_index().sort_values("ERA", ascending=True)
)

tcol1, tcol2 = st.columns(2)
with tcol1:
    st.caption("Average qualified-batter OPS by team")
    fig = px.bar(
        team_ops, x="Tm", y="OPS",
        color="Tm", color_discrete_map={t: teams.color_for_abbr(t) for t in team_ops["Tm"]},
    )
    fig.update_layout(
        showlegend=False, height=380, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color=style.CHART_TEXT, xaxis_title=None,
    )
    st.plotly_chart(fig, use_container_width=True)
with tcol2:
    st.caption("Average qualified-pitcher ERA by team")
    fig = px.bar(
        team_era, x="Tm", y="ERA",
        color="Tm", color_discrete_map={t: teams.color_for_abbr(t) for t in team_era["Tm"]},
    )
    fig.update_layout(
        showlegend=False, height=380, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color=style.CHART_TEXT, xaxis_title=None,
    )
    st.plotly_chart(fig, use_container_width=True)

st.divider()

style.colored_header("Standings", "chart")
standings = db.load_standings(mtime)
if standings.empty:
    st.caption("No standings data yet.")
else:
    clinch_symbols = {
        e["team_abbr"]: {"division_clinch": "z", "wildcard_clinch": "x", "eliminated": "e"}[e["kind"]]
        for e in db.clinch_elimination_status(mtime)
    }
    DIVISION_ORDER = ["AL East", "AL Central", "AL West", "NL East", "NL Central", "NL West"]
    div_cols = st.columns(3)
    for i, division in enumerate(DIVISION_ORDER):
        with div_cols[i % 3]:
            st.markdown(f"**{division}**")
            div_standings = standings[standings["division"] == division].sort_values("div_rank")
            display_cols = {"team_abbr": "Team", "wins": "W", "losses": "L"}
            display = div_standings[list(display_cols)].rename(columns=display_cols)
            st.markdown(
                style.standings_table(display, teams.color_for_abbr, clinch_symbols, compact=True),
                unsafe_allow_html=True,
            )
    st.caption("z = clinched division, x = clinched a playoff spot, e = eliminated. See the Standings page for full detail.")

st.divider()

style.colored_header(f"Batting Leaders (min {db.QUALIFIED_MIN_PA} PA)", "batting")
st.caption(f"Top 50 of {len(qualified_batters)} qualified batters by OPS — see the Batting page for the full filterable list.")
batting_display = teams.add_team_abbr(qualified_batters.head(50))[
    ["Name", "Age", "Tm", "G", "PA", "HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS"]
].reset_index(drop=True)
st.dataframe(
    style.style_stats_table(
        batting_display,
        higher_better=["HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS"],
        team_col="Tm",
        team_color_fn=teams.color_for_abbr,
        precision={"BA": "{:.3f}", "OBP": "{:.3f}", "SLG": "{:.3f}", "OPS": "{:.3f}"},
    ),
    use_container_width=True,
    height=400,
)

style.colored_header(f"Pitching Leaders (min {db.QUALIFIED_MIN_IP} IP)", "pitching")
st.caption(f"Top 50 of {len(qualified_pitchers)} qualified pitchers by ERA — see the Pitching page for the full filterable list.")
pitching_display = teams.add_team_abbr(qualified_pitchers.head(50))[
    ["Name", "Age", "Tm", "G", "GS", "W", "L", "SV", "IP", "ERA", "WHIP", "SO"]
].reset_index(drop=True)
st.dataframe(
    style.style_stats_table(
        pitching_display,
        higher_better=["W", "SV", "SO"],
        lower_better=["ERA", "WHIP", "L"],
        team_col="Tm",
        team_color_fn=teams.color_for_abbr,
        precision={"ERA": "{:.2f}", "WHIP": "{:.3f}"},
    ),
    use_container_width=True,
    height=400,
)

st.info("Use the pages in the sidebar for filterable Batting, Pitching, Fielding leaderboards, and Player Search.")
