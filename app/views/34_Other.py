"""Other — a hub for the lower-traffic pages (League Trends, Ballparks,
Umpires, Injury Report, Transactions, Awards Race, Minor Leagues, Box
Score Search), which used
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

SECTIONS = [
    ("views/35_Research.py", "Research"),
    ("views/30_League_Trends.py", "League Trends"),
    ("views/33_Ballparks.py", "Ballparks"),
    ("views/23_Umpires.py", "Umpires"),
    ("views/27_Injury_Report.py", "Injury Report"),
    ("views/28_Transactions.py", "Transactions"),
    ("views/29_Awards_Race.py", "Awards Race"),
    ("views/18_Minor_Leagues.py", "Minor Leagues"),
    ("views/22_Box_Score_Search.py", "Box Score Search"),
]
if st.session_state.get("_show_free_agency"):
    SECTIONS.append(("views/21_Free_Agency.py", "Free Agency"))

for path, title in SECTIONS:
    # One per row (not st.columns(), which stacks column-major on mobile —
    # a 2-column grid would read section 1, 3, 5, then 2, 4, 6 on a phone).
    with st.container(border=True):
        st.markdown(f"### {title}")
        st.page_link(path, label=f"Open {title} →", use_container_width=True)
