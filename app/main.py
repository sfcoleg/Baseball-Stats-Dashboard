"""Real entry point for the app (run via `streamlit run app/main.py`, not
Home.py directly). Uses st.navigation()/st.Page() instead of Streamlit's
classic pages/-folder auto-discovery, specifically so:
  1. The sidebar search box can render ABOVE the page nav. Neither the
     classic system nor st.navigation()'s own auto-rendered menu (position=
     "sidebar") support this — both always claim the very top of the
     sidebar regardless of script call order. The fix is position="hidden"
     (suppresses the automatic menu entirely) plus building the nav links
     ourselves with st.sidebar.page_link(), placed after the search box.
  2. The hidden player-profile page (pages/_Player.py) can be fully
     excluded from the visible menu simply by not creating a page_link for
     it — it's still registered as a valid destination (it's in the list
     passed to st.navigation()), just not listed as a clickable link, so
     st.switch_page() still works. The classic system has no equivalent
     control (an underscore-prefixed filename does NOT hide a page from
     nav there, despite old docs/folklore suggesting it does).
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent))
import following
import sidebar
import style

st.set_page_config(page_title="Diamond Metrics", layout="wide")

# Seeds st.session_state's follow lists from the browser's own localStorage
# (see following.py) — must run before any page can read them.
following.bootstrap()

# Logo + title header — rendered once here (not per-page) so it shows up on
# every page. Streamlit's own toolbar (hamburger menu / Deploy button) is an
# opaque bar pinned to the very top of the viewport; rather than push our
# header below it (leaving it lower than the toolbar's own icons), this
# places the logo/title INSIDE that same top strip via position:fixed, at
# the same height as the Deploy button and the sidebar's Player Search box.
HEADER_HEIGHT = "2.5rem"
st.markdown(
    "<style>"
    "@import url('https://fonts.googleapis.com/css2?family=Russo+One&display=swap');"
    ".diamond-title {"
    "  font-family: 'Russo One', sans-serif !important;"
    "  font-weight: 400 !important;"
    "  font-size: 1.6rem !important;"
    "  line-height: 1.6rem !important;"
    "  letter-spacing: 1px;"
    "  margin: 0 !important;"
    f"  color: {style.DIAMOND_COLOR} !important;"
    "  text-shadow: 1px 1px 0 #1E3A66, 2px 2px 0 #14294D, 4px 4px 8px rgba(0,0,0,0.45);"
    "}"
    ".diamond-header {"
    f"  position: fixed; top: 0; left: 230px; height: {HEADER_HEIGHT}; z-index: 1000000;"
    "  display: flex; align-items: center; gap: 8px; padding-left: 4.5rem;"
    "}"
    f"[data-testid='stHeader'] {{ height: {HEADER_HEIGHT}; }}"
    f"[data-testid='stMainBlockContainer'] {{ padding-top: {HEADER_HEIGHT} !important; }}"
    # Mobile: Streamlit's sidebar becomes an off-canvas overlay below this
    # width rather than a permanent 230px column, so the desktop offset
    # above (left: 230px, padding-left: 4.5rem — pushing the header clear
    # of the sidebar AND its own collapse arrow) leaves nothing but empty
    # space on a phone and shoves the logo/title towards the right edge.
    # Anchor to the left edge instead and shrink both down to fit.
    "@media (max-width: 640px) {"
    "  .diamond-header { left: 0 !important; padding-left: 0.75rem !important; gap: 6px !important; }"
    "  .diamond-logo svg { width: 20px !important; height: 20px !important; }"
    "  .diamond-title { font-size: 1.05rem !important; line-height: 1.05rem !important; }"
    "}"
    "</style>",
    unsafe_allow_html=True,
)
st.markdown(
    f"<div class='diamond-header'><span class='diamond-logo'>{style.diamond_logo(26)}</span>"
    f"<h1 class='diamond-title'>Diamond Metrics</h1></div>",
    unsafe_allow_html=True,
)

# Shrink the sidebar's built-in header bar (which only holds the collapse
# arrow) so the search box sits higher, closer to the top of the sidebar.
# Also narrows the sidebar itself (min/max-width pinned to override its
# default draggable-resize width). No border/divider — the sidebar shares
# the same background color as the rest of the site (see config.toml), so
# there's nothing to visually separate it from the main content anymore.
st.markdown(
    "<style>"
    "[data-testid='stSidebarHeader'] { height: 1.5rem; }"
    "[data-testid='stSidebar'] { min-width: 230px; max-width: 230px; }"
    "</style>",
    unsafe_allow_html=True,
)

# Site-wide mobile pass — everything here was sized for a wide desktop
# layout (Streamlit's own default heading sizes, plus this app's custom
# stat badges/cards), which reads as oversized once a phone shrinks
# everything else around it down to a ~375-430px viewport. Scoped to a
# single breakpoint so desktop is untouched.
st.markdown(
    "<style>"
    "@media (max-width: 640px) {"
    "  [data-testid='stMainBlockContainer'] { padding-left: 1rem !important; padding-right: 1rem !important; }"
    "  h1 { font-size: 1.5rem !important; }"
    "  h2 { font-size: 1.25rem !important; }"
    "  h3 { font-size: 1.05rem !important; }"
    "  [data-testid='stMetricValue'] { font-size: 1.3rem !important; }"
    "  [data-testid='stMetricLabel'] { font-size: 0.8rem !important; }"
    "}"
    "</style>",
    unsafe_allow_html=True,
)

sidebar.render_search()

PAGES = [
    st.Page("Home.py", title="Home", default=True),
    st.Page("pages/12_Daily_Digest.py", title="Daily Digest"),
    st.Page("pages/13_Following.py", title="Following"),
    st.Page("pages/1_Batting.py", title="Batting"),
    st.Page("pages/2_Pitching.py", title="Pitching"),
    st.Page("pages/3_Fielding.py", title="Fielding"),
    st.Page("pages/6_Baserunning.py", title="Baserunning"),
    st.Page("pages/4_Team.py", title="Team"),
    st.Page("pages/5_Compare.py", title="Compare"),
    st.Page("pages/8_Todays_Games.py", title="Today's Games"),
    st.Page("pages/9_Standings.py", title="Standings"),
    st.Page("pages/10_Injury_Report.py", title="Injury Report"),
    st.Page("pages/11_Transactions.py", title="Transactions"),
    st.Page("pages/14_Milestone_Watch.py", title="Milestone Watch"),
    st.Page("pages/15_Mini_Games.py", title="Mini Games"),
    st.Page("pages/16_World_Map.py", title="World Map"),
    st.Page("pages/_Player.py", title="Player"),  # deliberately no page_link below -> not shown in nav
]

pg = st.navigation(PAGES, position="hidden")

for p in PAGES:
    if p.title != "Player":
        st.sidebar.page_link(p, label=p.title)

pg.run()
