"""Other — a hub for the lower-traffic pages (League Trends, Ballparks,
Umpires, Around the League, Minor Leagues, Box Score Search), which used
to each get their own sidebar entry. Consolidated into one link so the
sidebar itself stays short — the pages themselves are untouched, this is
just a single tap away from each instead of six competing for space."""
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import style

st.set_page_config(page_title="Other | Diamond Metrics", layout="wide")
st.title("Other")
st.caption("Everything else the site does — one tap from here instead of its own sidebar slot.")

SECTIONS = [
    ("pages/30_League_Trends.py", "League Trends",
     "How baseball itself has changed over time: scoring environment, velocity, pitch mix, framing — plus a build-your-own chart tool."),
    ("pages/33_Ballparks.py", "Ballparks",
     "Park factors for every stadium, and a 3D museum of every home run hit there."),
    ("pages/23_Umpires.py", "Umpires",
     "Home-plate umpire scorecards — strike zone accuracy by umpire and by game."),
    ("pages/29_Around_the_League.py", "Around the League",
     "Injury report, transactions, and the awards race, all in one place."),
    ("pages/18_Minor_Leagues.py", "Minor Leagues",
     "A lighter version of the site for the minors: org pipelines and call-up tracking."),
    ("pages/22_Box_Score_Search.py", "Box Score Search",
     "Look up any game's full box score by date and team."),
]
if st.session_state.get("_show_free_agency"):
    SECTIONS.append((
        "pages/21_Free_Agency.py", "Free Agency", "Track free agent signings around the league.",
    ))

for path, title, desc in SECTIONS:
    # One per row (not st.columns(), which stacks column-major on mobile —
    # a 2-column grid would read section 1, 3, 5, then 2, 4, 6 on a phone).
    with st.container(border=True):
        st.markdown(f"### {title}")
        st.caption(desc)
        st.page_link(path, label=f"Open {title} →", use_container_width=True)
