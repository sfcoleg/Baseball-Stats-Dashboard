"""Sidebar header: the sport switcher (⚾ MLB | 🏒 NHL) and the persistent
player-search box, rendered once per run from main.py above the page nav."""
import streamlit as st

import db

SPORT_LABELS = {"mlb": "⚾ MLB", "nhl": "🏒 NHL"}
_LABEL_TO_SPORT = {v: k for k, v in SPORT_LABELS.items()}


def render_sport_switcher(active_sport: str, home_pages: dict) -> None:
    """Compact segmented toggle at the top of the sidebar. The URL decides
    which sport is active (main.py derives it from the current page's
    url_path); this widget only ever *changes* sport when the user clicks
    it — on every other run it's re-synced to the URL so deep links and
    normal navigation never get bounced by a stale widget value.

    `home_pages` maps sport -> the st.Page to switch to."""
    clicked = st.session_state.get("sport_switch")
    prev = st.session_state.get("_sport_switch_rendered")
    if clicked is not None and prev is not None and clicked != prev:
        target = _LABEL_TO_SPORT.get(clicked)
        if target and target != active_sport and target in home_pages:
            st.session_state["_sport_switch_rendered"] = clicked
            st.switch_page(home_pages[target])

    # Sync to the URL-derived sport before rendering (allowed: we set the
    # key before the widget is created this run).
    st.session_state["sport_switch"] = SPORT_LABELS[active_sport]
    st.sidebar.markdown(
        "<style>"
        "[data-testid='stSidebar'] [data-testid='stSegmentedControl'] button {"
        "  font-size: 0.8rem !important; padding: 2px 10px !important; min-height: 0 !important;"
        "}"
        # Below ~640px (phones) every sidebar tap target above is sized for
        # a mouse cursor, not a thumb — the collapse/expand arrow is 28x28,
        # nav links and the sport switcher are ~28px tall, all well under
        # the ~44px minimum touch target every mobile HIG recommends. This
        # widens just those three on narrow screens without touching the
        # deliberately compact desktop sizing above.
        "@media (max-width: 640px) {"
        "  [data-testid='stExpandSidebarButton'], [data-testid='stSidebarCollapseButton'] button {"
        "    padding: 12px !important;"
        "  }"
        "  [data-testid='stExpandSidebarButton'] svg, [data-testid='stSidebarCollapseButton'] svg {"
        "    width: 22px !important; height: 22px !important;"
        "  }"
        "  [data-testid='stSidebar'] [data-testid='stSegmentedControl'] button {"
        "    padding: 10px 16px !important; min-height: 44px !important; font-size: 0.95rem !important;"
        "  }"
        "  [data-testid='stSidebar'] a[data-testid='stPageLink-NavLink'] {"
        "    min-height: 44px !important; padding-top: 10px !important; padding-bottom: 10px !important;"
        "    display: flex !important; align-items: center !important;"
        "  }"
        "}"
        "</style>",
        unsafe_allow_html=True,
    )
    st.sidebar.segmented_control(
        "Sport", list(SPORT_LABELS.values()), key="sport_switch",
        label_visibility="collapsed",
    )
    st.session_state["_sport_switch_rendered"] = SPORT_LABELS[active_sport]


def render_search(active_sport: str = "mlb") -> None:
    if active_sport != "mlb":
        st.sidebar.text_input(
            "Search players", key="sidebar_search_query_nhl", placeholder="NHL search coming soon",
            label_visibility="collapsed", disabled=True,
        )
        return

    query = st.sidebar.text_input(
        "Search players", key="sidebar_search_query", placeholder="e.g. Ohtani, Judge",
        label_visibility="collapsed",
    )

    if not db.DB_PATH.exists() or not query.strip():
        return

    mtime = db.db_mtime()
    matches = db.search_players_all_seasons(query, mtime)

    if matches.empty:
        st.sidebar.caption("No matches.")
        return

    for _, row in matches.head(8).iterrows():
        label = f"{row['Name']} ({row['Tm']}) — {row['roles']}"
        if st.sidebar.button(label, key=f"sidebar_result_{row['mlbID']}_{row['roles']}", use_container_width=True):
            st.session_state["selected_mlbID"] = int(row["mlbID"])
            st.session_state["selected_name"] = row["Name"]
            st.session_state["selected_season"] = int(row["season"])
            st.switch_page("pages/_Player.py")

    if len(matches) > 8:
        st.sidebar.caption(f"+{len(matches) - 8} more — refine your search to narrow it down.")
