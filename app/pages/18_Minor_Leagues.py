import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Minor Leagues | Diamond Metrics", layout="wide")
st.title("Minor Leagues")
st.caption(
    "A lighter version of the main site for the minors — real per-player stats from the MLB "
    "Stats API, fetched live rather than backfilled across seasons like the MLB pages. Levels: "
    "Triple-A, Double-A, High-A, Single-A, Rookie."
)

CURRENT_SEASON = db.today_pacific().year
SEASONS = list(range(CURRENT_SEASON, CURRENT_SEASON - 3, -1))
LEVELS = list(db.MILB_LEVELS.keys())

BAT_COLS = [
    "Name", "Org", "Tm", "League", "Age", "G", "PA", "AB", "R", "H", "2B", "3B",
    "HR", "RBI", "BB", "SO", "SB", "AVG", "OBP", "SLG", "OPS",
]
PIT_COLS = ["Name", "Org", "Tm", "League", "Age", "G", "GS", "W", "L", "SV", "IP", "ERA", "WHIP", "SO", "BB", "HR"]


def _with_org(df: pd.DataFrame, season: int) -> pd.DataFrame:
    """Adds the parent-organization abbreviation column via the cached
    affiliation map; teams without a mapping (complex-league entries,
    co-ops) just show a dash."""
    df = df.copy()
    orgs = db.load_milb_parent_orgs(season)
    df["Org"] = df["team_id"].map(orgs).fillna("—")
    return df


bat_tab, pit_tab, org_tab, callup_tab = st.tabs(["Batting", "Pitching", "Org Pipeline", "Call-Ups"])

with bat_tab:
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        level = st.selectbox("Level", LEVELS, key="milb_bat_level")
    with c2:
        season = st.selectbox("Season", SEASONS, key="milb_bat_season")
    with c3:
        min_pa = st.number_input("Min PA", min_value=0, value=50, step=10, key="milb_bat_min_pa")

    with st.spinner("Loading..."):
        bat_df = db.load_milb_stats(db.MILB_LEVELS[level], "hitting", season)
    if bat_df.empty:
        st.info("No data available for this level/season yet.")
    else:
        bat_df = _with_org(bat_df, season)
        bat_df = bat_df[bat_df["PA"].fillna(0) >= min_pa].sort_values("OPS", ascending=False)
        st.caption(f"{len(bat_df)} players")
        st.dataframe(
            style.style_stats_table(
                bat_df[BAT_COLS],
                higher_better=["HR", "RBI", "SB", "AVG", "OBP", "SLG", "OPS"],
            ),
            use_container_width=True, hide_index=True, height=600,
        )

with pit_tab:
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        level = st.selectbox("Level", LEVELS, key="milb_pit_level")
    with c2:
        season = st.selectbox("Season", SEASONS, key="milb_pit_season")
    with c3:
        min_ip = st.number_input("Min IP", min_value=0, value=10, step=5, key="milb_pit_min_ip")

    with st.spinner("Loading..."):
        pit_df = db.load_milb_stats(db.MILB_LEVELS[level], "pitching", season)
    if pit_df.empty:
        st.info("No data available for this level/season yet.")
    else:
        pit_df = _with_org(pit_df, season)
        pit_df = pit_df[pit_df["IP"].fillna(0) >= min_ip].sort_values("ERA", ascending=True)
        st.caption(f"{len(pit_df)} players")
        st.dataframe(
            style.style_stats_table(
                pit_df[PIT_COLS],
                higher_better=["W", "SV", "SO"],
                lower_better=["ERA", "WHIP", "L", "BB"],
            ),
            use_container_width=True, hide_index=True, height=600,
        )

with org_tab:
    st.caption(
        "One organization's entire farm system across every level — the pipeline view. "
        "First load fetches all five levels, so give it a few seconds."
    )
    oc1, oc2 = st.columns([2, 1])
    with oc1:
        org_options = teams.all_teams()
        org_label = st.selectbox(
            "Organization", [f"{abbr} — {nickname}" for abbr, nickname in org_options],
            key="milb_org_pick",
        )
        org_abbr = org_label.split(" — ")[0]
    with oc2:
        org_season = st.selectbox("Season", SEASONS, key="milb_org_season")

    with st.spinner("Loading all levels..."):
        bat_frames, pit_frames = [], []
        for level_name, sport_id in db.MILB_LEVELS.items():
            b = db.load_milb_stats(sport_id, "hitting", org_season)
            if not b.empty:
                bat_frames.append(b.assign(Level=level_name))
            p = db.load_milb_stats(sport_id, "pitching", org_season)
            if not p.empty:
                pit_frames.append(p.assign(Level=level_name))

    org_bat = _with_org(pd.concat(bat_frames, ignore_index=True), org_season) if bat_frames else pd.DataFrame()
    org_pit = _with_org(pd.concat(pit_frames, ignore_index=True), org_season) if pit_frames else pd.DataFrame()
    org_bat = org_bat[org_bat["Org"] == org_abbr] if not org_bat.empty else org_bat
    org_pit = org_pit[org_pit["Org"] == org_abbr] if not org_pit.empty else org_pit

    if org_bat.empty and org_pit.empty:
        st.info("No affiliated players found for this organization/season.")
    else:
        # Modest floors so the tables show real farmhands, not every
        # 3-PA September cameo — looser than the level tabs' defaults
        # since a whole system splits playing time five ways.
        level_order = {name: i for i, name in enumerate(db.MILB_LEVELS)}
        if not org_bat.empty:
            style.colored_header("Hitters", "batting")
            show = org_bat[org_bat["PA"].fillna(0) >= 30].copy()
            show["_lvl"] = show["Level"].map(level_order)
            show = show.sort_values(["_lvl", "OPS"], ascending=[True, False])
            st.caption(f"{len(show)} hitters with 30+ PA, Triple-A first.")
            st.dataframe(
                style.style_stats_table(
                    show[["Name", "Level", "Tm", "Age", "G", "PA", "HR", "RBI", "SB", "AVG", "OBP", "SLG", "OPS"]],
                    higher_better=["HR", "RBI", "SB", "AVG", "OBP", "SLG", "OPS"],
                ),
                use_container_width=True, hide_index=True, height=500,
            )
        if not org_pit.empty:
            style.colored_header("Pitchers", "pitching")
            show = org_pit[org_pit["IP"].fillna(0) >= 10].copy()
            show["_lvl"] = show["Level"].map(level_order)
            show = show.sort_values(["_lvl", "ERA"], ascending=[True, True])
            st.caption(f"{len(show)} pitchers with 10+ IP, Triple-A first.")
            st.dataframe(
                style.style_stats_table(
                    show[["Name", "Level", "Tm", "Age", "G", "GS", "W", "L", "SV", "IP", "ERA", "WHIP", "SO"]],
                    higher_better=["W", "SV", "SO"],
                    lower_better=["ERA", "WHIP", "L"],
                ),
                use_container_width=True, hide_index=True, height=500,
            )

with callup_tab:
    st.caption(
        "The roster shuttle — every call-up, contract selection, and option to the minors, "
        "straight from the MLB transactions feed."
    )
    window_options = {"Last 7 days": 7, "Last 14 days": 14, "Last 30 days": 30}
    window_label = st.selectbox("Window", list(window_options.keys()), index=1, key="callup_window")

    with st.spinner("Loading moves..."):
        txs = db.load_transactions(window_options[window_label])

    _CALLUP_TYPES = {
        "Recalled": ("⬆️", "#7CFC9A"),
        "Selected": ("⬆️", "#7CFC9A"),   # contract selected from the minors
        "Optioned": ("⬇️", "#FF8A80"),
    }
    moves = txs[txs["type"].isin(_CALLUP_TYPES)] if not txs.empty else txs
    if moves is None or moves.empty:
        st.info("No call-ups or send-downs in this window.")
    else:
        ups = int(moves["type"].isin(["Recalled", "Selected"]).sum())
        downs = int((moves["type"] == "Optioned").sum())
        st.caption(f"{ups} up ⬆️ · {downs} down ⬇️")
        for _, row in moves.iterrows():
            arrow, accent = _CALLUP_TYPES[row["type"]]
            team_bit = ""
            abbr = row["to_abbr"] or row["from_abbr"]
            if isinstance(abbr, str):
                color = teams.color_for_abbr(abbr)
                team_bit = (
                    f"<span style='background-color:{color}66;color:#FAFAFA;padding:2px 8px;"
                    f"border-radius:6px;font-weight:700;font-size:0.8rem;margin-right:6px'>{abbr}</span>"
                )
            st.markdown(
                f"<div style='background-color:#1B243866;border-left:4px solid {accent};padding:8px 14px;"
                f"border-radius:6px;margin:5px 0'>"
                f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:2px'>"
                f"<div>{arrow} {team_bit}<span style='color:#9AA3B5;font-size:0.85rem'>{row['type']}</span></div>"
                f"<span style='color:#9AA3B5;font-size:0.85rem'>{row['date']}</span>"
                f"</div>"
                f"<div style='color:#DCE1EA'>{row['description']}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
