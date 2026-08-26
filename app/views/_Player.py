import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import following
import localstorage_bridge
import style
import teams

st.set_page_config(page_title="Player | Diamond Metrics", layout="wide")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

# NOTE: deliberately does NOT call following.bootstrap() — main.py already
# does, once per rerun, and calling it a second time in the same run is
# actively destructive. Its guard is:
#     if "followed_teams" in st.session_state:
#         st.session_state["_following_safe_to_save"] = True; return
# On a fresh session main.py's call seeds empty placeholder lists and sets
# that flag FALSE (real data hasn't been read out of localStorage yet). A
# second call sees the key it just wrote, takes the early return, and flips
# the flag to True — so save() at the bottom of this script then writes the
# empty placeholder over the visitor's actual follow list. That is exactly
# the clobber the flag exists to prevent.
localstorage_bridge.register("following", following.STORAGE_KEY)

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

# Keep the URL in sync with what's actually on screen. Streamlit Cloud
# drops websocket sessions often; on reconnect the page re-hydrates from
# the URL's query params, and if those still said the OLD season (or old
# player, after a sidebar-search switch), the view silently snapped back —
# which read as "switching years doesn't work."
if st.query_params.get("mlbid") != str(mlbID) or st.query_params.get("season") != str(season):
    st.query_params.update({"mlbid": str(mlbID), "season": str(season)})

# "Retired" is judged against the CURRENT season specifically, independent
# of whichever season is being viewed above — a player who's active now
# but has no row in some earlier off-year isn't retired, and a retired
# player is still retired even while you're looking at their 2019 season.
# MLB's own "active" flag is the real signal (see db.is_player_active) —
# a player can easily have zero stats rows this season just from missing
# it hurt (e.g. Félix Bautista), which looked identical to retirement
# under the old no-stats-this-season-only check. Only fall back to that
# heuristic if the live lookup fails.
_active_flag = db.is_player_active(mlbID)
if _active_flag is None:
    is_retired = (
        db.get_player_batting(mlbID, current_season, mtime) is None
        and db.get_player_pitching(mlbID, current_season, mtime) is None
    )
else:
    is_retired = not _active_flag

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

def _splits_table(splits: dict, columns: list):
    """Renders Home/Away/vs-L/vs-R as one row-per-split table. `columns` is
    [(display_label, MLB-Stats-API stat key, format string)]; a missing or
    zero-sample split (no AB/IP yet) is skipped rather than shown as a row
    of zeroes."""
    if not splits:
        st.caption("No split data available for this season.")
        return
    rows = []
    for label, stat in splits.items():
        if not stat or not (stat.get("atBats") or stat.get("inningsPitched")):
            continue
        row = {"Split": label}
        for disp, key, fmt in columns:
            val = stat.get(key)
            try:
                row[disp] = fmt.format(float(val)) if val not in (None, "-.--", ".---") else "—"
            except (TypeError, ValueError):
                row[disp] = val if val is not None else "—"
        rows.append(row)
    if not rows:
        st.caption("No split data available for this season.")
        return
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _stat_table(row, spec):
    """One-row stat table from a season row. `spec` is [(column, label)];
    a column this season's row doesn't carry is skipped rather than raising,
    so a stat that only exists for recent seasons (bat tracking, the x-stats)
    just drops out on older ones instead of breaking the whole tab."""
    present = [(c, lbl) for c, lbl in spec if c in row.index]
    if not present:
        st.caption("No data for this season.")
        return
    frame = (
        row[[c for c, _ in present]]
        .rename({c: lbl for c, lbl in present})
        .to_frame().T
    )
    st.dataframe(frame, use_container_width=True, hide_index=True)


all_batting = db.load_batting(season, mtime)
all_pitching = db.load_pitching(season, mtime)
qualified_batting = all_batting[all_batting["PA"] >= db.QUALIFIED_MIN_PA]
qualified_pitching = all_pitching[all_pitching["IP"] >= db.QUALIFIED_MIN_IP]

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
        "<span style='background-color:var(--dm-line);color:var(--dm-text);padding:4px 12px;"
        "border-radius:10px;font-size:0.5em;vertical-align:middle;font-weight:600;margin-left:6px'>RETIRED</span>"
        if is_retired else ""
    )
    hof_badge = (
        "<span style='background-color:var(--dm-amber-soft);color:#3A2F00;padding:4px 12px;"
        "border-radius:10px;font-size:0.5em;vertical-align:middle;font-weight:700;margin-left:6px'>HOF</span>"
        if mlbID in db.HALL_OF_FAME_MLBIDS else ""
    )
    st.markdown(
        f"# {selected_name} "
        f"<span style='background-color:{color}66;color:var(--dm-text);padding:4px 12px;"
        f"border-radius:10px;font-size:0.5em;vertical-align:middle;font-weight:600'>{abbr}</span>"
        f"{retired_badge}{hof_badge}",
        unsafe_allow_html=True,
    )
    st.caption(f"{nickname} · Age {age} · {selected_roles}")

    # Follow/unfollow, mirroring the Following page's own list (same
    # session_state keys, same localStorage payload) so the two stay in
    # sync — following here shows up there and vice versa.
    _followed = st.session_state.setdefault("followed_players", [])
    _is_following = any(int(p.get("mlbID", -1)) == int(mlbID) for p in _followed)
    _follow_col, _ = st.columns([1, 3])
    with _follow_col:
        # Mutate then rerun, and let the single following.save() at the
        # bottom of this script do the persisting. Calling save() here
        # instead would queue its localStorage <script> and then have
        # st.rerun() throw the render away before the browser ever ran it.
        if _is_following:
            if st.button("Following", key=f"follow_btn_{mlbID}", type="primary",
                         help="Click to unfollow", use_container_width=True):
                st.session_state["followed_players"] = [
                    p for p in _followed if int(p.get("mlbID", -1)) != int(mlbID)
                ]
                st.rerun()
        else:
            if st.button("Follow", key=f"follow_btn_{mlbID}",
                         help="Track this player on the Following page", use_container_width=True):
                _followed.append({"mlbID": int(mlbID), "name": selected_name})
                st.rerun()

    st.markdown(
        "<button id='share-link-btn' style='background-color:var(--dm-blue-soft);color:var(--dm-blue-text);"
        "border:1px solid var(--dm-blue-soft);border-radius:8px;padding:3px 12px;font-size:0.8rem;"
        "cursor:pointer;margin-top:4px'>\U0001F517 Copy share link</button>"
        "<span id='share-link-copied' style='display:none;color:var(--dm-green);font-size:0.8rem;"
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
        f"<span style='background-color:var(--dm-green-soft);color:var(--dm-green);padding:3px 10px;"
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

    std_tab, adv_tab, sc_tab, bb_tab, splits_tab = st.tabs(["Standard", "Advanced", "Statcast", "Batted Ball", "Splits"])
    with std_tab:
        st.dataframe(
            batting[["G", "PA", "AB", "R", "H", "2B", "3B", "HR", "RBI", "BB", "SO", "SB", "CS"]]
            .to_frame().T,
            use_container_width=True,
            hide_index=True,
        )
    with adv_tab:
        _stat_table(batting, [
            ("ISO", "ISO"), ("BABIP", "BABIP"), ("K_PCT", "K%"), ("BB_PCT", "BB%"),
            ("wOBA", "wOBA"), ("xwOBA", "xwOBA"), ("xOBP", "xOBP"), ("xISO", "xISO"),
            ("OPS_plus", "OPS+"), ("wRC_plus", "wRC+"), ("WAR", "WAR"),
        ])
    with sc_tab:
        _stat_table(batting, [
            ("avg_exit_velo", "Avg EV"), ("max_exit_velo", "Max EV"),
            ("hard_hit_pct", "Hard-Hit%"), ("barrel_pct", "Barrel%"),
            ("contact_pct", "Contact%"), ("chase_pct", "Chase%"),
            ("bat_speed", "Bat Speed"),
            ("xBA", "xBA"), ("xSLG", "xSLG"),
            # Actual minus expected — the "is this earned or is it luck?"
            # columns, which are the point of carrying the x-stats at all.
            ("xBA_diff", "BA − xBA"), ("xSLG_diff", "SLG − xSLG"), ("xwOBA_diff", "wOBA − xwOBA"),
        ])
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
    with splits_tab:
        with st.spinner("Loading splits..."):
            bat_splits = db.load_split_stats(mlbID, season, "hitting")
        _splits_table(bat_splits, [
            ("PA", "plateAppearances", "{:.0f}"), ("AVG", "avg", "{:.3f}"), ("OBP", "obp", "{:.3f}"),
            ("SLG", "slg", "{:.3f}"), ("OPS", "ops", "{:.3f}"), ("HR", "homeRuns", "{:.0f}"),
            ("RBI", "rbi", "{:.0f}"), ("BB", "baseOnBalls", "{:.0f}"), ("SO", "strikeOuts", "{:.0f}"),
        ])

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
    tab_labels = ["Standard", "Advanced", "Statcast", "Splits"] + (["Pitch Arsenal"] if is_pitcher else [])
    tabs = st.tabs(tab_labels)
    std_tab, adv_tab, sc_tab, pitch_splits_tab = tabs[:4]
    arsenal_tab = tabs[4] if is_pitcher else None
    with std_tab:
        st.dataframe(
            pitching[["G", "GS", "W", "L", "SV", "IP", "ERA", "WHIP", "SO", "BB", "HR"]]
            .to_frame().T,
            use_container_width=True,
            hide_index=True,
        )
    with adv_tab:
        _stat_table(pitching, [
            ("FIP", "FIP"), ("xFIP", "xFIP"), ("xERA", "xERA"),
            ("K_9", "K/9"), ("BB_9", "BB/9"), ("K_BB", "K/BB"),
            ("BAbip", "BABIP"), ("GB_FB", "GB/FB"),
            ("ERA_plus", "ERA+"), ("dWAR", "dWAR"), ("fWAR", "fWAR"), ("WAR", "bWAR"),
        ])
    with sc_tab:
        _stat_table(pitching, [
            ("avg_exit_velo_against", "Avg EV Against"),
            ("hard_hit_pct_against", "Hard-Hit% Against"),
            ("barrel_pct_against", "Barrel% Against"),
            ("xBA_against", "xBA Against"), ("xSLG_against", "xSLG Against"),
            ("xwOBA_against", "xwOBA Against"), ("xERA_diff", "ERA − xERA"),
            ("fastball_velo", "Fastball Velo"), ("induced_chase_pct", "Induced Chase%"),
        ])
    with pitch_splits_tab:
        with st.spinner("Loading splits..."):
            pitch_splits = db.load_split_stats(mlbID, season, "pitching")
        _splits_table(pitch_splits, [
            ("IP", "inningsPitched", "{}"), ("ERA", "era", "{:.2f}"), ("WHIP", "whip", "{:.2f}"),
            ("SO", "strikeOuts", "{:.0f}"), ("BB", "baseOnBalls", "{:.0f}"), ("HR", "homeRuns", "{:.0f}"),
        ])
    if arsenal_tab is not None:
        with arsenal_tab:
            arsenal = db.get_player_pitch_arsenal(mlbID, season, mtime)
            if arsenal.empty:
                st.caption("No pitch-level Statcast data for this season.")
            else:
                arsenal_cols = {
                    "pitch_name": "Pitch", "usage_pct": "Usage %", "velocity": "Velo",
                    "spin_rate": "Active Spin %", "vert_break": "IVB", "horz_break": "HB",
                    "whiff_pct": "Whiff %", "ba": "BA", "slg": "SLG", "woba": "wOBA",
                    "hard_hit_percent": "Hard-Hit %", "run_value_per_100": "RV/100",
                }
                # Results-against columns only exist on rows ingested with the
                # extended schema (2017+) — show whichever are present.
                arsenal_cols = {k: v for k, v in arsenal_cols.items() if k in arsenal.columns}
                arsenal_display = arsenal[list(arsenal_cols)].rename(columns=arsenal_cols)
                st.dataframe(
                    style.style_stats_table(
                        arsenal_display,
                        higher_better=[c for c in ["Whiff %", "RV/100"] if c in arsenal_display.columns],
                        lower_better=[c for c in ["BA", "SLG", "wOBA", "Hard-Hit %"] if c in arsenal_display.columns],
                        precision={"Usage %": "{:.1f}", "Velo": "{:.1f}", "Active Spin %": "{:.1f}",
                                   "IVB": "{:.1f}", "HB": "{:.1f}", "Whiff %": "{:.1f}",
                                   "BA": "{:.3f}", "SLG": "{:.3f}", "wOBA": "{:.3f}",
                                   "Hard-Hit %": "{:.1f}", "RV/100": "{:+.1f}"},
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
                st.caption(
                    "IVB/HB = induced vertical / horizontal break (inches). BA/SLG/wOBA = what hitters "
                    "produce against that pitch. RV/100 = run value per 100 pitches, pitcher's "
                    "perspective — positive is good. Active Spin % is 2020+ only."
                )

                # Movement cloud: this pitcher's pitches vs. the whole league.
                league_arsenal = db.load_pitch_arsenal(season, mtime)
                if not league_arsenal.empty and "vert_break" in arsenal.columns:
                    st.markdown("**Movement vs. the League**")
                    st.caption(
                        "Every dot is one pitcher's version of a pitch, from the whole league. "
                        "The labeled dots are this pitcher's — far from the pack means movement "
                        "hitters rarely see."
                    )
                    fig = go.Figure()
                    cloud = league_arsenal.dropna(subset=["vert_break", "horz_break"])
                    for pname, seg in cloud.groupby("pitch_name"):
                        fig.add_trace(go.Scatter(
                            x=seg["horz_break"], y=seg["vert_break"], mode="markers",
                            marker=dict(size=5, color=style.PITCH_COLORS.get(pname, style.CHART_DIM), opacity=0.15),
                            hoverinfo="skip", showlegend=False,
                        ))
                    mine_mv = arsenal.dropna(subset=["vert_break", "horz_break"])
                    for _, prow in mine_mv.iterrows():
                        fig.add_trace(go.Scatter(
                            x=[prow["horz_break"]], y=[prow["vert_break"]], mode="markers+text",
                            name=prow["pitch_name"], text=[prow["pitch_name"]], textposition="top center",
                            textfont=dict(size=11, color="#FAFAFA"),
                            marker=dict(size=14, color=style.PITCH_COLORS.get(prow["pitch_name"], style.CHART_TEXT),
                                        line=dict(width=2, color=style.CHART_TEXT)),
                            showlegend=False,
                        ))
                    fig.add_hline(y=0, line_color="rgba(154,163,181,0.4)", line_width=1)
                    fig.add_vline(x=0, line_color="rgba(154,163,181,0.4)", line_width=1)
                    fig.update_xaxes(title="Horizontal Break (in)", gridcolor="rgba(74,82,102,0.25)", color=style.CHART_DIM)
                    fig.update_yaxes(title="Induced Vertical Break (in)", gridcolor="rgba(74,82,102,0.25)", color=style.CHART_DIM)
                    fig.update_layout(
                        height=440, margin=dict(l=10, r=10, t=10, b=10),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=style.CHART_TEXT,
                    )
                    st.plotly_chart(fig, use_container_width=True)

                # Year-over-year arsenal changes for this pitcher.
                history_arsenal = db.load_pitch_arsenal_all_seasons(mtime)
                mine_hist = history_arsenal[history_arsenal["mlbID"] == mlbID] if not history_arsenal.empty else history_arsenal
                if not mine_hist.empty and mine_hist["season"].nunique() > 1:
                    st.markdown("**Arsenal Over the Years**")
                    st.caption("Usage and velocity by season — new pitches appearing, old ones shelved, velocity trends.")
                    metric_pick = st.radio(
                        "Arsenal trend metric", ["Usage %", "Velocity"], horizontal=True,
                        key=f"arsenal_trend_{mlbID}", label_visibility="collapsed",
                    )
                    metric_col = "usage_pct" if metric_pick == "Usage %" else "velocity"
                    fig = go.Figure()
                    for pname, seg in mine_hist.dropna(subset=[metric_col]).groupby("pitch_name"):
                        seg = seg.sort_values("season")
                        fig.add_trace(go.Scatter(
                            x=seg["season"], y=seg[metric_col], mode="lines+markers", name=pname,
                            line=dict(color=style.PITCH_COLORS.get(pname, style.CHART_DIM), width=2.5),
                            marker=dict(size=7),
                        ))
                    fig.update_xaxes(dtick=1, gridcolor="rgba(74,82,102,0.25)", color=style.CHART_DIM)
                    fig.update_yaxes(
                        title="Usage %" if metric_col == "usage_pct" else "Velo (mph)",
                        gridcolor="rgba(74,82,102,0.25)", color=style.CHART_DIM,
                    )
                    fig.update_layout(
                        height=380, margin=dict(l=10, r=10, t=10, b=10),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=style.CHART_TEXT,
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                    )
                    st.plotly_chart(fig, use_container_width=True)

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
                        color_continuous_scale=style.HEAT_SCALE,
                    )
                    fig.add_shape(
                        type="rect", x0=-0.83, x1=0.83, y0=1.5, y1=3.5,
                        line=dict(color=style.CHART_TEXT, width=2),
                    )
                    fig.update_yaxes(range=[0, 5], scaleanchor="x", scaleratio=1)
                    fig.update_xaxes(range=[-2.5, 2.5])
                    fig.update_layout(
                        height=460, margin=dict(l=0, r=0, t=10, b=0),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=style.CHART_TEXT,
                        xaxis_title="Horizontal — catcher's view (ft)", yaxis_title="Height (ft)",
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    st.caption(
                        f"{len(plot_df)} pitches shown. White box is a league-average strike zone "
                        "(17in plate, 1.5-3.5ft off the ground) — an individual batter's real zone varies with height/stance."
                    )

                    st.markdown("**Pitch Mix by Count**")
                    if "balls" not in pitches.columns or "strikes" not in pitches.columns:
                        st.caption("No count data available for this season.")
                    else:
                        pitch_colors = {
                            name: px.colors.qualitative.Set2[i % len(px.colors.qualitative.Set2)]
                            for i, name in enumerate(pitch_types)
                        }
                        # A count-progression tree, not a grid: 0-0 at the top,
                        # branching down to every count reachable from it (a
                        # ball moves right, a strike moves left), same shape as
                        # how an at-bat actually unfolds. Node x is balls minus
                        # strikes (so 1-0 and 0-1 sit symmetrically either side
                        # of 0-0), node y is balls-plus-strikes (pitch count
                        # depth) — both mapped from data space into [0,1] paper
                        # fractions so pies (which only place via `domain`, not
                        # x/y data coords) and their connecting lines (drawn in
                        # `paper` ref, which shares that same [0,1] space) line
                        # up exactly.
                        valid_counts = [(b, s) for b in range(4) for s in range(3)]
                        depth = {c: c[0] + c[1] for c in valid_counts}
                        offset = {c: c[0] - c[1] for c in valid_counts}
                        min_off, max_off = min(offset.values()), max(offset.values())
                        max_depth = max(depth.values())

                        def _node_center(c):
                            x = 0.06 + (offset[c] - min_off) / (max_off - min_off) * 0.88
                            y = 0.95 - (depth[c] / max_depth) * 0.88
                            return x, y

                        centers = {c: _node_center(c) for c in valid_counts}
                        node_w, node_h = 0.15, 0.15

                        shapes = []
                        for (b, s) in valid_counts:
                            cx, cy = centers[(b, s)]
                            for child in ((b + 1, s), (b, s + 1)):
                                if child in centers:
                                    nx, ny = centers[child]
                                    shapes.append(dict(
                                        type="line", xref="paper", yref="paper",
                                        x0=cx, y0=cy, x1=nx, y1=ny,
                                        line=dict(color="rgba(250,250,250,0.25)", width=1.5),
                                        layer="below",
                                    ))

                        annotations = []
                        count_fig = go.Figure()
                        any_count_data = False
                        legend_shown = False
                        for c in valid_counts:
                            b, s = c
                            cx, cy = centers[c]
                            annotations.append(dict(
                                x=cx, y=cy + node_h / 2 + 0.025, xref="paper", yref="paper",
                                text=f"{b}-{s}", showarrow=False, font=dict(color="#FAFAFA", size=12),
                            ))
                            count_df = pitches[(pitches["balls"] == b) & (pitches["strikes"] == s)]
                            mix = count_df["pitch_name"].value_counts()
                            if mix.empty:
                                continue
                            any_count_data = True
                            count_fig.add_trace(go.Pie(
                                labels=mix.index, values=mix.values,
                                marker=dict(colors=[pitch_colors.get(n, "#888") for n in mix.index]),
                                textinfo="none", hole=0.35, sort=False,
                                domain=dict(
                                    x=[max(0, cx - node_w / 2), min(1, cx + node_w / 2)],
                                    y=[max(0, cy - node_h / 2), min(1, cy + node_h / 2)],
                                ),
                                showlegend=not legend_shown,
                            ))
                            legend_shown = True
                        if not any_count_data:
                            st.caption("Not enough pitches with count data to break down by count.")
                        else:
                            count_fig.update_layout(
                                shapes=shapes, annotations=annotations,
                                height=800, margin=dict(l=0, r=0, t=10, b=0),
                                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=style.CHART_TEXT,
                                legend=dict(orientation="h", yanchor="bottom", y=-0.03),
                            )
                            st.plotly_chart(count_fig, use_container_width=True)
                            st.caption(
                                "0-0 at the top, branching down through every count reachable from it "
                                "(right on a ball, left on a strike) to 3-2 at the bottom — each donut is "
                                "that count's pitch mix. Missing nodes mean that count barely came up."
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
                            # framing_pct is Savant's shadow-zone strike RATE (0-1),
                            # not a percentile — previously mislabeled here.
                            columns={"framing_runs": "Framing Runs", "framing_pct": "Strike Rate"}
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
        fig.update_traces(line_color=style.CHART_BLUE, marker_color=style.CHART_BLUE)
        fig.update_layout(
            height=320, margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color=style.CHART_TEXT,
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
            fig.update_traces(line_color=style.CHART_BLUE, marker_color=style.CHART_BLUE)
            fig.update_layout(
                height=320, margin=dict(l=0, r=0, t=10, b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font_color=style.CHART_TEXT, xaxis=dict(dtick=1),
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
                name="League average", line=dict(color=style.CHART_DIM, width=2, dash="dot"),
            ))
            fig.add_trace(go.Scatter(
                x=player_points["Age"], y=player_points["stat"], mode="lines+markers",
                name=selected_name, line=dict(color=style.CHART_BLUE, width=3), marker=dict(size=8),
            ))
            fig.update_layout(
                height=340, margin=dict(l=0, r=0, t=10, b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font_color=style.CHART_TEXT, xaxis_title="Age", yaxis_title=arc_stat_label,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("Not enough cached seasons yet to show an age curve for this stat.")

if batting is not None or pitching is not None:
    style.colored_header("League Distribution", "chart")
    if batting is not None and is_batter_role:
        dist_df = qualified_batting.dropna(subset=["OPS"])
        fig = px.histogram(dist_df, x="OPS", nbins=40, labels={"OPS": f"OPS (min {db.QUALIFIED_MIN_PA} PA)"})
        fig.add_vline(x=batting["OPS"], line_color="#3B82F6", line_width=3)
        fig.update_layout(
            height=320, margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color=style.CHART_TEXT, showlegend=False,
        )
        st.caption(f"Blue line = {selected_name}'s OPS against all qualified batters.")
        st.plotly_chart(fig, use_container_width=True)
    if pitching is not None and is_pitcher_role:
        dist_df = qualified_pitching.dropna(subset=["ERA"])
        fig = px.histogram(dist_df, x="ERA", nbins=40, labels={"ERA": f"ERA (min {db.QUALIFIED_MIN_IP} IP)"})
        fig.add_vline(x=pitching["ERA"], line_color="#3B82F6", line_width=3)
        fig.update_layout(
            height=320, margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color=style.CHART_TEXT, showlegend=False,
        )
        st.caption(f"Blue line = {selected_name}'s ERA against all qualified pitchers.")
        st.plotly_chart(fig, use_container_width=True)

if batting is not None and is_batter_role:
    spray = db.player_batted_ball_events(mlbID, season)
    if not spray.empty:
        qoc = db.quality_of_contact_score(mlbID, season)
        if qoc:
            style.colored_header("Quality of Contact", "chart")
            st.caption(
                "Our own 1-100 composite of hard-hit rate, barrel rate, and average exit "
                "velocity — not an official MLB/Statcast stat, scaled against fixed league-"
                "average reference points rather than the current league pool."
            )
            qc1, qc2, qc3, qc4 = st.columns(4)
            qc1.metric("Score", qoc["score"])
            qc2.metric("Hard-Hit%", f"{qoc['hard_hit_pct']:.1f}%")
            qc3.metric("Barrel%", f"{qoc['barrel_pct']:.1f}%")
            qc4.metric("Avg Exit Velo", f"{qoc['avg_ev']:.1f} mph")

        stadium_outline = db.team_stadium_outline(abbr)
        style.colored_header("Spray Chart", "chart")
        st.caption(f"{teams.franchise_display_name(abbr, season)}'s actual home park outline." if stadium_outline else "Generic field outline (no digitized park shape available for this team).")
        view_mode = st.radio(
            "Spray chart view", ["Top-Down", "3D Trajectory"], horizontal=True,
            key="spray_view_mode", label_visibility="collapsed",
        )
        # Wall/foul-line segments as plain (x_list, y_list) pairs rather than
        # go.Scatter traces directly — the 2D view below draws these flat at
        # z absent, the 3D view (style.trajectory_3d_chart) redraws the same
        # segments at z=0 as a ground reference, so both views share this
        # one field-shape computation instead of maintaining two copies.
        # See style.field_wall_lines for the real-park-vs-generic-fallback
        # logic (also shared with Game Center's own spray chart).
        field_lines = style.field_wall_lines(stadium_outline)

        if view_mode == "3D Trajectory":
            fig3d = style.trajectory_3d_chart(spray, field_lines, db.SPRAY_EVENT_COLORS)
            st.caption("Flight paths are an approximation — real Statcast trajectories account for drag, which isn't part of the public API; the start/end points are real, the arc connecting them is a plain projectile-motion curve.")
            st.plotly_chart(fig3d, use_container_width=True)
        else:
            fig = style.spray_chart_2d(spray, field_lines, db.SPRAY_EVENT_COLORS)
            # st.plotly_chart's own width/height params (not just the figure's
            # layout) determine the actual rendered box — its default
            # width="stretch" overrides fig.layout.width to fill the
            # container, which re-introduces the scaleanchor distortion the
            # fixed size in spray_chart_2d was meant to avoid. Passing them
            # explicitly here is what actually pins it.
            st.plotly_chart(fig, width=800, height=490)

        style.colored_header("Hot/Cold Zone", "chart")
        st.caption(
            "Average exit velocity by plate location — where this player does the most damage, not just "
            "where they put the bat on the ball. Blue = weak contact, red = hard contact."
        )
        st.plotly_chart(style.batter_zone_heatmap_chart(spray), use_container_width=True)

# Batting comps for a two-way player (both roles True) — matches the same
# "batting is authoritative" convention used for the header team badge above.
similarity_is_batter = batting is not None and is_batter_role
if similarity_is_batter or (pitching is not None and is_pitcher_role):
    style.colored_header("Similar Players", "headliners", color)
    similar = db.similar_players(mlbID, season, similarity_is_batter, mtime, n=5)
    if similar.empty:
        st.caption("Not enough qualified players this season to compute similarity.")
    else:
        st.caption(
            f"Statistically closest qualified {'batters' if similarity_is_batter else 'pitchers'} in {season}, "
            "by rate-stat profile (batting average, exit velocity, ERA, FIP, etc.) — not real scouting comps."
        )
        sim_cols = st.columns(len(similar))
        for sim_col, (_, row) in zip(sim_cols, similar.iterrows()):
            with sim_col:
                sim_abbr, _, sim_color = teams.team_meta_from_city(row["Tm"], row["Lev"])
                sim_link = style.player_link(row["mlbID"], season)
                st.markdown(
                    "<div style='text-align:center'>"
                    # display:block on the anchor so the photo and the name
                    # always stack — inline, a short name fit BESIDE the
                    # photo instead of under it.
                    f"<a href='{sim_link}' target='_self' style='color:inherit;text-decoration:none;"
                    f"display:block'>"
                    f"<img src='{style.headshot_url(row['mlbID'], width=140)}' style='width:72px;height:72px;"
                    "border-radius:10px;object-fit:cover;object-position:center 25%' />"
                    f"<div style='margin-top:6px;font-weight:700;overflow-wrap:break-word'>{row['Name']}</div></a>"
                    f"<div style='margin-top:4px'><span style='background-color:{sim_color}66;color:var(--dm-text);"
                    f"padding:2px 9px;border-radius:8px;font-size:0.75rem;font-weight:600'>{sim_abbr}</span></div>"
                    "</div>",
                    unsafe_allow_html=True,
                )

# Win Probability Impact — this player's WPA from our trained model (see
# the Clutch tabs on Batting/Pitching for the league-wide view).
wpa_bat = db.load_wpa_batting(season, mtime)
wpa_pit = db.load_wpa_pitching(season, mtime)
my_wpa_bat = wpa_bat[wpa_bat["mlbID"] == mlbID] if not wpa_bat.empty else wpa_bat
my_wpa_pit = wpa_pit[wpa_pit["mlbID"] == mlbID] if not wpa_pit.empty else wpa_pit
if (my_wpa_bat is not None and not my_wpa_bat.empty) or (my_wpa_pit is not None and not my_wpa_pit.empty):
    style.colored_header("Win Probability Impact", "headliners", color)
    st.caption(
        "WPA (Win Probability Added) — how much this player's plate appearances moved their "
        "team's chance of winning across the season, from our own trained win probability model. "
        "Timing matters: late, close-game production counts for more."
    )
    for label, mine in [("As batter", my_wpa_bat), ("As pitcher", my_wpa_pit)]:
        if mine is None or mine.empty:
            continue
        row = mine.iloc[0]
        st.markdown(f"**{label}**")
        c1, c2, c3 = st.columns(3)
        c1.metric("WPA", f"{row['wpa']:+.2f}")
        c2.metric("WPA+", f"{row['wpa_plus']:+.2f}")
        c3.metric("Biggest Play", f"{row['best_play_wpa'] * 100:+.0f}%")
        if isinstance(row["best_play_desc"], str) and row["best_play_desc"]:
            st.caption(f"Biggest play ({row['best_play_date']}): {row['best_play_desc']}")

awards = db.load_player_awards(mlbID)
if awards and awards["marquee"]:
    style.colored_header("Awards", "headliners", color)
    by_season = {}
    for a in awards["marquee"]:
        by_season.setdefault(a["season"], []).append(a)
    season_html = []
    for yr, entries in by_season.items():
        badges = "".join(
            f"<span style='background-color:{e['color']}33;color:{e['color']};padding:3px 10px;"
            f"border-radius:8px;font-weight:600;font-size:0.85rem;margin-right:6px;"
            f"display:inline-block;margin-bottom:4px'>{e['label']}</span>"
            for e in entries
        )
        season_html.append(
            f"<div style='margin-bottom:6px'>"
            f"<span style='color:var(--dm-dim);font-weight:600;margin-right:10px'>{yr}</span>{badges}</div>"
        )
    st.markdown("".join(season_html), unsafe_allow_html=True)
    if awards["other_count"]:
        st.caption(f"+{awards['other_count']} other honor{'s' if awards['other_count'] != 1 else ''}")

if batting is None and pitching is None and fielding.empty:
    st.info("No stats found for this player in the selected season.")

# Persists whatever's currently in session_state to this browser's
# localStorage — same unconditional end-of-render call the Following page
# makes (cheap and idempotent; see following.py). This is what makes the
# Follow button above stick.
following.save()
