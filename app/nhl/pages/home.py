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

if seasons:
    season = seasons[0]
    skaters = ndb.load_skaters(season, mtime)
    st.subheader(f"{ndb.season_label(season)} Points Leaders")
    top = skaters.sort_values("points", ascending=False).head(10)
    lcols = st.columns(5)
    for i, (_, p) in enumerate(top.iterrows()):
        with lcols[i % 5]:
            tm = nteams._primary(p["teamAbbrevs"])
            color = nteams.color_for_abbr(tm)
            headshot = f"https://assets.nhle.com/mugs/nhl/{season}{season + 1}/{tm}/{int(p['playerId'])}.png"
            st.markdown(
                f"<div style='position:relative;text-align:center;background:linear-gradient(180deg,{color}26,transparent);"
                f"border:1px solid {color}55;border-radius:12px;padding:14px 8px 10px;margin-bottom:14px'>"
                f"<div style='position:absolute;top:6px;left:8px;background:{color};color:#0E1117;"
                f"font-weight:800;font-size:0.75rem;width:20px;height:20px;border-radius:50%;"
                f"display:flex;align-items:center;justify-content:center'>{i + 1}</div>"
                f"<img src='{headshot}' style='width:72px;height:72px;border-radius:50%;object-fit:cover;"
                f"object-position:center 15%;border:2px solid {color};background:#1A1F2E' />"
                f"<div style='margin-top:8px;font-weight:700;font-size:0.92rem;line-height:1.2'>"
                f"<a href='nhl-player?nhlid={int(p['playerId'])}' target='_self' "
                f"style='color:#FAFAFA;text-decoration:none'>{p['skaterFullName']}</a></div>"
                f"<span style='display:inline-block;margin-top:4px;background-color:{color}66;color:#FAFAFA;"
                f"padding:1px 8px;border-radius:6px;font-size:0.75rem;font-weight:700'>{tm}</span>"
                f"<div style='margin-top:6px;font-size:1.4rem;font-weight:800;color:{color}'>{int(p['points'])}"
                f"<span style='font-size:0.7rem;font-weight:600;color:#9AA3B5'> PTS</span></div>"
                "</div>",
                unsafe_allow_html=True,
            )
else:
    st.info("No NHL data yet — run `python ingest/nhl_refresh.py` to backfill.")
