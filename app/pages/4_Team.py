import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import prefs
import style
import teams

st.set_page_config(page_title="Team | Diamond Metrics", layout="wide")
st.title("Team")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
available_seasons = db.get_seasons("batting")
season = st.selectbox("Season", available_seasons, index=prefs.default_season_index(available_seasons))
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

# All-Star rosters come from the ASG itself (see
# ingest/refresh_data.py's fetch_all_star_roster()) — covers every season
# 2010+ except 2020, when the game was canceled.
_ALL_STAR_SCOPES = {}
if season in db.all_star_seasons():
    _ALL_STAR_SCOPES["AL All-Stars"] = "AL"
    _ALL_STAR_SCOPES["NL All-Stars"] = "NL"

team_options = teams.all_teams()
labels = [f"{abbr} — {nickname}" for abbr, nickname in team_options] + list(_COMPOSITE_SCOPES) + list(_ALL_STAR_SCOPES)

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
    # fall back to the saved favorite team (Settings page), else the first
    # team, instead of Streamlit raising on a stale value.
    fallback_label = labels[0]
    favorite_abbr = prefs.get_favorite_team()
    if favorite_abbr:
        for label in labels:
            if label.startswith(f"{favorite_abbr} —"):
                fallback_label = label
                break
    st.session_state[TEAM_CHOICE_KEY] = fallback_label

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

_ALL_STAR_COLORS = {"AL": "#C8102E", "NL": "#003DA5"}

if choice in _ALL_STAR_SCOPES:
    league = _ALL_STAR_SCOPES[choice]
    style.colored_header(choice, "headliners")
    st.caption(f"The {season} All-Star Game starting lineup and full roster.")
    roster = db.load_all_star_roster(season, league, mtime)
    if roster.empty:
        st.info("No All-Star roster data for this season.")
        st.stop()

    roster_ids = set(roster["mlbID"].astype(int))
    all_batting = teams.add_team_abbr(db.load_batting(season, mtime))
    all_pitching = teams.add_team_abbr(db.load_pitching(season, mtime))
    roster_batting = all_batting[all_batting["mlbID"].isin(roster_ids)].sort_values("OPS", ascending=False)
    roster_pitching = all_pitching[all_pitching["mlbID"].isin(roster_ids)].sort_values("ERA", ascending=True)

    # The starting pitcher's boxscore position is "P" (there's no separate
    # "SP" in the Stats API), but style.baseball_diamond's diamond layout
    # keys the mound slot as "SP" — remap just that one row.
    starters = {
        ("SP" if row.Pos == "P" else row.Pos): {"name": row.Name, "mlbID": int(row.mlbID)}
        for row in roster[roster["is_starter"]].itertuples()
    }

    # There's no "starting reliever" concept, so the RP diamond slot has no
    # is_starter row to draw from — represent it with the roster's closer
    # instead (most saves that season among non-starting pitchers), falling
    # back to the next-best ERA if nobody has recorded a save yet.
    non_starter_pitching = roster_pitching[~roster_pitching["mlbID"].isin(
        {v["mlbID"] for k, v in starters.items() if k == "SP"}
    )]
    if not non_starter_pitching.empty:
        closer = non_starter_pitching.sort_values(["SV", "ERA"], ascending=[False, True]).iloc[0]
        starters["RP"] = {"name": closer["Name"], "mlbID": int(closer["mlbID"])}

    st.markdown(style.baseball_diamond(starters, _ALL_STAR_COLORS[league]), unsafe_allow_html=True)
    if "SP" not in starters:
        # Rosters are announced weeks ahead, but the official starting-
        # pitcher flag isn't set until game time — not a bug, the SP slot
        # just shows TBD until then.
        st.caption("Starting pitcher not yet announced for this game.")

    if not roster_batting.empty:
        style.colored_header("Batting", "batting")
        st.dataframe(
            style.style_stats_table(
                roster_batting[["Name", "Age", "Tm", "G", "PA", "HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS"]],
                higher_better=["HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS"],
                team_col="Tm", team_color_fn=teams.color_for_abbr,
                precision={"BA": "{:.3f}", "OBP": "{:.3f}", "SLG": "{:.3f}", "OPS": "{:.3f}"},
            ),
            use_container_width=True,
            hide_index=True,
        )

    if not roster_pitching.empty:
        style.colored_header("Pitching", "pitching")
        st.dataframe(
            style.style_stats_table(
                roster_pitching[["Name", "Age", "Tm", "G", "GS", "W", "L", "SV", "IP", "ERA", "WHIP", "SO"]],
                higher_better=["W", "SV", "SO"],
                lower_better=["ERA", "WHIP", "L"],
                team_col="Tm", team_color_fn=teams.color_for_abbr,
                precision={"ERA": "{:.2f}", "WHIP": "{:.3f}"},
            ),
            use_container_width=True,
            hide_index=True,
        )
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

# Standings/playoff odds/schedule are all live, present-day data (not
# scoped to a season) — like the depth chart below, only shown when the
# CURRENT season is selected, so a historical season doesn't show today's
# playoff race next to, say, 2015 stats.
if season == current_season:
    standings = db.load_standings(mtime)
    team_standing = standings[standings["team_abbr"] == selected_abbr]
    if not team_standing.empty:
        row = team_standing.iloc[0]
        playoff_odds = db.compute_playoff_odds(mtime)
        team_odds = playoff_odds[playoff_odds["team_abbr"] == selected_abbr]
        pct = float(team_odds.iloc[0]["playoff_pct"]) if not team_odds.empty else None
        ws_pct = float(team_odds.iloc[0]["ws_pct"]) if not team_odds.empty else None

        style.colored_header("Standings & Playoff Odds", "batting")
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Record", f"{row['wins']}-{row['losses']}")
        m2.metric(row["division"], f"#{row['div_rank']}")
        m3.metric("Run Diff", f"{row['run_diff']:+.0f}" if pd.notna(row["run_diff"]) else "—")
        m4.metric("Streak", row["streak"] if pd.notna(row["streak"]) else "—")
        m5.metric("Playoff Odds", f"{pct:.1f}%" if pct is not None else "—")
        m6.metric("World Series Odds", f"{ws_pct:.1f}%" if ws_pct is not None else "—")

        # Records breakdown — the situational splits that explain a season
        # (a bad one-run record is usually the story behind "worse than
        # their run differential"). All from played schedule games.
        played_games = db.team_schedule(selected_abbr, mtime)
        played_games = played_games[played_games["result"].notna()]
        if not played_games.empty:
            margin = (played_games["runs_for"] - played_games["runs_against"]).abs()
            own_division = row["division"]
            division_teams = set(standings[standings["division"] == own_division]["team_abbr"]) - {selected_abbr}

            def _rec(mask):
                seg = played_games[mask]
                return f"{(seg['result'] == 'W').sum()}-{(seg['result'] == 'L').sum()}"

            style.colored_header("Records Breakdown", "headliners")
            r1, r2, r3, r4, r5 = st.columns(5)
            r1.metric("Home", _rec(played_games["home"]))
            r2.metric("Away", _rec(~played_games["home"]))
            r3.metric("One-Run Games", _rec(margin == 1))
            r4.metric("Blowouts (5+)", _rec(margin >= 5))
            r5.metric("vs Division", _rec(played_games["opponent"].isin(division_teams)))

    full_schedule = db.team_schedule(selected_abbr, mtime)
    if not full_schedule.empty:
        style.colored_header("Full Season Schedule", "pitching")
        st.caption(f"{(full_schedule['result'] == 'W').sum()}W – {(full_schedule['result'] == 'L').sum()}L so far, {full_schedule['result'].isna().sum()} remaining.")
        st.markdown(
            "<div id='sched-container' style='max-height:500px;overflow-y:auto'>"
            + style.team_schedule_table(full_schedule, teams.color_for_abbr)
            + "</div>",
            unsafe_allow_html=True,
        )
        # Local game times (server has no idea what timezone the viewer is
        # in — see the identical pattern on Today's Games) and an initial
        # scroll to the most recent/live game, so the schedule opens
        # positioned at "now" instead of scrolled to Opening Day. Re-run on
        # every rerun (selecting a different team swaps the schedule's DOM
        # under the same container id).
        components.html(
            """
            <script>
            (function() {
                function updateGameTimes() {
                    const els = window.parent.document.querySelectorAll('.game-time-local[data-utc]');
                    els.forEach(function(el) {
                        const d = new Date(el.dataset.utc);
                        if (isNaN(d.getTime())) return;
                        el.textContent = d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
                    });
                }
                function scrollToAnchor() {
                    // Set the inner container's own scrollTop directly
                    // (rather than anchor.scrollIntoView(), which walks up
                    // and scrolls every ancestor including the outer page —
                    // dragging the whole Team page down to wherever the
                    // schedule happens to sit instead of just scrolling
                    // inside the fixed-height schedule box).
                    const container = window.parent.document.getElementById('sched-container');
                    const anchor = window.parent.document.getElementById('sched-anchor');
                    if (container && anchor) {
                        const anchorRect = anchor.getBoundingClientRect();
                        const containerRect = container.getBoundingClientRect();
                        container.scrollTop += anchorRect.top - containerRect.top;
                    }
                }
                updateGameTimes();
                scrollToAnchor();
            })();
            </script>
            """,
            height=0,
        )

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

# --- Team leaders -----------------------------------------------------------
def _leader_card(col, row_data, text, key):
    """One leader as a milestone-style card with a profile button."""
    with col:
        style.milestone_card(int(row_data["mlbID"]), row_data["Name"], selected_abbr, color, text)
        if st.button("View profile", key=key, use_container_width=True):
            st.session_state["selected_mlbID"] = int(row_data["mlbID"])
            st.session_state["selected_name"] = row_data["Name"]
            st.session_state["selected_season"] = season
            st.switch_page("pages/_Player.py")


leaders = []
qualified_bat = team_batting[team_batting["PA"] >= 100]
qualified_pit = team_pitching[team_pitching["IP"] >= 30]
if not qualified_bat.empty:
    war_row = qualified_bat.sort_values("WAR", ascending=False).iloc[0]
    if pd.notna(war_row["WAR"]):
        leaders.append((war_row, f"{war_row['WAR']:.1f} WAR — position-player leader", "leader_war"))
    ops_row = qualified_bat.sort_values("OPS", ascending=False).iloc[0]
    leaders.append((ops_row, f"{ops_row['OPS']:.3f} OPS — best bat", "leader_ops"))
    hr_row = qualified_bat.sort_values("HR", ascending=False).iloc[0]
    leaders.append((hr_row, f"{int(hr_row['HR'])} HR — power leader", "leader_hr"))
if not qualified_pit.empty:
    era_row = qualified_pit.sort_values("ERA").iloc[0]
    leaders.append((era_row, f"{era_row['ERA']:.2f} ERA — staff ace", "leader_era"))
    so_row = team_pitching.sort_values("SO", ascending=False).iloc[0]
    leaders.append((so_row, f"{int(so_row['SO'])} strikeouts — whiff leader", "leader_so"))
if not team_pitching.empty and team_pitching["SV"].max() > 0:
    sv_row = team_pitching.sort_values("SV", ascending=False).iloc[0]
    leaders.append((sv_row, f"{int(sv_row['SV'])} saves — closer", "leader_sv"))

# Clutch hero — the roster's WPA leader from our win probability model
# (batters and pitchers pooled; WPA data covers 2025 onward).
roster_ids = set(team_batting["mlbID"]) | set(team_pitching["mlbID"])
wpa_pool = []
for wpa_table, names in [(db.load_wpa_batting(season, mtime), team_batting),
                         (db.load_wpa_pitching(season, mtime), team_pitching)]:
    if not wpa_table.empty:
        mine = wpa_table[wpa_table["mlbID"].isin(roster_ids)].merge(
            names[["mlbID", "Name"]], on="mlbID", how="inner"
        )
        wpa_pool.append(mine)
if wpa_pool:
    wpa_all = pd.concat(wpa_pool, ignore_index=True)
    if not wpa_all.empty:
        clutch_row = wpa_all.sort_values("wpa", ascending=False).iloc[0]
        leaders.append((clutch_row, f"{clutch_row['wpa']:+.2f} WPA — clutch hero", "leader_wpa"))

if leaders:
    style.colored_header("Team Leaders", "headliners")
    for start in range(0, len(leaders), 3):
        cols = st.columns(3)
        for col, (row_data, text, key) in zip(cols, leaders[start:start + 3]):
            _leader_card(col, row_data, text, key)

# --- Roster tables -----------------------------------------------------------
prof_col1, prof_col2 = st.columns([3, 1])
with prof_col1:
    roster_names = pd.concat([team_batting[["mlbID", "Name"]], team_pitching[["mlbID", "Name"]]]) \
        .drop_duplicates("mlbID").sort_values("Name")
    profile_pick = st.selectbox("Open a player's profile", roster_names["Name"].tolist(),
                                label_visibility="collapsed")
with prof_col2:
    if st.button("View profile", key="roster_profile_btn", use_container_width=True):
        picked = roster_names[roster_names["Name"] == profile_pick].iloc[0]
        st.session_state["selected_mlbID"] = int(picked["mlbID"])
        st.session_state["selected_name"] = picked["Name"]
        st.session_state["selected_season"] = season
        st.switch_page("pages/_Player.py")

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
