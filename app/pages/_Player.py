import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Player | Diamond Metrics", layout="wide")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

# Hydrates a shared link (?mlbid=...&season=...) into session_state — the
# normal path only ever gets here via the sidebar search setting
# selected_mlbID directly, so a link opened fresh (new tab/visitor) would
# otherwise always hit the "use the search box" dead end below.
if "selected_mlbID" not in st.session_state and "mlbid" in st.query_params:
    try:
        _qp_mlbid = int(st.query_params["mlbid"])
    except (TypeError, ValueError):
        _qp_mlbid = None
    if _qp_mlbid is not None:
        _qp_name = db.get_player_name(_qp_mlbid, db.db_mtime())
        if _qp_name:
            st.session_state["selected_mlbID"] = _qp_mlbid
            st.session_state["selected_name"] = _qp_name
            if "season" in st.query_params:
                try:
                    st.session_state["selected_season"] = int(st.query_params["season"])
                except (TypeError, ValueError):
                    pass

if "selected_mlbID" not in st.session_state:
    st.title("Player Profile")
    st.info("Use the search box in the sidebar to find a player.")
    st.stop()

mlbID = st.session_state["selected_mlbID"]
mtime = db.db_mtime()

current_season = db.get_seasons("batting")[0]

# Scoped to seasons this player actually has a row in — not every cached
# season — so a retired player's dropdown can't land on a post-retirement
# season with nothing to show.
own_seasons = db.player_seasons(mlbID, mtime) or [current_season]
default_season = st.session_state.get("selected_season") or own_seasons[0]
if default_season not in own_seasons:
    default_season = own_seasons[0]
# Keyed per-player so switching to a different search result resets the
# selectbox to that player's own default season instead of sticking on
# whatever season was last picked for the previous player.
season = st.selectbox(
    "Season", own_seasons, index=own_seasons.index(default_season), key=f"player_profile_season_{mlbID}",
)

# "Retired" is judged against the CURRENT season specifically, independent
# of whichever season is being viewed above — a player who's active now
# but has no row in some earlier off-year isn't retired, and a retired
# player is still retired even while you're looking at their 2019 season.
is_retired = (
    db.get_player_batting(mlbID, current_season, mtime) is None
    and db.get_player_pitching(mlbID, current_season, mtime) is None
)

batting = db.get_player_batting(mlbID, season, mtime)
pitching = db.get_player_pitching(mlbID, season, mtime)
fielding = db.get_player_fielding(mlbID, season, mtime)

if batting is None and pitching is None and fielding.empty:
    st.title("Player Profile")
    st.info("No stats found for this player in the selected season.")
    st.stop()

selected_name = st.session_state.get("selected_name", "")
# Primary role only (career PA vs career IP) except the one true two-way
# player — see db.player_roles_label — so a pitcher who batted a handful
# of times under the old NL rules, or a position player who mopped up an
# inning in a blowout, isn't mislabeled with a dual role.
selected_roles = db.player_roles_label(mlbID, mtime)
# Gates which sections/tabs render below — a pitcher with one incidental PA
# (or a position player who mopped up an inning) still has a `batting`/
# `pitching` row, but shouldn't get that section unless it's actually their
# role (or they're a two-way player per TWO_WAY_PLAYER_MLBIDS).
is_batter_role = "Batter" in selected_roles
is_pitcher_role = "Pitcher" in selected_roles

all_batting = db.load_batting(season, mtime)
all_pitching = db.load_pitching(season, mtime)
qualified_batting = all_batting[all_batting["PA"] >= 50]
qualified_pitching = all_pitching[all_pitching["IP"] >= 20]

st.divider()

team_row = batting if batting is not None else pitching
if team_row is not None:
    abbr, nickname, color = teams.team_meta_from_city(team_row["Tm"], team_row.get("Lev"))
    nickname = teams.franchise_display_name(abbr, season)
    age = team_row["Age"]
elif not fielding.empty:
    abbr, color = teams.team_meta_from_nickname(fielding.iloc[0]["Tm"])
    nickname = fielding.iloc[0]["Tm"]
    age = "—"
else:
    abbr, nickname, color = "—", "Unknown", "#666666"
    age = "—"

# Tints this page's bordered cards/tabs toward the player's own team color
# instead of the site-wide fixed blue — scoped to this script run only
# (Streamlit fully re-executes the page on navigation, so this never
# leaks onto another player's or another page's colors).
st.markdown(
    f"<style>"
    f"[data-testid='stVerticalBlockBorderWrapper'] {{ border-color: {color}55 !important; }}"
    f"[data-testid='stTabs'] [aria-selected='true'] {{ color: {color} !important; }}"
    f"[data-testid='stTabs'] [data-baseweb='tab-highlight'] {{ background-color: {color} !important; }}"
    f"</style>",
    unsafe_allow_html=True,
)

photo_col, header_col = st.columns([1, 6])
with photo_col:
    st.image(style.headshot_url(mlbID, width=180), width=120)
with header_col:
    retired_badge = (
        "<span style='background-color:#66666666;color:#DCE1EA;padding:4px 12px;"
        "border-radius:10px;font-size:0.5em;vertical-align:middle;font-weight:600;margin-left:6px'>RETIRED</span>"
        if is_retired else ""
    )
    hof_badge = (
        "<span style='background-color:#FFD70066;color:#3A2F00;padding:4px 12px;"
        "border-radius:10px;font-size:0.5em;vertical-align:middle;font-weight:700;margin-left:6px'>HOF</span>"
        if mlbID in db.HALL_OF_FAME_MLBIDS else ""
    )
    st.markdown(
        f"# {selected_name} "
        f"<span style='background-color:{color}66;color:#FAFAFA;padding:4px 12px;"
        f"border-radius:10px;font-size:0.5em;vertical-align:middle;font-weight:600'>{abbr}</span>"
        f"{retired_badge}{hof_badge}",
        unsafe_allow_html=True,
    )
    st.caption(f"{nickname} · Age {age} · {selected_roles}")
    st.markdown(
        "<button id='share-link-btn' style='background-color:#3B4A8244;color:#B9C4FF;"
        "border:1px solid #3B4A8288;border-radius:8px;padding:3px 12px;font-size:0.8rem;"
        "cursor:pointer;margin-top:4px'>\U0001F517 Copy share link</button>"
        "<span id='share-link-copied' style='display:none;color:#7CFC9A;font-size:0.8rem;"
        "margin-left:8px'>Copied!</span>",
        unsafe_allow_html=True,
    )
    components.html(
        f"""
        <script>
        (function() {{
            function setup() {{
                const btn = window.parent.document.getElementById('share-link-btn');
                if (!btn || btn.dataset.wired) return;
                btn.dataset.wired = '1';
                btn.addEventListener('click', function() {{
                    const url = window.parent.location.origin + '/Player?mlbid={mlbID}&season={season}';
                    // Uses the PARENT document's clipboard permission, not this
                    // sandboxed iframe's — the iframe alone often lacks the
                    // clipboard-write permission grant, same reasoning as the
                    // parent-initiated navigation workaround in following.py.
                    window.parent.navigator.clipboard.writeText(url).then(function() {{
                        const msg = window.parent.document.getElementById('share-link-copied');
                        if (msg) {{
                            msg.style.display = 'inline';
                            setTimeout(function() {{ msg.style.display = 'none'; }}, 2000);
                        }}
                    }});
                }});
            }}
            setup();
            new MutationObserver(setup).observe(window.parent.document.body, {{childList: true, subtree: true}});
        }})();
        </script>
        """,
        height=0,
    )

history = db.load_player_history(mlbID, season, mtime)
streak_badges = []
if batting is not None and is_batter_role:
    hit_streak = db.current_hit_streak(history[history["role"] == "Batter"])
    if hit_streak is not None and hit_streak >= 2:
        streak_badges.append(f"{hit_streak}-Game Hit Streak")
if pitching is not None and is_pitcher_role:
    scoreless_streak = db.current_scoreless_streak(history[history["role"] == "Pitcher"])
    if scoreless_streak is not None and scoreless_streak >= 2:
        streak_badges.append(f"{scoreless_streak}-Outing Scoreless Streak")
if streak_badges:
    badges_html = "".join(
        f"<span style='background-color:#2e7d3244;color:#7CFC9A;padding:3px 10px;"
        f"border-radius:8px;font-weight:600;font-size:0.85rem;margin-right:8px'>{b}</span>"
        for b in streak_badges
    )
    st.markdown(badges_html, unsafe_allow_html=True)

# Lets the headline stat rows below show "+0.023 vs 2025" instead of a
# percentile — same st.metric delta slot, just a different source, so
# toggling doesn't change layout. Off by default since percentile-vs-
# league is the more broadly useful view for someone who doesn't already
# know this player's prior season off the top of their head.
compare_mode = st.checkbox("Compare to last season", key=f"compare_toggle_{mlbID}_{season}")
prior_batting = prior_pitching = None
if compare_mode:
    if batting is not None:
        prior_batting = db.get_player_batting(mlbID, season - 1, mtime)
    if pitching is not None:
        prior_pitching = db.get_player_pitching(mlbID, season - 1, mtime)
    if (batting is not None and prior_batting is None) or (pitching is not None and prior_pitching is None):
        st.caption(f"No {season - 1} data for this player in at least one section — showing percentiles there instead.")


def stat_delta(prior_row, col, current_val, fmt, lower_is_better=False):
    """(delta_text, delta_color) for st.metric comparing `current_val` to
    the same stat in `prior_row` (a season-(N-1) Series). None/'off' if
    there's no prior-season row or the stat is missing from it."""
    if prior_row is None or col not in prior_row.index or pd.isna(prior_row.get(col)) or pd.isna(current_val):
        return None, "off"
    diff = current_val - prior_row[col]
    delta_color = "off" if diff == 0 else ("inverse" if lower_is_better else "normal")
    return f"{fmt.format(diff)} vs {season - 1}", delta_color


if batting is not None and is_batter_role:
    style.colored_header("Batting", "batting", color)
    metrics = [
        ("AVG", f"{batting['BA']:.3f}", db.percentile_rank(qualified_batting["BA"], batting["BA"]), "BA", "{:+.3f}"),
        ("OBP", f"{batting['OBP']:.3f}", db.percentile_rank(qualified_batting["OBP"], batting["OBP"]), "OBP", "{:+.3f}"),
        ("SLG", f"{batting['SLG']:.3f}", db.percentile_rank(qualified_batting["SLG"], batting["SLG"]), "SLG", "{:+.3f}"),
        ("OPS", f"{batting['OPS']:.3f}", db.percentile_rank(qualified_batting["OPS"], batting["OPS"]), "OPS", "{:+.3f}"),
        ("HR", int(batting["HR"]), db.percentile_rank(qualified_batting["HR"], batting["HR"]), "HR", "{:+.0f}"),
        ("RBI", int(batting["RBI"]), db.percentile_rank(qualified_batting["RBI"], batting["RBI"]), "RBI", "{:+.0f}"),
    ]
    cols = st.columns(6)
    for col, (label, value, pct, raw_col, fmt) in zip(cols, metrics):
        if compare_mode and prior_batting is not None:
            delta_text, delta_color = stat_delta(prior_batting, raw_col, batting[raw_col], fmt)
        else:
            delta_text, delta_color = (f"{pct}th pctile" if pct is not None else None), "off"
        col.metric(label, value, delta_text, delta_color=delta_color)

    style.colored_header("Baserunning", "batting", color)
    sb, cs = batting.get("SB"), batting.get("CS")
    attempts = (sb or 0) + (cs or 0)
    sb_pct_val = (sb / attempts * 100) if attempts and pd.notna(sb) and pd.notna(cs) else None
    qualified_attempts = qualified_batting["SB"] + qualified_batting["CS"]
    qualified_sb_pct = (qualified_batting["SB"] / qualified_attempts.replace(0, pd.NA) * 100)
    br_metrics = [
        ("BsR", f"{batting['baserunning_runs']:+.1f}" if pd.notna(batting.get("baserunning_runs")) else "—",
         db.percentile_rank(qualified_batting["baserunning_runs"], batting.get("baserunning_runs")) if pd.notna(batting.get("baserunning_runs")) else None),
        ("SB", int(sb) if pd.notna(sb) else "—", db.percentile_rank(qualified_batting["SB"], sb) if pd.notna(sb) else None),
        ("CS", int(cs) if pd.notna(cs) else "—", None),
        ("SB%", f"{sb_pct_val:.0f}%" if sb_pct_val is not None else "—",
         db.percentile_rank(qualified_sb_pct, sb_pct_val) if sb_pct_val is not None else None),
        ("Sprint Speed", f"{batting['sprint_speed']:.1f} ft/s" if pd.notna(batting.get("sprint_speed")) else "—",
         db.percentile_rank(qualified_batting["sprint_speed"], batting.get("sprint_speed")) if pd.notna(batting.get("sprint_speed")) else None),
        ("Home-to-1st", f"{batting['hp_to_1b']:.2f}s" if pd.notna(batting.get("hp_to_1b")) else "—",
         db.percentile_rank(qualified_batting["hp_to_1b"], batting.get("hp_to_1b"), lower_is_better=True) if pd.notna(batting.get("hp_to_1b")) else None),
    ]
    br_cols = st.columns(len(br_metrics))
    for col, (label, value, pct) in zip(br_cols, br_metrics):
        col.metric(label, value, f"{pct}th pctile" if pct is not None else None, delta_color="off")

    std_tab, adv_tab, sc_tab, bb_tab = st.tabs(["Standard", "Advanced", "Statcast", "Batted Ball"])
    with std_tab:
        st.dataframe(
            batting[["G", "PA", "AB", "R", "H", "2B", "3B", "HR", "RBI", "BB", "SO", "SB", "CS"]]
            .to_frame().T,
            use_container_width=True,
            hide_index=True,
        )
    with adv_tab:
        st.dataframe(
            batting[["ISO", "BABIP", "K_PCT", "BB_PCT", "wOBA", "xwOBA", "WAR", "OPS_plus", "wRC_plus"]]
            .rename({"K_PCT": "K%", "BB_PCT": "BB%", "OPS_plus": "OPS+", "wRC_plus": "wRC+"})
            .to_frame().T,
            use_container_width=True,
            hide_index=True,
        )
    with sc_tab:
        st.dataframe(
            batting[["avg_exit_velo", "max_exit_velo", "hard_hit_pct", "barrel_pct", "xBA", "xSLG"]]
            .rename({
                "avg_exit_velo": "Avg EV", "max_exit_velo": "Max EV",
                "hard_hit_pct": "Hard-Hit%", "barrel_pct": "Barrel%",
            })
            .to_frame().T,
            use_container_width=True,
            hide_index=True,
        )
    with bb_tab:
        bb_row = db.load_batted_ball(season, mtime)
        bb_row = bb_row[bb_row["mlbID"] == mlbID] if "mlbID" in bb_row.columns else bb_row.iloc[0:0]
        bt_row = db.load_bat_tracking(season, mtime)
        bt_row = bt_row[bt_row["mlbID"] == mlbID] if "mlbID" in bt_row.columns else bt_row.iloc[0:0]
        if bb_row.empty and bt_row.empty:
            st.caption("No batted-ball or bat-tracking data for this season.")
        if not bb_row.empty:
            st.caption("Batted-ball direction and type — how this player's contact is distributed.")
            st.dataframe(
                bb_row[["gb_rate", "fb_rate", "ld_rate", "pu_rate", "pull_rate", "straight_rate", "oppo_rate"]]
                .rename(columns={
                    "gb_rate": "GB%", "fb_rate": "FB%", "ld_rate": "LD%", "pu_rate": "PU%",
                    "pull_rate": "Pull%", "straight_rate": "Straight%", "oppo_rate": "Oppo%",
                }),
                use_container_width=True,
                hide_index=True,
            )
        if not bt_row.empty:
            st.caption("Bat tracking — 2023+ only.")
            st.dataframe(
                bt_row[["avg_bat_speed", "swing_length", "hard_swing_rate", "squared_up_per_swing", "blast_per_swing"]]
                .rename(columns={
                    "avg_bat_speed": "Bat Speed (mph)", "swing_length": "Swing Length (ft)",
                    "hard_swing_rate": "Hard-Swing%", "squared_up_per_swing": "Squared-Up%",
                    "blast_per_swing": "Blast%",
                }),
                use_container_width=True,
                hide_index=True,
            )

if pitching is not None and is_pitcher_role:
    style.colored_header("Pitching", "pitching", color)
    metrics = [
        ("ERA", f"{pitching['ERA']:.2f}", db.percentile_rank(qualified_pitching["ERA"], pitching["ERA"], lower_is_better=True), "ERA", "{:+.2f}", True),
        ("WHIP", f"{pitching['WHIP']:.3f}", db.percentile_rank(qualified_pitching["WHIP"], pitching["WHIP"], lower_is_better=True), "WHIP", "{:+.3f}", True),
        ("W-L", f"{int(pitching['W'])}-{int(pitching['L'])}", None, None, None, False),
        ("SV", int(pitching["SV"]), db.percentile_rank(qualified_pitching["SV"], pitching["SV"]), "SV", "{:+.0f}", False),
        ("IP", pitching["IP"], None, None, None, False),
        ("SO", int(pitching["SO"]), db.percentile_rank(qualified_pitching["SO"], pitching["SO"]), "SO", "{:+.0f}", False),
    ]
    cols = st.columns(6)
    for col, (label, value, pct, raw_col, fmt, lower_better) in zip(cols, metrics):
        if compare_mode and prior_pitching is not None and raw_col:
            delta_text, delta_color = stat_delta(prior_pitching, raw_col, pitching[raw_col], fmt, lower_better)
        else:
            delta_text, delta_color = (f"{pct}th pctile" if pct is not None else None), "off"
        col.metric(label, value, delta_text, delta_color=delta_color)

    # Pitch Arsenal only makes sense for an actual pitcher — a position
    # player who mopped up an inning in a blowout still has a pitching row
    # (get_player_pitching above just checks for that row's existence), but
    # a handful of position-player pitches isn't a real "arsenal".
    is_pitcher = "Pitcher" in selected_roles
    tab_labels = ["Standard", "Advanced", "Statcast"] + (["Pitch Arsenal"] if is_pitcher else [])
    tabs = st.tabs(tab_labels)
    std_tab, adv_tab, sc_tab = tabs[:3]
    arsenal_tab = tabs[3] if is_pitcher else None
    with std_tab:
        st.dataframe(
            pitching[["G", "GS", "W", "L", "SV", "IP", "ERA", "WHIP", "SO", "BB", "HR"]]
            .to_frame().T,
            use_container_width=True,
            hide_index=True,
        )
    with adv_tab:
        st.dataframe(
            pitching[["FIP", "K_9", "BB_9", "K_BB", "WAR", "ERA_plus"]]
            .rename({"K_9": "K/9", "BB_9": "BB/9", "K_BB": "K/BB", "ERA_plus": "ERA+"})
            .to_frame().T,
            use_container_width=True,
            hide_index=True,
        )
    with sc_tab:
        st.dataframe(
            pitching[["avg_exit_velo_against", "hard_hit_pct_against", "barrel_pct_against"]]
            .rename({
                "avg_exit_velo_against": "Avg EV Against",
                "hard_hit_pct_against": "Hard-Hit% Against",
                "barrel_pct_against": "Barrel% Against",
            })
            .to_frame().T,
            use_container_width=True,
            hide_index=True,
        )
    if arsenal_tab is not None:
        with arsenal_tab:
            arsenal = db.get_player_pitch_arsenal(mlbID, season, mtime)
            if arsenal.empty:
                st.caption("No pitch-level Statcast data for this season.")
            else:
                arsenal_display = arsenal[[
                    "pitch_name", "usage_pct", "velocity", "spin_rate", "whiff_pct",
                    "vert_break", "horz_break", "run_value",
                ]].rename(columns={
                    "pitch_name": "Pitch", "usage_pct": "Usage %", "velocity": "Velo (mph)",
                    "spin_rate": "Active Spin %", "whiff_pct": "Whiff %", "vert_break": "Vert Break (in)",
                    "horz_break": "Horz Break (in)", "run_value": "Run Value",
                })
                st.dataframe(
                    style.style_stats_table(
                        arsenal_display,
                        higher_better=["Usage %", "Velo (mph)", "Whiff %", "Run Value"],
                        precision={"Usage %": "{:.1f}", "Velo (mph)": "{:.1f}", "Active Spin %": "{:.1f}",
                                   "Whiff %": "{:.1f}", "Vert Break (in)": "{:.1f}", "Horz Break (in)": "{:.1f}"},
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
                st.caption("Active Spin % — 2020+ only; blank for older seasons or pitch types Statcast doesn't track it for.")

                st.markdown("**Pitch Locations**")
                with st.spinner("Loading pitch-by-pitch data — first load can take 20-30s..."):
                    pitches = db.load_pitch_locations(mlbID, season)
                if pitches.empty:
                    st.caption("No pitch-level location data available for this season.")
                else:
                    pitch_types = sorted(pitches["pitch_name"].dropna().unique().tolist())
                    loc_pitch = st.selectbox("Pitch type", ["All"] + pitch_types, key="pitch_loc_type")
                    plot_df = pitches if loc_pitch == "All" else pitches[pitches["pitch_name"] == loc_pitch]
                    fig = px.density_heatmap(
                        plot_df, x="plate_x", y="plate_z", nbinsx=25, nbinsy=25,
                        color_continuous_scale="Turbo",
                    )
                    fig.add_shape(
                        type="rect", x0=-0.83, x1=0.83, y0=1.5, y1=3.5,
                        line=dict(color="#FAFAFA", width=2),
                    )
                    fig.update_yaxes(range=[0, 5], scaleanchor="x", scaleratio=1)
                    fig.update_xaxes(range=[-2.5, 2.5])
                    fig.update_layout(
                        height=460, margin=dict(l=0, r=0, t=10, b=0),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA",
                        xaxis_title="Horizontal — catcher's view (ft)", yaxis_title="Height (ft)",
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    st.caption(
                        f"{len(plot_df)} pitches shown. White box is a league-average strike zone "
                        "(17in plate, 1.5-3.5ft off the ground) — an individual batter's real zone varies with height/stance."
                    )

if not fielding.empty:
    style.colored_header("Fielding", "fielding", color)
    st.caption("Outs Above Average (OAA) by position — Statcast.")
    st.dataframe(
        fielding[["Pos", "OAA", "FRP", "success_rate"]].rename(columns={"success_rate": "Success Rate"}),
        use_container_width=True,
        hide_index=True,
    )

    positions_played = set(fielding["Pos"].dropna())
    if positions_played & {"C"}:
        framing = db.load_catcher_framing(season, mtime)
        framing = framing[framing["mlbID"] == mlbID] if "mlbID" in framing.columns else framing.iloc[0:0]
        poptime = db.load_catcher_poptime(season, mtime)
        poptime = poptime[poptime["mlbID"] == mlbID] if "mlbID" in poptime.columns else poptime.iloc[0:0]
        if not framing.empty or not poptime.empty:
            st.caption("Catcher framing (pitch-framing runs saved) and pop time (throw speed to 2nd/3rd on steals).")
            cols = st.columns(2)
            with cols[0]:
                if not framing.empty:
                    st.dataframe(
                        framing[["framing_runs", "framing_pct"]].rename(
                            columns={"framing_runs": "Framing Runs", "framing_pct": "Framing Pctile"}
                        ),
                        use_container_width=True, hide_index=True,
                    )
            with cols[1]:
                if not poptime.empty:
                    st.dataframe(
                        poptime[["pop_2b", "pop_3b", "exchange_time"]].rename(
                            columns={"pop_2b": "Pop Time 2B (s)", "pop_3b": "Pop Time 3B (s)",
                                     "exchange_time": "Exchange (s)"}
                        ),
                        use_container_width=True, hide_index=True,
                    )
    if positions_played & {"LF", "CF", "RF"}:
        jump = db.load_outfield_jump(season, mtime)
        jump = jump[jump["mlbID"] == mlbID] if "mlbID" in jump.columns else jump.iloc[0:0]
        if not jump.empty:
            st.caption("Outfielder jump — reaction/burst/route distance vs. league average (feet), on 2-star-or-harder plays.")
            st.dataframe(
                jump[["reaction", "burst", "routing"]].rename(
                    columns={"reaction": "Reaction (ft)", "burst": "Burst (ft)", "routing": "Routing (ft)"}
                ),
                use_container_width=True, hide_index=True,
            )

if not is_retired and (batting is not None or pitching is not None):
    style.colored_header("Season Trend", "headliners", color)
    stat_col, stat_label, role_filter = (
        ("ERA", "ERA", "Pitcher") if selected_roles == "Pitcher" else ("OPS", "OPS", "Batter")
    )
    trend = history[(history["role"] == role_filter) & history[stat_col].notna()]
    if len(trend) >= 2:
        fig = px.line(trend, x="date", y=stat_col, markers=True, labels={"date": "Date", stat_col: stat_label})
        fig.update_traces(line_color="#3B82F6", marker_color="#3B82F6")
        fig.update_layout(
            height=320, margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="#FAFAFA",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Trend builds up day by day from the daily refresh — check back after a few more days of data.")

arc_is_batter = is_batter_role
if batting is not None or pitching is not None:
    style.colored_header("Career Arc", "headliners", color)
    arc_col1, arc_col2 = st.columns([2, 1])
    with arc_col1:
        arc_stat = st.selectbox(
            "Track", db.CAREER_ARC_BATTING_STATS if arc_is_batter else db.CAREER_ARC_PITCHING_STATS,
            key="career_arc_stat", format_func=lambda s: db.STAT_DISPLAY_LABELS.get(s, s),
        )
    with arc_col2:
        arc_x_axis = st.radio("X-axis", ["Season", "Age"], key="career_arc_x_axis", horizontal=True)
    arc_stat_label = db.STAT_DISPLAY_LABELS.get(arc_stat, arc_stat)

    if arc_x_axis == "Season":
        arc_df = db.player_career_arc(mlbID, arc_is_batter, arc_stat, mtime)
        if len(arc_df) >= 2:
            fig = px.line(
                arc_df, x="season", y="stat", markers=True, labels={"season": "Season", "stat": arc_stat_label},
            )
            fig.update_traces(line_color="#3B82F6", marker_color="#3B82F6")
            fig.update_layout(
                height=320, margin=dict(l=0, r=0, t=10, b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font_color="#FAFAFA", xaxis=dict(dtick=1),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("Not enough cached seasons yet to show a season-by-season arc for this stat.")
    else:
        league_curve = db.league_aging_curve(arc_is_batter, arc_stat, mtime)
        player_points = db.player_aging_points(mlbID, arc_is_batter, arc_stat, mtime)
        if len(player_points) >= 2 and len(league_curve) >= 2:
            st.caption(
                f"Dotted line = league average {arc_stat_label} by age (qualified players, every cached season). "
                f"Solid line = {selected_name}'s own {arc_stat_label} by age."
            )
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=league_curve["Age"], y=league_curve["stat"], mode="lines",
                name="League average", line=dict(color="#9AA3B5", width=2, dash="dot"),
            ))
            fig.add_trace(go.Scatter(
                x=player_points["Age"], y=player_points["stat"], mode="lines+markers",
                name=selected_name, line=dict(color="#3B82F6", width=3), marker=dict(size=8),
            ))
            fig.update_layout(
                height=340, margin=dict(l=0, r=0, t=10, b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font_color="#FAFAFA", xaxis_title="Age", yaxis_title=arc_stat_label,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("Not enough cached seasons yet to show an age curve for this stat.")

if batting is not None or pitching is not None:
    style.colored_header("League Distribution", "chart")
    if batting is not None and is_batter_role:
        dist_df = qualified_batting.dropna(subset=["OPS"])
        fig = px.histogram(dist_df, x="OPS", nbins=40, labels={"OPS": "OPS (min 50 PA)"})
        fig.add_vline(x=batting["OPS"], line_color="#3B82F6", line_width=3)
        fig.update_layout(
            height=320, margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="#FAFAFA", showlegend=False,
        )
        st.caption(f"Blue line = {selected_name}'s OPS against all qualified batters.")
        st.plotly_chart(fig, use_container_width=True)
    if pitching is not None and is_pitcher_role:
        dist_df = qualified_pitching.dropna(subset=["ERA"])
        fig = px.histogram(dist_df, x="ERA", nbins=40, labels={"ERA": "ERA (min 20 IP)"})
        fig.add_vline(x=pitching["ERA"], line_color="#3B82F6", line_width=3)
        fig.update_layout(
            height=320, margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="#FAFAFA", showlegend=False,
        )
        st.caption(f"Blue line = {selected_name}'s ERA against all qualified pitchers.")
        st.plotly_chart(fig, use_container_width=True)

if batting is None and pitching is None and fielding.empty:
    st.info("No stats found for this player in the selected season.")
