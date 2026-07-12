import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Player | Sabermetrics Dashboard", layout="wide")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

if "selected_mlbID" not in st.session_state:
    st.title("Player Profile")
    st.info("Use the search box in the sidebar to find a player.")
    st.stop()

mlbID = st.session_state["selected_mlbID"]
mtime = db.db_mtime()
season = st.session_state.get("selected_season") or db.get_seasons("batting")[0]

batting = db.get_player_batting(mlbID, season, mtime)
pitching = db.get_player_pitching(mlbID, season, mtime)
fielding = db.get_player_fielding(mlbID, season, mtime)

if batting is None and pitching is None and fielding.empty:
    st.title("Player Profile")
    st.info("No stats found for this player in the selected season.")
    st.stop()

selected_name = st.session_state.get("selected_name", "")
selected_roles = " / ".join(
    role for role, present in [("Batter", batting is not None), ("Pitcher", pitching is not None)] if present
)

all_batting = db.load_batting(season, mtime)
all_pitching = db.load_pitching(season, mtime)
qualified_batting = all_batting[all_batting["PA"] >= 50]
qualified_pitching = all_pitching[all_pitching["IP"] >= 20]

st.divider()

team_row = batting if batting is not None else pitching
if team_row is not None:
    abbr, nickname, color = teams.team_meta_from_city(team_row["Tm"], team_row.get("Lev"))
    age = team_row["Age"]
elif not fielding.empty:
    abbr, color = teams.team_meta_from_nickname(fielding.iloc[0]["Tm"])
    nickname = fielding.iloc[0]["Tm"]
    age = "—"
else:
    abbr, nickname, color = "—", "Unknown", "#666666"
    age = "—"

photo_col, header_col = st.columns([1, 6])
with photo_col:
    st.image(style.headshot_url(mlbID, width=180), width=120)
with header_col:
    st.markdown(
        f"# {selected_name} "
        f"<span style='background-color:{color}66;color:#FAFAFA;padding:4px 12px;"
        f"border-radius:10px;font-size:0.5em;vertical-align:middle;font-weight:600'>{abbr}</span>",
        unsafe_allow_html=True,
    )
    st.caption(f"{nickname} · Age {age} · {selected_roles}")

history = db.load_player_history(mlbID, season, mtime)
streak_badges = []
if batting is not None:
    hit_streak = db.current_hit_streak(history[history["role"] == "Batter"])
    if hit_streak is not None and hit_streak >= 2:
        streak_badges.append(f"{hit_streak}-Game Hit Streak")
if pitching is not None:
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

if batting is not None:
    style.colored_header("Batting", "batting")
    metrics = [
        ("AVG", f"{batting['BA']:.3f}", db.percentile_rank(qualified_batting["BA"], batting["BA"])),
        ("OBP", f"{batting['OBP']:.3f}", db.percentile_rank(qualified_batting["OBP"], batting["OBP"])),
        ("SLG", f"{batting['SLG']:.3f}", db.percentile_rank(qualified_batting["SLG"], batting["SLG"])),
        ("OPS", f"{batting['OPS']:.3f}", db.percentile_rank(qualified_batting["OPS"], batting["OPS"])),
        ("HR", int(batting["HR"]), db.percentile_rank(qualified_batting["HR"], batting["HR"])),
        ("RBI", int(batting["RBI"]), db.percentile_rank(qualified_batting["RBI"], batting["RBI"])),
    ]
    cols = st.columns(6)
    for col, (label, value, pct) in zip(cols, metrics):
        col.metric(label, value, f"{pct}th pctile" if pct is not None else None, delta_color="off")

    style.colored_header("Baserunning", "batting")
    sb, cs = batting.get("SB"), batting.get("CS")
    attempts = (sb or 0) + (cs or 0)
    sb_pct_val = (sb / attempts * 100) if attempts and pd.notna(sb) and pd.notna(cs) else None
    qualified_attempts = qualified_batting["SB"] + qualified_batting["CS"]
    qualified_sb_pct = (qualified_batting["SB"] / qualified_attempts.replace(0, pd.NA) * 100)
    br_metrics = [
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

    std_tab, adv_tab, sc_tab = st.tabs(["Standard", "Advanced (Sabermetrics)", "Statcast"])
    with std_tab:
        st.dataframe(
            batting[["G", "PA", "AB", "R", "H", "2B", "3B", "HR", "RBI", "BB", "SO", "SB", "CS"]]
            .to_frame().T,
            use_container_width=True,
            hide_index=True,
        )
    with adv_tab:
        st.dataframe(
            batting[["ISO", "BABIP", "K_PCT", "BB_PCT", "wOBA", "xwOBA"]]
            .rename({"K_PCT": "K%", "BB_PCT": "BB%"})
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

if pitching is not None:
    style.colored_header("Pitching", "pitching")
    metrics = [
        ("ERA", f"{pitching['ERA']:.2f}", db.percentile_rank(qualified_pitching["ERA"], pitching["ERA"], lower_is_better=True)),
        ("WHIP", f"{pitching['WHIP']:.3f}", db.percentile_rank(qualified_pitching["WHIP"], pitching["WHIP"], lower_is_better=True)),
        ("W-L", f"{int(pitching['W'])}-{int(pitching['L'])}", None),
        ("SV", int(pitching["SV"]), db.percentile_rank(qualified_pitching["SV"], pitching["SV"])),
        ("IP", pitching["IP"], None),
        ("SO", int(pitching["SO"]), db.percentile_rank(qualified_pitching["SO"], pitching["SO"])),
    ]
    cols = st.columns(6)
    for col, (label, value, pct) in zip(cols, metrics):
        col.metric(label, value, f"{pct}th pctile" if pct is not None else None, delta_color="off")

    std_tab, adv_tab, sc_tab = st.tabs(["Standard", "Advanced (Sabermetrics)", "Statcast"])
    with std_tab:
        st.dataframe(
            pitching[["G", "GS", "W", "L", "SV", "IP", "ERA", "WHIP", "SO", "BB", "HR"]]
            .to_frame().T,
            use_container_width=True,
            hide_index=True,
        )
    with adv_tab:
        st.dataframe(
            pitching[["FIP", "K_9", "BB_9", "K_BB"]]
            .rename({"K_9": "K/9", "BB_9": "BB/9", "K_BB": "K/BB"})
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

if not fielding.empty:
    style.colored_header("Fielding", "fielding")
    st.caption("Outs Above Average (OAA) by position — Statcast.")
    st.dataframe(
        fielding[["Pos", "OAA", "FRP", "success_rate"]].rename(columns={"success_rate": "Success Rate"}),
        use_container_width=True,
        hide_index=True,
    )

if batting is not None or pitching is not None:
    style.colored_header("Season Trend", "headliners")
    stat_col, stat_label, role_filter = ("OPS", "OPS", "Batter") if batting is not None else ("ERA", "ERA", "Pitcher")
    trend = history[(history["role"] == role_filter) & history[stat_col].notna()]
    if len(trend) >= 2:
        fig = px.line(trend, x="date", y=stat_col, markers=True, labels={"date": "Date", stat_col: stat_label})
        fig.update_traces(line_color="#E3572A", marker_color="#E3572A")
        fig.update_layout(
            height=320, margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="#FAFAFA",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Trend builds up day by day from the daily refresh — check back after a few more days of data.")

if batting is not None or pitching is not None:
    style.colored_header("League Distribution", "chart")
    if batting is not None:
        dist_df = qualified_batting.dropna(subset=["OPS"])
        fig = px.histogram(dist_df, x="OPS", nbins=40, labels={"OPS": "OPS (min 50 PA)"})
        fig.add_vline(x=batting["OPS"], line_color="#E3572A", line_width=3)
        fig.update_layout(
            height=320, margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="#FAFAFA", showlegend=False,
        )
        st.caption(f"Orange line = {selected_name}'s OPS against all qualified batters.")
        st.plotly_chart(fig, use_container_width=True)
    if pitching is not None:
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
