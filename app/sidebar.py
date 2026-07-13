"""Persistent player-search box shown in the sidebar on every page (not a
dedicated Search page) — call render_search() near the top of each page,
right after st.set_page_config()."""
import streamlit as st

import db
import style


def render_search():
    st.sidebar.caption("Player Search")
    query = st.sidebar.text_input(
        "Search players", key="sidebar_search_query", placeholder="e.g. Ohtani, Judge",
        label_visibility="collapsed",
    )

    if not db.DB_PATH.exists() or not query.strip():
        return

    season = db.get_seasons("batting")[0]
    mtime = db.db_mtime()
    matches = db.search_players(query, season, mtime)

    if matches.empty:
        st.sidebar.caption("No matches.")
        return

    # Which stat the career-arc sparkline tracks — separate dropdowns for
    # batting/pitching stats since one result list can contain both roles.
    # Only shown once results exist, and only the dropdown(s) relevant to
    # the roles actually present, to avoid cluttering a single-role search.
    roles_present = " / ".join(matches["roles"].unique())
    batting_stat, pitching_stat = "OPS", "ERA"
    if "Batter" in roles_present:
        batting_stat = st.sidebar.selectbox(
            "Track (batters)", db.CAREER_ARC_BATTING_STATS, key="sidebar_batting_arc_stat",
        )
    if "Pitcher" in roles_present:
        pitching_stat = st.sidebar.selectbox(
            "Track (pitchers)", db.CAREER_ARC_PITCHING_STATS, key="sidebar_pitching_arc_stat",
        )

    for _, row in matches.head(8).iterrows():
        label = f"{row['Name']} ({row['Tm']}) — {row['roles']}"
        if st.sidebar.button(label, key=f"sidebar_result_{row['mlbID']}_{row['roles']}", use_container_width=True):
            st.session_state["selected_mlbID"] = int(row["mlbID"])
            st.session_state["selected_name"] = row["Name"]
            st.session_state["selected_season"] = season
            st.switch_page("pages/_Player.py")

        # Career-arc sparkline: tracks whichever stat is selected above —
        # the batting stat for a batter, pitching stat for a pitcher-only
        # result. A two-way player (roles == "Batter / Pitcher") just shows
        # the batting arc, to keep this to one line per result.
        is_batter = "Batter" in row["roles"]
        stat_col = batting_stat if is_batter else pitching_stat
        arc = db.player_career_arc(row["mlbID"], is_batter, stat_col, mtime)
        spark = style.sparkline_svg(arc)
        if spark:
            fmt = db.CAREER_ARC_FORMATS.get(stat_col, "{:.3f}")
            st.sidebar.markdown(
                f"<div style='margin:-10px 0 6px 4px;color:#9AA3B5;font-size:0.75rem'>"
                f"{spark} {stat_col} {fmt.format(arc[0])} → {fmt.format(arc[-1])} ({len(arc)} yr)</div>",
                unsafe_allow_html=True,
            )

    if len(matches) > 8:
        st.sidebar.caption(f"+{len(matches) - 8} more — refine your search to narrow it down.")
