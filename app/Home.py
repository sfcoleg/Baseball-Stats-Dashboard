import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent))
import db
import style
import teams

st.set_page_config(page_title="Diamond Metrics", layout="wide")

# The data refresh cron runs at 6:00am Pacific, so "today" for this app's
# purposes means the Pacific calendar day — not the server process's own
# local date. Streamlit Community Cloud runs its servers in UTC, which is
# far enough ahead of Pacific that plain date.today() rolls over to the
# next day while it's still evening in Pacific time, showing "tomorrow's"
# content hours too early. today_pacific() is the one source of truth for
# "what day is it" anywhere on this page.
def today_pacific() -> date:
    return datetime.now(ZoneInfo("America/Los_Angeles")).date()


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
    games = db.load_todays_games(db.db_mtime())
    if games.empty:
        return
    live_scores = db.load_live_scores(games.iloc[0]["date"])
    logo_season = today_pacific().year

    def _logo(abbr):
        team_id = teams.team_id_for_abbr(teams.normalize_mlb_abbr(abbr))
        return style.team_logo_for_season(teams.normalize_mlb_abbr(abbr), team_id, logo_season) if team_id else None

    def _team_row(logo, name, score):
        logo_html = (
            f"<img src='{logo}' style='height:22px;width:22px;object-fit:contain;margin-right:6px;flex-shrink:0'>"
            if logo else ""
        )
        return (
            "<div style='display:flex;align-items:center;justify-content:space-between;padding:2px 0'>"
            f"<div style='display:flex;align-items:center;overflow:hidden'>{logo_html}"
            f"<span style='font-size:0.85rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>{name}</span></div>"
            f"<span style='font-weight:700;font-size:0.95rem;margin-left:8px;flex-shrink:0'>{score}</span>"
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
                f"<span class='live-badge' style='background-color:#D32F2F;color:#FFFFFF;padding:1px 8px;"
                f"border-radius:6px;font-weight:700;font-size:0.68rem'>LIVE</span>"
                f"<span style='color:#9AA3B5;font-size:0.72rem;margin-left:6px'>{live.get('inning') or ''}</span>"
            )
        elif started:
            status_html = "<span style='color:#9AA3B5;font-size:0.72rem'>Final</span>"
        else:
            status_html = "<span style='color:#9AA3B5;font-size:0.72rem'>Scheduled</span>"

        cards.append(
            "<div style='flex:0 0 auto;width:170px;background-color:#1B243866;border-radius:10px;"
            "padding:10px 12px;margin-right:10px'>"
            f"<div style='margin-bottom:4px'>{status_html}</div>"
            + _team_row(_logo(row["away_abbr"]), row["away_team"], away_txt)
            + _team_row(_logo(row["home_abbr"]), row["home_team"], home_txt)
            + "</div>"
        )

    st.markdown(
        "<div style='display:flex;overflow-x:auto;padding-bottom:8px;margin-top:-90px'>"
        + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )
    st.divider()


_todays_games_strip()

seasons = db.get_seasons("batting")
season = st.selectbox("Season", seasons, index=0)

mtime = db.db_mtime()
batting = db.load_batting(season, mtime)
pitching = db.load_pitching(season, mtime)

st.divider()

qualified_batters = batting[batting["PA"] >= 50].sort_values("OPS", ascending=False)
qualified_pitchers = pitching[pitching["IP"] >= 20].sort_values("ERA", ascending=True)

recent_batting = db.load_recent_batting(season, mtime)
recent_pitching = db.load_recent_pitching(season, mtime)

milestones = db.get_milestones(season, mtime)
if milestones:
    style.colored_header("Milestones", "headliners")
    st.caption("Notable achievements from yesterday's games.")
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
    for col, period, label in [(h1, "day", "Hot Yesterday"), (h2, "week", "Hot This Week"), (h3, "month", "Hot This Month")]:
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
    for col, period, label in [(p1, "day", "Hot Yesterday"), (p2, "week", "Hot This Week"), (p3, "month", "Hot This Month")]:
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
    color="HR", color_continuous_scale="Blues",
    range_color=[color_floor, hr_max],
    text="HR",
)
fig.update_layout(
    showlegend=False, coloraxis_showscale=False,
    height=400, margin=dict(l=0, r=0, t=10, b=0),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font_color="#FAFAFA",
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
        font_color="#FAFAFA", xaxis_title=None,
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
        font_color="#FAFAFA", xaxis_title=None,
    )
    st.plotly_chart(fig, use_container_width=True)

st.divider()

style.colored_header("Batting Leaders (min 50 PA)", "batting")
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

style.colored_header("Pitching Leaders (min 20 IP)", "pitching")
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
