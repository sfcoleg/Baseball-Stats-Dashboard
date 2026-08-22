"""NHL home — Phase 0 placeholder while the hockey side gets built. The
sport switcher in the sidebar (see sidebar.render_sport_switcher) lands
here; every NHL page lives under a url_path starting with "nhl" so the
active sport can be derived from the URL alone."""
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

st.set_page_config(page_title="NHL | Diamond Metrics", layout="wide")
st.title("🏒 NHL")
st.info(
    "Hockey is on the way. Standings, scores, skater and goalie stats, team pages, and a "
    "trained game-odds model are being built on the same foundation as the MLB side — "
    "flip the switcher back to ⚾ MLB anytime."
)
