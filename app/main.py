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
# every page, and pinned via position:sticky so it stays visible at the top
# of the viewport while scrolling a long page. Background color matches the
# theme's backgroundColor (config.toml) so scrolled-under content doesn't
# show through.
st.markdown(
    "<style>"
    "@import url('https://fonts.googleapis.com/css2?family=Bungee&display=swap');"
    ".diamond-title {"
    "  font-family: 'Bungee', cursive;"
    "  font-size: 2rem;"
    "  letter-spacing: 1px;"
    "  margin: 0;"
    f"  color: {style.DIAMOND_COLOR};"
    "  text-shadow: 2px 2px 0 #1E3A66, 4px 4px 0 #14294D, 6px 6px 10px rgba(0,0,0,0.45);"
    "}"
    ".diamond-header {"
    "  position: sticky; top: 0; z-index: 999; background-color: #33405F;"
    "  display: flex; align-items: center; gap: 10px; padding: 0.25rem 0 0.5rem;"
    "}"
    # Streamlit's own toolbar (hamburger menu / Deploy button) is an opaque,
    # absolutely-positioned bar that the page's block-container pads itself
    # below — both default to a taller height than the toolbar's icons
    # actually need. Shrinking both to match pulls the logo/title up to sit
    # right at the top of the page instead of leaving dead space above it.
    "[data-testid='stHeader'] { height: 2.5rem; }"
    "[data-testid='stMainBlockContainer'] { padding-top: 2.5rem !important; }"
    "</style>",
    unsafe_allow_html=True,
)
st.markdown(
    f"<div class='diamond-header'>{style.diamond_logo(36)}"
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
    st.Page("pages/_Player.py", title="Player"),  # deliberately no page_link below -> not shown in nav
]

pg = st.navigation(PAGES, position="hidden")

for p in PAGES:
    if p.title != "Player":
        st.sidebar.page_link(p, label=p.title)

pg.run()
