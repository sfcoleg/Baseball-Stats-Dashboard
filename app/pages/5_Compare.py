"""Compare — two players head to head: skill radars, stat tables, clutch
impact, arsenal duel (pitchers), zone heatmaps (batters), career arc
overlay, batter-vs-pitcher matchup history, and catcher defense.
Deep-linkable via ?a=<mlbID>&b=<mlbID>&season=."""
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import prefs
import style
import teams

st.set_page_config(page_title="Compare | Diamond Metrics", layout="wide")
st.title("Compare Players")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
seasons = db.get_seasons("batting")

qp_season = st.query_params.get("season")
season_index = seasons.index(int(qp_season)) if qp_season and qp_season.isdigit() and int(qp_season) in seasons \
    else prefs.default_season_index(seasons)
season = st.selectbox("Season", seasons, index=season_index)

# Deep-link support: ?a=<mlbID>&b=<mlbID> pre-fills the two search boxes
# with those players' names (a name query resolves to exactly one match,
# so the pick logic below auto-selects them).
for param, key in [("a", "a_query"), ("b", "b_query")]:
    qp = st.query_params.get(param)
    if qp and qp.isdigit() and key not in st.session_state:
        with sqlite3.connect(db.DB_PATH) as _conn:
            row = _conn.execute(
                "SELECT Name FROM batting WHERE mlbID=? UNION SELECT Name FROM pitching WHERE mlbID=? LIMIT 1",
                (int(qp), int(qp)),
            ).fetchone()
        if row:
            st.session_state[key] = row[0]


def pick_player(label, key_prefix):
    query = st.text_input(label, key=f"{key_prefix}_query", placeholder="e.g. Ohtani, Judge")
    if not query.strip():
        return None
    matches = db.search_players(query, season, mtime)
    if matches.empty:
        st.warning(f"No players found matching '{query}'.")
        return None
    if len(matches) == 1:
        return matches.iloc[0]
    options = [f"{row.Name} ({row.Tm}) — {row.roles}" for row in matches.itertuples()]
    choice = st.selectbox(f"{len(matches)} matches", options, key=f"{key_prefix}_choice")
    return matches.iloc[options.index(choice)]


col_a, col_b = st.columns(2)
with col_a:
    selected_a = pick_player("Player A", "a")
with col_b:
    selected_b = pick_player("Player B", "b")

if selected_a is None or selected_b is None:
    st.info("Pick two players to compare.")
    st.stop()

if selected_a["mlbID"] == selected_b["mlbID"]:
    st.warning("Pick two different players.")
    st.stop()

# Make the current comparison shareable — anyone opening this URL lands on
# the same two players and season.
st.query_params.update({"a": str(int(selected_a["mlbID"])), "b": str(int(selected_b["mlbID"])), "season": str(season)})

st.divider()

id_a, id_b = int(selected_a["mlbID"]), int(selected_b["mlbID"])
name_a, name_b = selected_a["Name"], selected_b["Name"]

batting_a = db.get_player_batting(id_a, season, mtime)
batting_b = db.get_player_batting(id_b, season, mtime)
pitching_a = db.get_player_pitching(id_a, season, mtime)
pitching_b = db.get_player_pitching(id_b, season, mtime)
fielding_a = db.get_player_fielding(id_a, season, mtime)
fielding_b = db.get_player_fielding(id_b, season, mtime)

qualified_batting = db.load_batting(season, mtime)
qualified_batting = qualified_batting[qualified_batting["PA"] >= 50]
qualified_pitching = db.load_pitching(season, mtime)
qualified_pitching = qualified_pitching[qualified_pitching["IP"] >= 20]

# Role gates — a pitcher's incidental PA shouldn't trigger batting sections
# (mirrors _Player.py; two-way players pass both).
roles_a = db.player_roles_label(id_a, mtime)
roles_b = db.player_roles_label(id_b, mtime)
is_batter_a, is_pitcher_a = "Batter" in roles_a, "Pitcher" in roles_a
is_batter_b, is_pitcher_b = "Batter" in roles_b, "Pitcher" in roles_b
batting_role_a = batting_a if is_batter_a else None
batting_role_b = batting_b if is_batter_b else None
pitching_role_a = pitching_a if is_pitcher_a else None
pitching_role_b = pitching_b if is_pitcher_b else None

# Team colors drive each player's identity across every chart on the page.
def _team_meta(batting_row, pitching_row):
    row = batting_row if batting_row is not None else pitching_row
    if row is None:
        return ("—", "", "#666666")
    return teams.team_meta_from_city(row.get("Tm", ""), row.get("Lev"))


abbr_a, _, color_a = _team_meta(batting_a, pitching_a)
abbr_b, _, color_b = _team_meta(batting_b, pitching_b)
# Same team (or unknown) → identical radar/line colors; force contrast.
if color_b == color_a:
    color_b = "#93C5FD"


def team_badge(abbr, color):
    return (
        f"<span style='background-color:{color}66;color:var(--dm-text);padding:3px 10px;"
        f"border-radius:10px;font-weight:600'>{abbr}</span>"
    )


h1, h2 = st.columns(2)
h1.image(style.headshot_url(id_a, width=150), width=110)
h1.markdown(f"### {name_a} {team_badge(abbr_a, color_a)}", unsafe_allow_html=True)
h2.image(style.headshot_url(id_b, width=150), width=110)
h2.markdown(f"### {name_b} {team_badge(abbr_b, color_b)}", unsafe_allow_html=True)


def build_compare_table(row_a, row_b, fields, round_map=None):
    round_map = round_map or {}
    data = {}
    for label, col in fields:
        val_a = row_a[col] if row_a is not None else None
        val_b = row_b[col] if row_b is not None else None
        ndigits = round_map.get(label)
        if ndigits is not None:
            val_a = round(val_a, ndigits) if val_a is not None and not pd.isna(val_a) else val_a
            val_b = round(val_b, ndigits) if val_b is not None and not pd.isna(val_b) else val_b
        data[label] = [val_a, val_b]
    return pd.DataFrame(data, index=[name_a, name_b]).T


# --- Skill radars -----------------------------------------------------------
if batting_role_a is not None and batting_role_b is not None:
    style.colored_header("Batting Profile", "batting")
    # Skill axes, not counting stats — each is a percentile against
    # qualified batters, so the shape reads as strengths/weaknesses.
    radar_fields = [
        ("Production (wOBA)", "wOBA", False), ("Power (ISO)", "ISO", False),
        ("Contact%", "contact_pct", False), ("Plate Eye (Chase%)", "chase_pct", True),
        ("Hard-Hit%", "hard_hit_pct", False), ("Speed", "sprint_speed", False),
    ]
    values_a = [db.percentile_rank(qualified_batting[col], batting_role_a[col], lower) or 0 for _, col, lower in radar_fields]
    values_b = [db.percentile_rank(qualified_batting[col], batting_role_b[col], lower) or 0 for _, col, lower in radar_fields]
    st.caption("Percentile rank (0-100) against qualified batters (min 50 PA) league-wide.")
    st.plotly_chart(
        style.radar_chart([label for label, _, _ in radar_fields], values_a, values_b,
                          name_a, name_b, color_a, color_b),
        use_container_width=True,
    )

if pitching_role_a is not None and pitching_role_b is not None:
    style.colored_header("Pitching Profile", "pitching")
    radar_fields = [
        ("Run Prevention (FIP)", "FIP", True), ("Strikeouts (K/9)", "K_9", False),
        ("Command (BB/9)", "BB_9", True), ("Contact Mgmt (Hard-Hit%)", "hard_hit_pct_against", True),
        ("Velocity", "fastball_velo", False), ("Chase Induced", "induced_chase_pct", False),
    ]
    values_a = [db.percentile_rank(qualified_pitching[col], pitching_role_a[col], lower) or 0 for _, col, lower in radar_fields]
    values_b = [db.percentile_rank(qualified_pitching[col], pitching_role_b[col], lower) or 0 for _, col, lower in radar_fields]
    st.caption("Percentile rank (0-100) against qualified pitchers (min 20 IP) league-wide.")
    st.plotly_chart(
        style.radar_chart([label for label, _, _ in radar_fields], values_a, values_b,
                          name_a, name_b, color_a, color_b),
        use_container_width=True,
    )

# --- Head-to-head (batter vs pitcher pairs) ---------------------------------
h2h_pairs = []
if is_batter_a and is_pitcher_b:
    h2h_pairs.append((id_a, name_a, id_b, name_b))
if is_batter_b and is_pitcher_a:
    h2h_pairs.append((id_b, name_b, id_a, name_a))
for batter_id, batter_name, pitcher_id, pitcher_name in h2h_pairs:
    h2h = db.load_head_to_head(batter_id, pitcher_id)
    if h2h.get("plateAppearances"):
        style.colored_header(f"Head to Head: {batter_name} vs. {pitcher_name}", "headliners")
        st.caption("Career regular-season matchup, all seasons.")
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("PA", h2h.get("plateAppearances", 0))
        c2.metric("Line", f"{h2h.get('hits', 0)}-for-{h2h.get('atBats', 0)}")
        c3.metric("AVG", h2h.get("avg", "—"))
        c4.metric("OPS", h2h.get("ops", "—"))
        c5.metric("HR", h2h.get("homeRuns", 0))
        c6.metric("K / BB", f"{h2h.get('strikeOuts', 0)} / {h2h.get('baseOnBalls', 0)}")


def _wpa_pair(pid, is_batter):
    """(WPA, WPA+) for a player this season, or (None, None) if ungraded."""
    table = db.load_wpa_batting(season, mtime) if is_batter else db.load_wpa_pitching(season, mtime)
    mine = table[table["mlbID"] == pid] if not table.empty else table
    if mine is None or mine.empty:
        return (None, None)
    r = mine.iloc[0]
    return (round(float(r["wpa"]), 2), round(float(r["wpa_plus"]), 2))


# --- Batting tables ---------------------------------------------------------
if batting_role_a is not None or batting_role_b is not None:
    style.colored_header("Batting", "batting")
    std_tab, adv_tab, sc_tab, disc_tab = st.tabs(["Standard", "Advanced", "Statcast", "Plate Discipline"])

    with std_tab:
        fields = [
            ("G", "G"), ("PA", "PA"), ("AB", "AB"), ("R", "R"), ("H", "H"),
            ("HR", "HR"), ("RBI", "RBI"), ("SB", "SB"),
            ("BA", "BA"), ("OBP", "OBP"), ("SLG", "SLG"), ("OPS", "OPS"),
        ]
        table = build_compare_table(batting_role_a, batting_role_b, fields,
                                    round_map={"BA": 3, "OBP": 3, "SLG": 3, "OPS": 3})
        st.dataframe(style.style_comparison(table, higher_better=["HR", "RBI", "SB", "R", "H", "BA", "OBP", "SLG", "OPS"]),
                     use_container_width=True)

    with adv_tab:
        fields = [
            ("ISO", "ISO"), ("BABIP", "BABIP"), ("K%", "K_PCT"), ("BB%", "BB_PCT"),
            ("wOBA", "wOBA"), ("xwOBA", "xwOBA"), ("WAR", "WAR"), ("OPS+", "OPS_plus"), ("wRC+", "wRC_plus"),
        ]
        table = build_compare_table(batting_role_a, batting_role_b, fields,
                                    round_map={"ISO": 3, "BABIP": 3, "K%": 1, "BB%": 1, "wOBA": 3,
                                               "xwOBA": 3, "WAR": 1, "OPS+": 0, "wRC+": 0})
        wpa_a = _wpa_pair(id_a, True) if batting_role_a is not None else (None, None)
        wpa_b = _wpa_pair(id_b, True) if batting_role_b is not None else (None, None)
        table.loc["WPA"] = [wpa_a[0], wpa_b[0]]
        table.loc["WPA+"] = [wpa_a[1], wpa_b[1]]
        st.dataframe(style.style_comparison(table,
                                            higher_better=["ISO", "BB%", "wOBA", "xwOBA", "WAR", "OPS+", "wRC+",
                                                           "WPA", "WPA+"],
                                            lower_better=["K%"]),
                     use_container_width=True)

    with sc_tab:
        fields = [
            ("Avg EV", "avg_exit_velo"), ("Max EV", "max_exit_velo"),
            ("Hard-Hit%", "hard_hit_pct"), ("Barrel%", "barrel_pct"),
            ("xBA", "xBA"), ("xSLG", "xSLG"), ("xISO", "xISO"), ("xOBP", "xOBP"),
        ]
        table = build_compare_table(batting_role_a, batting_role_b, fields,
                                    round_map={"Avg EV": 1, "Max EV": 1, "Hard-Hit%": 1, "Barrel%": 1,
                                               "xBA": 3, "xSLG": 3, "xISO": 3, "xOBP": 3})
        st.dataframe(style.style_comparison(table,
                                            higher_better=["Avg EV", "Max EV", "Hard-Hit%", "Barrel%",
                                                           "xBA", "xSLG", "xISO", "xOBP"]),
                     use_container_width=True)

    with disc_tab:
        fields = [
            ("Contact%", "contact_pct"), ("Chase%", "chase_pct"), ("Bat Speed", "bat_speed"),
            ("K%", "K_PCT"), ("BB%", "BB_PCT"),
        ]
        table = build_compare_table(batting_role_a, batting_role_b, fields,
                                    round_map={"Contact%": 1, "Chase%": 1, "Bat Speed": 1, "K%": 1, "BB%": 1})
        st.dataframe(style.style_comparison(table,
                                            higher_better=["Contact%", "Bat Speed", "BB%"],
                                            lower_better=["Chase%", "K%"]),
                     use_container_width=True)

# --- Zone heatmaps (both batters) -------------------------------------------
if batting_role_a is not None and batting_role_b is not None:
    style.colored_header("Hot/Cold Zones", "chart")
    st.caption("Average exit velocity by plate location — where each hitter does damage. Blue = weak, red = hard contact.")
    z1, z2 = st.columns(2)
    for col, pid, pname in [(z1, id_a, name_a), (z2, id_b, name_b)]:
        with col:
            st.markdown(f"**{pname}**")
            spray = db.player_batted_ball_events(pid, season)
            if spray.empty:
                st.caption("No batted-ball data this season.")
            else:
                st.plotly_chart(style.batter_zone_heatmap_chart(spray), use_container_width=True,
                                key=f"zone_{pid}")

# --- Pitching tables --------------------------------------------------------
if pitching_role_a is not None or pitching_role_b is not None:
    style.colored_header("Pitching", "pitching")
    std_tab, adv_tab, sc_tab = st.tabs(["Standard", "Advanced", "Statcast"])

    with std_tab:
        fields = [
            ("G", "G"), ("GS", "GS"), ("W", "W"), ("L", "L"), ("SV", "SV"),
            ("IP", "IP"), ("ERA", "ERA"), ("WHIP", "WHIP"), ("SO", "SO"), ("BB", "BB"),
        ]
        table = build_compare_table(pitching_role_a, pitching_role_b, fields, round_map={"ERA": 2, "WHIP": 3})
        st.dataframe(style.style_comparison(table, higher_better=["W", "SV", "SO"],
                                            lower_better=["ERA", "WHIP", "L", "BB"]),
                     use_container_width=True)

    with adv_tab:
        fields = [
            ("FIP", "FIP"), ("xERA", "xERA"), ("K/9", "K_9"), ("BB/9", "BB_9"), ("K/BB", "K_BB"),
            ("WAR", "WAR"), ("ERA+", "ERA_plus"),
        ]
        table = build_compare_table(pitching_role_a, pitching_role_b, fields,
                                    round_map={"FIP": 2, "xERA": 2, "K/9": 2, "BB/9": 2, "K/BB": 2,
                                               "WAR": 1, "ERA+": 0})
        wpa_a = _wpa_pair(id_a, False) if pitching_role_a is not None else (None, None)
        wpa_b = _wpa_pair(id_b, False) if pitching_role_b is not None else (None, None)
        table.loc["WPA"] = [wpa_a[0], wpa_b[0]]
        table.loc["WPA+"] = [wpa_a[1], wpa_b[1]]
        st.dataframe(style.style_comparison(table, higher_better=["K/9", "K/BB", "WAR", "ERA+", "WPA", "WPA+"],
                                            lower_better=["FIP", "xERA", "BB/9"]),
                     use_container_width=True)

    with sc_tab:
        fields = [
            ("Avg EV Against", "avg_exit_velo_against"),
            ("Hard-Hit% Against", "hard_hit_pct_against"),
            ("Barrel% Against", "barrel_pct_against"),
            ("Fastball Velo", "fastball_velo"),
            ("Induced Chase%", "induced_chase_pct"),
        ]
        table = build_compare_table(pitching_role_a, pitching_role_b, fields,
                                    round_map={"Avg EV Against": 1, "Hard-Hit% Against": 1,
                                               "Barrel% Against": 1, "Fastball Velo": 1, "Induced Chase%": 1})
        st.dataframe(style.style_comparison(table,
                                            higher_better=["Fastball Velo", "Induced Chase%"],
                                            lower_better=["Avg EV Against", "Hard-Hit% Against", "Barrel% Against"]),
                     use_container_width=True)

# --- Arsenal duel (both pitchers) -------------------------------------------
if pitching_role_a is not None and pitching_role_b is not None:
    arsenal_a = db.get_player_pitch_arsenal(id_a, season, mtime)
    arsenal_b = db.get_player_pitch_arsenal(id_b, season, mtime)
    if not arsenal_a.empty and not arsenal_b.empty:
        style.colored_header("Arsenal Duel", "chart")
        st.caption(
            "Both arsenals on one movement map — each dot is a pitch, labeled and colored by pitcher, "
            "over the league's cloud (faint). Farther from the pack = movement hitters rarely see."
        )
        league_arsenal = db.load_pitch_arsenal(season, mtime)
        fig = go.Figure()
        if not league_arsenal.empty:
            cloud = league_arsenal.dropna(subset=["vert_break", "horz_break"])
            fig.add_trace(go.Scatter(
                x=cloud["horz_break"], y=cloud["vert_break"], mode="markers",
                marker=dict(size=4, color=style.CHART_DIM, opacity=0.10), hoverinfo="skip", showlegend=False,
            ))
        for arsenal, pname, pcolor in [(arsenal_a, name_a, color_a), (arsenal_b, name_b, color_b)]:
            mv = arsenal.dropna(subset=["vert_break", "horz_break"])
            fig.add_trace(go.Scatter(
                x=mv["horz_break"], y=mv["vert_break"], mode="markers+text", name=pname,
                text=mv["pitch_name"], textposition="top center",
                textfont=dict(size=10, color=pcolor),
                marker=dict(size=13, color=pcolor, line=dict(width=1.5, color=style.CHART_TEXT)),
                hovertext=[
                    f"{pname} — {r['pitch_name']}: {r['usage_pct']:.0f}% usage, "
                    f"{r['velocity']:.1f} mph" if pd.notna(r["velocity"]) else f"{pname} — {r['pitch_name']}"
                    for _, r in mv.iterrows()
                ],
                hoverinfo="text",
            ))
        fig.add_hline(y=0, line_color="rgba(154,163,181,0.4)", line_width=1)
        fig.add_vline(x=0, line_color="rgba(154,163,181,0.4)", line_width=1)
        fig.update_xaxes(title="Horizontal Break (in)", gridcolor="rgba(74,82,102,0.25)", color=style.CHART_DIM)
        fig.update_yaxes(title="Induced Vertical Break (in)", gridcolor="rgba(74,82,102,0.25)", color=style.CHART_DIM)
        fig.update_layout(
            height=500, margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=style.CHART_TEXT,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        )
        st.plotly_chart(fig, use_container_width=True)

        a1, a2 = st.columns(2)
        arsenal_cols = {"pitch_name": "Pitch", "usage_pct": "Usage %", "velocity": "Velo",
                        "whiff_pct": "Whiff %", "woba": "wOBA", "run_value_per_100": "RV/100"}
        for col, arsenal, pname in [(a1, arsenal_a, name_a), (a2, arsenal_b, name_b)]:
            with col:
                st.markdown(f"**{pname}**")
                cols_present = {k: v for k, v in arsenal_cols.items() if k in arsenal.columns}
                disp = arsenal[list(cols_present)].rename(columns=cols_present)
                st.dataframe(
                    style.style_stats_table(
                        disp,
                        higher_better=[c for c in ["Whiff %", "RV/100"] if c in disp.columns],
                        lower_better=[c for c in ["wOBA"] if c in disp.columns],
                        precision={"Usage %": "{:.1f}", "Velo": "{:.1f}", "Whiff %": "{:.1f}",
                                   "wOBA": "{:.3f}", "RV/100": "{:+.1f}"},
                    ),
                    use_container_width=True, hide_index=True,
                )

# --- Career arc overlay -----------------------------------------------------
both_batters = is_batter_a and is_batter_b
both_pitchers = is_pitcher_a and is_pitcher_b
if both_batters or both_pitchers:
    style.colored_header("Career Arc", "headliners")
    arc_stats = db.CAREER_ARC_BATTING_STATS if both_batters else db.CAREER_ARC_PITCHING_STATS
    arc_stat = st.selectbox("Track", arc_stats, key="compare_arc_stat",
                            format_func=lambda s: db.STAT_DISPLAY_LABELS.get(s, s))
    arc_a = db.player_career_arc(id_a, both_batters, arc_stat, mtime)
    arc_b = db.player_career_arc(id_b, both_batters, arc_stat, mtime)
    if len(arc_a) < 2 and len(arc_b) < 2:
        st.caption("Not enough cached seasons for a career overlay yet.")
    else:
        fig = go.Figure()
        for arc, pname, pcolor in [(arc_a, name_a, color_a), (arc_b, name_b, color_b)]:
            if not arc.empty:
                fig.add_trace(go.Scatter(
                    x=arc["season"], y=arc["stat"], mode="lines+markers", name=pname,
                    line=dict(color=pcolor, width=2.5), marker=dict(size=7),
                ))
        fig.update_xaxes(dtick=1, gridcolor="rgba(74,82,102,0.25)", color=style.CHART_DIM)
        fig.update_yaxes(title=db.STAT_DISPLAY_LABELS.get(arc_stat, arc_stat),
                         gridcolor="rgba(74,82,102,0.25)", color=style.CHART_DIM)
        fig.update_layout(
            height=380, margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=style.CHART_TEXT,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        )
        st.plotly_chart(fig, use_container_width=True)

# --- Fielding ---------------------------------------------------------------
if not fielding_a.empty or not fielding_b.empty:
    style.colored_header("Fielding", "fielding")
    # Positions differ? Compare anyway — OAA/FRP are league-relative at each
    # player's own position, so cross-position comparison is fair game. The
    # position label says WHERE each earned their number.
    def _field_summary(fielding):
        if fielding.empty:
            return None
        return {
            "pos": ", ".join(fielding["Pos"].dropna().astype(str).tolist()),
            "OAA": fielding["OAA"].sum(),
            "FRP": fielding["FRP"].sum(),
        }

    sum_a, sum_b = _field_summary(fielding_a), _field_summary(fielding_b)
    st.caption(
        f"{name_a}: {sum_a['pos'] if sum_a else 'no fielding data'} · "
        f"{name_b}: {sum_b['pos'] if sum_b else 'no fielding data'} — OAA/FRP are vs. the average "
        "fielder at each player's own position, so different positions still compare fairly."
    )
    field_table = pd.DataFrame({
        "OAA": [sum_a["OAA"] if sum_a else None, sum_b["OAA"] if sum_b else None],
        "FRP": [sum_a["FRP"] if sum_a else None, sum_b["FRP"] if sum_b else None],
    }, index=[f"{name_a} ({sum_a['pos']})" if sum_a else name_a,
              f"{name_b} ({sum_b['pos']})" if sum_b else name_b]).T
    st.dataframe(style.style_comparison(field_table, higher_better=["OAA", "FRP"]),
                 use_container_width=True)

    # Both catchers → the framing/throwing numbers regular fielding misses.
    if sum_a and sum_b and "C" in (sum_a["pos"] or "") and "C" in (sum_b["pos"] or ""):
        framing = db.load_catcher_framing(season, mtime)
        poptime = db.load_catcher_poptime(season, mtime)
        rows = {}
        for pid, pname in [(id_a, name_a), (id_b, name_b)]:
            fr = framing[framing["mlbID"] == pid] if not framing.empty else framing
            pt = poptime[poptime["mlbID"] == pid] if not poptime.empty else poptime
            rows[pname] = [
                round(fr.iloc[0]["framing_runs"], 1) if fr is not None and not fr.empty else None,
                round(pt.iloc[0]["pop_2b"], 2) if pt is not None and not pt.empty else None,
                round(pt.iloc[0]["arm"], 1) if pt is not None and not pt.empty else None,
            ]
        catcher_table = pd.DataFrame(rows, index=["Framing Runs", "Pop 2B (s)", "Arm (mph)"])
        st.caption("Catcher defense — framing and throwing.")
        st.dataframe(style.style_comparison(catcher_table,
                                            higher_better=["Framing Runs", "Arm (mph)"],
                                            lower_better=["Pop 2B (s)"]),
                     use_container_width=True)

if batting_a is None and batting_b is None and pitching_a is None and pitching_b is None \
        and fielding_a.empty and fielding_b.empty:
    st.info("No stats found for these players in the selected season.")
