"""Ballparks — every stadium's personality: our own park factors computed
from six seasons of game results, and a 3D museum of every home run hit
there (ingest/ballparks.py data + the same trajectory renderer the spray
charts use)."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Ballparks | Diamond Metrics", layout="wide")
st.title("Ballparks")
style.glossary_link()
st.caption(
    "Each park's effect on the game, measured from our own data — plus every home run hit there, "
    "in 3D. Factors compare scoring in a team's home games vs. that same team's road games "
    "(100 = neutral), pooled across 2021-2026 so one weird season doesn't define a park."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
hr_log = db.load_hr_log(mtime)
factors = db.park_factors(mtime)

if hr_log.empty:
    st.info("No ballpark data yet — run ingest/ballparks.py to backfill.")
    st.stop()

# Savant's home_team is the park key; AZ -> ARI etc. via the shared fix.
hr_log = hr_log.assign(park_abbr=hr_log["home_team"].map(teams.normalize_mlb_abbr))
if not factors.empty:
    factors = factors.assign(park_abbr=factors["team"].map(teams.normalize_mlb_abbr))

team_options = teams.all_teams()
pick = st.selectbox("Ballpark", [f"{abbr} — {nickname}" for abbr, nickname in team_options])
abbr = pick.split(" — ")[0]
color = teams.color_for_abbr(abbr)
team_id = teams.team_id_for_abbr(abbr)

logo_col, header_col = st.columns([1, 8])
with logo_col:
    if team_id:
        st.markdown(
            f"<img src='{style.team_logo_for_season(abbr, team_id, db.get_seasons('batting')[0])}' "
            f"style='height:70px;width:auto;border-radius:0'>",
            unsafe_allow_html=True,
        )
with header_col:
    st.markdown(
        f"<h2>Home of the <span style='background-color:{color}66;color:#FAFAFA;padding:4px 14px;"
        f"border-radius:10px'>{teams.franchise_display_name(abbr, db.get_seasons('batting')[0])}</span></h2>",
        unsafe_allow_html=True,
    )

# --- This park's factors -----------------------------------------------------
mine = factors[factors["park_abbr"] == abbr] if not factors.empty else pd.DataFrame()
park_hrs = hr_log[hr_log["park_abbr"] == abbr]
if not mine.empty:
    row = mine.iloc[0]
    league_rank_runs = int((factors["run_factor"] > row["run_factor"]).sum()) + 1
    league_rank_hr = int((factors["hr_factor"] > row["hr_factor"]).sum()) + 1
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Run Factor", f"{row['run_factor']:.0f}",
              f"#{league_rank_runs} of {len(factors)}", delta_color="off")
    m2.metric("HR Factor", f"{row['hr_factor']:.0f}",
              f"#{league_rank_hr} of {len(factors)}", delta_color="off")
    m3.metric("Games Measured", int(row["games"]))
    m4.metric("HRs Stored", len(park_hrs))
    if abbr == "ATH":
        st.caption("Athletics numbers blend the Oakland Coliseum and Sutter Health Park eras.")

# --- The 3D HR museum --------------------------------------------------------
style.colored_header("Every Home Run, in 3D", "chart")
seasons_avail = sorted(park_hrs["season"].unique(), reverse=True)
f1, f2 = st.columns([1, 2])
with f1:
    season_pick = st.selectbox("Season", ["All"] + [str(s) for s in seasons_avail], index=1 if seasons_avail else 0)
with f2:
    side_pick = st.radio("Hit by", ["Everyone", "Home team", "Visitors"], horizontal=True)

shown = park_hrs if season_pick == "All" else park_hrs[park_hrs["season"] == int(season_pick)]
# Bottom of the inning = home team batting.
shown = shown.assign(outcome=shown["inning_topbot"].map({"Bot": "Home team", "Top": "Visitors"}))
if side_pick != "Everyone":
    shown = shown[shown["outcome"] == side_pick]

if shown.empty:
    st.caption("No home runs stored for this selection.")
else:
    st.caption(
        f"{len(shown)} home runs — home team in {teams.nickname_for_abbr(abbr)} colors, visitors in gray. "
        "Arcs are drag-free physics approximations between the real launch and landing points, "
        "same as the player spray charts."
    )
    outline = db.team_stadium_outline(abbr)
    field_lines = style.field_wall_lines(outline)
    # With hundreds of arcs, full-opacity lines bury the park outline —
    # fade the arcs somewhat as the count grows, and keep the walls a
    # muted-but-thick line so the shape reads without glowing.
    arc_opacity = min(0.9, max(0.4, 120 / max(len(shown), 1)))
    fig = style.trajectory_3d_chart(
        shown, field_lines, {"Home team": color, "Visitors": "#9AA3B5"},
        arc_width=3, arc_opacity=arc_opacity, wall_color="#8B94A8", wall_width=7,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Longest homers hit here (in the shown selection), with batter names.
    with_dist = shown.dropna(subset=["hit_distance_sc"])
    if not with_dist.empty:
        style.colored_header("Longest Home Runs Here", "headliners")
        top = with_dist.nlargest(10, "hit_distance_sc").copy()
        names = pd.concat([
            db.load_batting(s, mtime)[["mlbID", "Name"]] for s in seasons_avail
        ]).drop_duplicates("mlbID") if seasons_avail else pd.DataFrame(columns=["mlbID", "Name"])
        name_by_id = dict(zip(names["mlbID"], names["Name"]))
        for _, r in top.iterrows():
            batter = name_by_id.get(int(r["batter"]), "")
            desc = r["des"] if isinstance(r["des"], str) else ""
            st.markdown(
                f"<div style='background-color:#1B243866;border-left:4px solid {color};padding:6px 14px;"
                f"border-radius:6px;margin:4px 0'>"
                f"<b>{r['hit_distance_sc']:.0f} ft</b> "
                f"<span style='color:#9AA3B5;font-size:0.85rem'>· {r['game_date'][:10]}"
                + (f" · {batter}" if batter else "") + "</span>"
                f"<div style='color:#DCE1EA;font-size:0.9rem'>{desc}</div></div>",
                unsafe_allow_html=True,
            )

# --- League-wide park factor table -------------------------------------------
if not factors.empty:
    style.colored_header("All 30 Parks", "batting")
    st.caption("Sorted by run factor — the launching pads at the top, the pitcher havens at the bottom.")
    table = factors.sort_values("run_factor", ascending=False)[
        ["park_abbr", "run_factor", "hr_factor", "games"]
    ].rename(columns={"park_abbr": "Tm", "run_factor": "Run Factor",
                      "hr_factor": "HR Factor", "games": "Games"})
    st.dataframe(
        style.style_stats_table(
            table,
            higher_better=["Run Factor", "HR Factor"],
            team_col="Tm", team_color_fn=teams.color_for_abbr,
            precision={"Run Factor": "{:.0f}", "HR Factor": "{:.0f}"},
        ),
        use_container_width=True, height=600, hide_index=True,
    )