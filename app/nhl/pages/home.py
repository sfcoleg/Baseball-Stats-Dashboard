"""NHL home — landing page for the hockey side. The sport switcher in the
sidebar (see sidebar.render_sport_switcher) lands here; every NHL page
lives under a url_path starting with "nhl" so the active sport can be
derived from the URL alone."""
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from nhl import db as ndb
from nhl import teams as nteams

st.set_page_config(page_title="NHL | Diamond Metrics", layout="wide")
st.title("🏒 NHL")
st.caption(
    "Skater and goalie stats, standings, live scores, head-to-head comparisons, shot maps, and a "
    "trained game-odds model — built on the same free NHL and MoneyPuck data as the rest of the site."
)

mtime = ndb.nhl_db_mtime()
seasons = ndb.skater_seasons(mtime)

st.subheader("Jump to")
links = [
    ("skaters.py", "Skaters"), ("goalies.py", "Goalies"), ("team.py", "Team"),
    ("compare.py", "Compare"), ("today.py", "Today's Games"), ("standings.py", "Standings"),
    ("shots.py", "Shot Maps"),
]
cols = st.columns(len(links))
for col, (filename, label) in zip(cols, links):
    with col:
        st.page_link(f"nhl/pages/{filename}", label=label, use_container_width=True)

if seasons:
    st.divider()
    season = seasons[0]
    skaters = ndb.load_skaters(season, mtime)
    st.subheader(f"{ndb.season_label(season)} Points Leaders")
    top = skaters.sort_values("points", ascending=False).head(8)
    lcols = st.columns(4)
    for i, (_, p) in enumerate(top.iterrows()):
        with lcols[i % 4]:
            tm = nteams._primary(p["teamAbbrevs"])
            st.markdown(
                f"[{p['skaterFullName']}](nhl-player?nhlid={int(p['playerId'])}) "
                f"<span style='color:{nteams.color_for_abbr(tm)};font-weight:700'>{tm}</span> "
                f"— {int(p['points'])} pts",
                unsafe_allow_html=True,
            )
else:
    st.info("No NHL data yet — run `python ingest/nhl_refresh.py` to backfill.")
