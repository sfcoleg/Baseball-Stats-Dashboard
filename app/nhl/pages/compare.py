"""NHL Compare — two players head to head: percentile skill radar (role-
gated: skater vs skater or goalie vs goalie), season stat table, shot-type
mix duel (skaters), and a career-arc line overlay.
Deep-linkable via ?a=<playerId>&b=<playerId>&season=<year>."""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nhl import db as ndb
from nhl import teams as nteams

st.set_page_config(page_title="NHL Compare | Diamond Metrics", layout="wide")
st.title("Compare Players")

mtime = ndb.nhl_db_mtime()
seasons = ndb.skater_seasons(mtime)
if not seasons:
    st.info("No NHL data yet — run ingest/nhl_refresh.py to backfill.")
    st.stop()

qp_season = st.query_params.get("season")
season_index = seasons.index(int(qp_season)) if qp_season and qp_season.isdigit() and int(qp_season) in seasons else 0
season = st.selectbox("Season", seasons, index=season_index, format_func=ndb.season_label)

for param, key in [("a", "a_query"), ("b", "b_query")]:
    qp = st.query_params.get(param)
    if qp and qp.isdigit() and key not in st.session_state:
        pool = pd.concat([
            ndb.load_skaters(season, mtime)[["playerId", "skaterFullName"]].rename(columns={"skaterFullName": "Name"}),
            ndb.load_goalies(season, mtime)[["playerId", "goalieFullName"]].rename(columns={"goalieFullName": "Name"}),
        ], ignore_index=True)
        row = pool[pool["playerId"] == int(qp)]
        if not row.empty:
            st.session_state[key] = row.iloc[0]["Name"]


def pick_player(label, key_prefix):
    query = st.text_input(label, key=f"{key_prefix}_query", placeholder="e.g. McDavid, Hellebuyck")
    if not query.strip():
        return None
    matches = ndb.search_players(query, season, mtime)
    if matches.empty:
        st.warning(f"No players found matching '{query}'.")
        return None
    if len(matches) == 1:
        return matches.iloc[0]
    options = [f"{row.Name} ({nteams._primary(row.Tm)}) — {row.role}" for row in matches.itertuples()]
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
if selected_a["playerId"] == selected_b["playerId"]:
    st.warning("Pick two different players.")
    st.stop()

st.query_params.update({"a": str(int(selected_a["playerId"])), "b": str(int(selected_b["playerId"])), "season": str(season)})
st.divider()

id_a, id_b = int(selected_a["playerId"]), int(selected_b["playerId"])
name_a, name_b = selected_a["Name"], selected_b["Name"]
role_a, role_b = selected_a["role"], selected_b["role"]
color_a = nteams.color_for_abbr(nteams._primary(selected_a["Tm"]))
color_b = nteams.color_for_abbr(nteams._primary(selected_b["Tm"]))

# --- Skill radar (only when both players share a role) ---------------------
if role_a == "Skater" and role_b == "Skater":
    skaters = ndb.load_skaters(season, mtime)
    qualified = skaters[skaters["gamesPlayed"] >= 20]
    row_a = skaters[skaters["playerId"] == id_a].iloc[0]
    row_b = skaters[skaters["playerId"] == id_b].iloc[0]
    style.colored_header("Skater Profile", "batting")
    radar_fields = [
        ("Scoring (P/60)", "pointsPer605v5", False), ("Finishing (xG)", "ixG", False),
        ("Possession (CF%)", "satPercentage", False), ("Physicality (Hits)", "hits", False),
        ("Discipline (Net Pen/60)", "netPenaltiesPer60", False), ("Faceoffs", "faceoffWinPct", False),
    ]
    values_a = [ndb.percentile_rank(qualified[col], row_a[col], lower) or 0 for _, col, lower in radar_fields]
    values_b = [ndb.percentile_rank(qualified[col], row_b[col], lower) or 0 for _, col, lower in radar_fields]
    st.caption(f"Percentile rank (0-100) against skaters with 20+ GP in {ndb.season_label(season)}.")
    st.plotly_chart(
        style.radar_chart([label for label, _, _ in radar_fields], values_a, values_b, name_a, name_b, color_a, color_b),
        use_container_width=True,
    )
elif role_a == "Goalie" and role_b == "Goalie":
    goalies = ndb.load_goalies(season, mtime)
    qualified = goalies[goalies["gamesPlayed"] >= 10]
    row_a = goalies[goalies["playerId"] == id_a].iloc[0]
    row_b = goalies[goalies["playerId"] == id_b].iloc[0]
    style.colored_header("Goalie Profile", "pitching")
    gsax_pool = qualified["xGA"] - qualified["goalsAgainst"]
    gsax_a = row_a["xGA"] - row_a["goalsAgainst"]
    gsax_b = row_b["xGA"] - row_b["goalsAgainst"]
    radar_fields_vals = [
        ("SV%", ndb.percentile_rank(qualified["savePct"], row_a["savePct"]) or 0,
         ndb.percentile_rank(qualified["savePct"], row_b["savePct"]) or 0),
        ("GAA", ndb.percentile_rank(qualified["goalsAgainstAverage"], row_a["goalsAgainstAverage"], True) or 0,
         ndb.percentile_rank(qualified["goalsAgainstAverage"], row_b["goalsAgainstAverage"], True) or 0),
        ("GSAx", ndb.percentile_rank(gsax_pool, gsax_a) or 0, ndb.percentile_rank(gsax_pool, gsax_b) or 0),
        ("Quality Start%", ndb.percentile_rank(qualified["qualityStartsPct"], row_a["qualityStartsPct"]) or 0,
         ndb.percentile_rank(qualified["qualityStartsPct"], row_b["qualityStartsPct"]) or 0),
        ("Workload (GP)", ndb.percentile_rank(qualified["gamesPlayed"], row_a["gamesPlayed"]) or 0,
         ndb.percentile_rank(qualified["gamesPlayed"], row_b["gamesPlayed"]) or 0),
    ]
    st.caption(f"Percentile rank (0-100) against goalies with 10+ GP in {ndb.season_label(season)}.")
    st.plotly_chart(
        style.radar_chart([f[0] for f in radar_fields_vals], [f[1] for f in radar_fields_vals],
                          [f[2] for f in radar_fields_vals], name_a, name_b, color_a, color_b),
        use_container_width=True,
    )
else:
    st.info(f"{name_a} ({role_a}) and {name_b} ({role_b}) don't share stat categories, so no skill radar — "
            "each player's own tables are below instead.")

st.divider()


def build_compare_table(row_a, row_b, fields, round_map=None):
    round_map = round_map or {}
    data = {}
    for label, col in fields:
        val_a, val_b = row_a.get(col), row_b.get(col)
        ndigits = round_map.get(label)
        if ndigits is not None:
            val_a = round(val_a, ndigits) if pd.notna(val_a) else val_a
            val_b = round(val_b, ndigits) if pd.notna(val_b) else val_b
        data[label] = [val_a, val_b]
    return pd.DataFrame(data, index=[name_a, name_b]).T


# --- Season stat tables ------------------------------------------------
if role_a == "Skater" or role_b == "Skater":
    skaters = ndb.load_skaters(season, mtime)
    row_a = skaters[skaters["playerId"] == id_a].iloc[0] if role_a == "Skater" else {}
    row_b = skaters[skaters["playerId"] == id_b].iloc[0] if role_b == "Skater" else {}
    style.colored_header("Skater Stats", "batting")
    fields = [("GP", "gamesPlayed"), ("G", "goals"), ("A", "assists"), ("P", "points"),
              ("+/-", "plusMinus"), ("xG", "ixG"), ("CF%", "satPercentage"), ("Hits", "hits"),
              ("Blocks", "blockedShots")]
    st.dataframe(build_compare_table(row_a, row_b, fields, round_map={"xG": 1, "CF%": 1}),
                 use_container_width=True)

if role_a == "Goalie" or role_b == "Goalie":
    goalies = ndb.load_goalies(season, mtime)
    row_a = goalies[goalies["playerId"] == id_a].iloc[0] if role_a == "Goalie" else {}
    row_b = goalies[goalies["playerId"] == id_b].iloc[0] if role_b == "Goalie" else {}
    style.colored_header("Goalie Stats", "pitching")
    fields = [("GP", "gamesPlayed"), ("W", "wins"), ("L", "losses"), ("OTL", "otLosses"),
              ("GAA", "goalsAgainstAverage"), ("SV%", "savePct"), ("SO", "shutouts"),
              ("Quality Start%", "qualityStartsPct")]
    st.dataframe(build_compare_table(row_a, row_b, fields, round_map={"GAA": 2, "SV%": 1, "Quality Start%": 1}),
                 use_container_width=True)

# --- Shot-type duel (skaters only) --------------------------------------
if role_a == "Skater" and role_b == "Skater":
    skaters = ndb.load_skaters(season, mtime)
    row_a = skaters[skaters["playerId"] == id_a].iloc[0]
    row_b = skaters[skaters["playerId"] == id_b].iloc[0]
    shot_types = [("Wrist", "Wrist"), ("Snap", "Snap"), ("Slap", "Slap"), ("Backhand", "Backhand"),
                  ("TipIn", "Tip"), ("Deflected", "Deflect"), ("WrapAround", "Wrap")]
    cols_a = [f"goals{suffix}" for suffix, _ in shot_types]
    labels = [label for _, label in shot_types]
    if all(c in skaters.columns for c in cols_a):
        style.colored_header("Shot-Type Duel", "chart")
        st.caption("Goals by shot type this season.")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=labels, y=[row_a[c] for c in cols_a], name=name_a, marker_color=color_a))
        fig.add_trace(go.Bar(x=labels, y=[row_b[c] for c in cols_a], name=name_b, marker_color=color_b))
        fig.update_layout(
            barmode="group", height=380, margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            yaxis=dict(gridcolor="rgba(74,82,102,0.25)"),
        )
        st.plotly_chart(fig, use_container_width=True)

# --- Career arc overlay --------------------------------------------------
career_a = ndb.load_goalie_career(id_a, mtime) if role_a == "Goalie" else ndb.load_skater_career(id_a, mtime)
career_b = ndb.load_goalie_career(id_b, mtime) if role_b == "Goalie" else ndb.load_skater_career(id_b, mtime)
if len(career_a) > 1 or len(career_b) > 1:
    style.colored_header("Career Arc", "fielding")
    metric_a = "savePct" if role_a == "Goalie" else "pointsPerGame"
    metric_b = "savePct" if role_b == "Goalie" else "pointsPerGame"
    fig = go.Figure()
    if metric_a in career_a.columns:
        fig.add_trace(go.Scatter(
            x=career_a["season"].map(ndb.season_label), y=career_a[metric_a], mode="lines+markers",
            name=f"{name_a} ({'SV%' if role_a == 'Goalie' else 'PPG'})", line_color=color_a,
        ))
    if metric_b in career_b.columns:
        fig.add_trace(go.Scatter(
            x=career_b["season"].map(ndb.season_label), y=career_b[metric_b], mode="lines+markers",
            name=f"{name_b} ({'SV%' if role_b == 'Goalie' else 'PPG'})", line_color=color_b,
            yaxis="y2" if role_a != role_b else "y",
        ))
    layout = dict(
        height=380, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(gridcolor="rgba(74,82,102,0.25)"), yaxis=dict(gridcolor="rgba(74,82,102,0.25)"),
    )
    if role_a != role_b:
        layout["yaxis2"] = dict(overlaying="y", side="right", gridcolor="rgba(0,0,0,0)")
        st.caption("Different roles plot on separate axes (points/game vs. save %) — shapes over time still compare.")
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True)
