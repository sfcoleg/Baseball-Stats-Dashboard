import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Team | Diamond Metrics", layout="wide")
st.title("Team")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
available_seasons = db.get_seasons("batting")
season = st.selectbox("Season", available_seasons, index=0)
current_season = available_seasons[0]  # most recent season = the one recent_batting/recent_pitching cover

_COMPOSITE_COLORS = {"all": "#3B82F6", "month": "#93C5FD"}
_COMPOSITE_CAPTIONS = {
    "all": "Best qualified player at each position across all 30 teams, full-season stats.",
    "month": "Best performer at each position over the trailing 30 days.",
}

_COMPOSITE_SCOPES = {}
if season >= 2016:
    # build_composite_team() needs fielding.Pos to assign roster spots, and
    # the fielding table is empty before 2016 (Statcast's Outs Above
    # Average metric didn't exist yet) — so "All MLB Team" would just come
    # back with no fielders assignable to a position.
    _COMPOSITE_SCOPES["All MLB Team"] = "all"
if season == current_season:
    # recent_batting/recent_pitching are current-season-only (never backfilled
    # for historical years — see AGENTS.md), so "All Month Team" only makes
    # sense when the current season is selected.
    _COMPOSITE_SCOPES["All Month Team"] = "month"

team_options = teams.all_teams()
labels = [f"{abbr} — {nickname}" for abbr, nickname in team_options] + list(_COMPOSITE_SCOPES)

# Keyed (rather than an `index=` computed fresh each run) so the choice
# survives a rerun even when `labels` itself changes shape — e.g. switching
# to a season where "All MLB Team" isn't offered used to silently reset the
# selectbox back to index 0 (Diamondbacks) on every such rerun.
TEAM_CHOICE_KEY = "team_page_team_choice"

# Set by clicking a team's row on the Standings page (st.switch_page) — one-shot,
# so a manual selectbox change afterward isn't overridden on a later visit.
default_abbr = st.session_state.pop("team_page_selected_team", None)
if default_abbr:
    for label in labels:
        if label.startswith(f"{default_abbr} —"):
            st.session_state[TEAM_CHOICE_KEY] = label
            break

if st.session_state.get(TEAM_CHOICE_KEY) not in labels:
    # First visit, or the previously selected option isn't valid for this
    # season anymore (e.g. a composite scope gated to certain seasons) —
    # fall back to the first team instead of Streamlit raising on a stale value.
    st.session_state[TEAM_CHOICE_KEY] = labels[0]

choice = st.selectbox("Team", labels, key=TEAM_CHOICE_KEY)

if choice in _COMPOSITE_SCOPES:
    scope = _COMPOSITE_SCOPES[choice]
    style.colored_header(choice, "fielding")
    st.caption(_COMPOSITE_CAPTIONS[scope])
    starters = db.build_composite_team(season, mtime, scope)
    if not starters:
        st.info("Not enough data yet to build this roster.")
        st.stop()
    st.markdown(style.baseball_diamond(starters, _COMPOSITE_COLORS[scope]), unsafe_allow_html=True)

    roster_rows = [
        {"Pos": pos, "Name": player["name"], "Stat": player.get("note", "—")}
        for pos, player in starters.items()
    ]
    st.dataframe(pd.DataFrame(roster_rows), use_container_width=True, hide_index=True)
    st.stop()

selected_abbr = team_options[labels.index(choice)][0]
color = teams.color_for_abbr(selected_abbr)
team_id = teams.team_id_for_abbr(selected_abbr)

batting = teams.add_team_abbr(db.load_batting(season, mtime))
pitching = teams.add_team_abbr(db.load_pitching(season, mtime))
fielding = teams.add_team_abbr_from_nickname(db.load_fielding(season, mtime))

team_batting = batting[batting["Tm"] == selected_abbr].sort_values("OPS", ascending=False)
team_pitching = pitching[pitching["Tm"] == selected_abbr].sort_values("ERA", ascending=True)
team_fielding = fielding[fielding["Tm"] == selected_abbr].sort_values("OAA", ascending=False)

logo_col, header_col = st.columns([1, 8])
with logo_col:
    if team_id:
        # st.image inherits the theme's baseRadius ("large") and rounds the
        # logo's corners — a raw <img> tag with an inline style override
        # sidesteps that without touching the global theme. Sized via CSS
        # height (not the HTML width attribute) — the live CDN's logos are
        # SVGs with no intrinsic width/height, only a viewBox, and relying
        # on a bare `width=` attribute to auto-derive the height from that
        # rendered them tiny; an explicit CSS height is consistent across
        # browsers regardless of how the source image declares its size.
        st.markdown(
            f"<img src='{style.team_logo_for_season(selected_abbr, team_id, season)}' "
            f"style='height:80px;width:auto;border-radius:0'>",
            unsafe_allow_html=True,
        )
with header_col:
    st.markdown(
        f"<h2><span style='background-color:{color}66;color:#FAFAFA;padding:4px 14px;"
        f"border-radius:10px'>{selected_abbr}</span> {teams.franchise_display_name(selected_abbr, season)}</h2>",
        unsafe_allow_html=True,
    )
    st.caption(f"{len(team_batting)} batters, {len(team_pitching)} pitchers, {len(team_fielding)} fielders on record for {season}.")

if team_batting.empty and team_pitching.empty and team_fielding.empty:
    st.info("No players found for this team in the selected season.")
    st.stop()

# db.load_depth_chart() hits the MLB Stats API's live, present-day depth
# chart — it can't be scoped to a season, so it only makes sense to show
# when the CURRENT season is selected. A historical season would otherwise
# show today's roster next to that season's stats, which is misleading.
if season == current_season:
    starters = db.load_depth_chart(team_id) if team_id else {}
    if "RP" not in starters:
        # No CP listed on the live depth chart — common for a team using a
        # closer-by-committee rather than one set closer. Fall back to this
        # season's highest-IP reliever (GS == 0) so the RP slot isn't just blank.
        bullpen = team_pitching[team_pitching["GS"] == 0]
        if not bullpen.empty:
            top_rp = bullpen.sort_values("IP", ascending=False).iloc[0]
            starters["RP"] = {"name": top_rp["Name"], "mlbID": top_rp["mlbID"]}
    if starters:
        style.colored_header("Starting Lineup", "fielding")
        st.caption("Current depth-chart starter at each position.")
        st.markdown(style.baseball_diamond(starters, color), unsafe_allow_html=True)

style.colored_header("Batting", "batting")
st.dataframe(
    style.style_stats_table(
        team_batting[["Name", "Age", "G", "PA", "HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS"]],
        higher_better=["HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS"],
        precision={"BA": "{:.3f}", "OBP": "{:.3f}", "SLG": "{:.3f}", "OPS": "{:.3f}"},
    ),
    use_container_width=True,
    hide_index=True,
)

style.colored_header("Pitching", "pitching")
st.dataframe(
    style.style_stats_table(
        team_pitching[["Name", "Age", "G", "GS", "W", "L", "SV", "IP", "ERA", "WHIP", "SO"]],
        higher_better=["W", "SV", "SO"],
        lower_better=["ERA", "WHIP", "L"],
        precision={"ERA": "{:.2f}", "WHIP": "{:.3f}"},
    ),
    use_container_width=True,
    hide_index=True,
)

style.colored_header("Fielding", "fielding")
st.dataframe(
    style.style_stats_table(
        team_fielding[["Name", "Pos", "OAA", "FRP", "success_rate"]].rename(columns={"success_rate": "Success Rate"}),
        higher_better=["OAA", "FRP"],
    ),
    use_container_width=True,
    hide_index=True,
)
