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

st.set_page_config(page_title="Sabermetrics Dashboard", layout="wide")

# Seeds st.session_state's follow lists from the browser's own localStorage
# (see following.py) — must run before any page can read them.
following.bootstrap()

# Shrink the sidebar's built-in header bar (which only holds the collapse
# arrow) so the search box sits higher, closer to the top of the sidebar.
st.markdown(
    "<style>[data-testid='stSidebarHeader'] { height: 1.5rem; }</style>",
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
    st.Page("pages/_Player.py", title="Player"),  # deliberately no page_link below -> not shown in nav
    st.Page("pages/_Article.py", title="Article"),  # same deal — reached via Daily Digest's "Read more" buttons
]

pg = st.navigation(PAGES, position="hidden")

for p in PAGES:
    if p.title not in ("Player", "Article"):
        st.sidebar.page_link(p, label=p.title)

pg.run()
