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

    for _, row in matches.head(8).iterrows():
        label = f"{row['Name']} ({row['Tm']}) — {row['roles']}"
        if st.sidebar.button(label, key=f"sidebar_result_{row['mlbID']}_{row['roles']}", use_container_width=True):
            st.session_state["selected_mlbID"] = int(row["mlbID"])
            st.session_state["selected_name"] = row["Name"]
            st.session_state["selected_season"] = season
            st.switch_page("pages/_Player.py")

        # Career-arc sparkline: OPS trend for batters, ERA trend for a
        # pitcher-only result — a two-way player (roles == "Batter / Pitcher")
        # just shows the batting arc, to keep this to one line per result.
        is_batter = "Batter" in row["roles"]
        arc = db.player_career_arc(row["mlbID"], is_batter, mtime)
        spark = style.sparkline_svg(arc)
        if spark:
            stat_label = "OPS" if is_batter else "ERA"
            fmt = "{:.3f}" if is_batter else "{:.2f}"
            st.sidebar.markdown(
                f"<div style='margin:-10px 0 6px 4px;color:#9AA3B5;font-size:0.75rem'>"
                f"{spark} {stat_label} {fmt.format(arc[0])} → {fmt.format(arc[-1])} ({len(arc)} yr)</div>",
                unsafe_allow_html=True,
            )

    if len(matches) > 8:
        st.sidebar.caption(f"+{len(matches) - 8} more — refine your search to narrow it down.")
