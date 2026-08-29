"""NFL Defense — coverage and pass rush.

The whole defensive side of the ball was missing from the site, because the
standard box score barely measures it. Pro-Football-Reference's advanced
tables are the exception: they record who was thrown at, what happened when
they were, and who got pressure on the quarterback."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import db as fdb
from nfl import teams as fteams

st.set_page_config(page_title="NFL Defense | Diamond Metrics", layout="wide")
st.title("Defense")

mtime = fdb.nfl_db_mtime()
season_list = fdb.seasons(mtime)
if not season_list:
    st.info("No NFL data yet — run `python ingest/nfl_refresh.py` to build it.")
    st.stop()

season = st.selectbox("Season", season_list, index=fdb.season_index(season_list, mtime),
                      format_func=fdb.season_label)

if not fdb.advanced_available(season, "pfr"):
    st.caption(
        f"Advanced defensive stats begin in {fdb.PFR_FIRST_SEASON} — earlier seasons "
        "have no per-player coverage or pass-rush data."
    )
    st.stop()

defense = fdb.load_pfr_advanced(season, "def", mtime)
if defense.empty:
    st.caption(f"No defensive data for {fdb.season_label(season)} yet.")
    st.stop()

defense = defense.rename(columns={"player": "Player", "tm": "Tm", "pos": "Pos"})
positions = sorted(defense["Pos"].dropna().unique().tolist())
picked = st.multiselect("Positions", positions, default=[], placeholder="All positions")
pool = defense[defense["Pos"].isin(picked)] if picked else defense


def _board(frame, sort_col, columns, precision, note, ascending, minimum=None):
    if sort_col not in frame.columns:
        st.caption("No data for this season.")
        return
    rows = frame
    if minimum:
        col, floor = minimum
        if col in rows.columns:
            rows = rows[pd.to_numeric(rows[col], errors="coerce").fillna(0) >= floor]
    rows = rows.dropna(subset=[sort_col])
    if rows.empty:
        st.caption("No qualifying players for this season.")
        return
    top = rows.sort_values(sort_col, ascending=ascending).head(25)
    display = pd.DataFrame()
    for src, label in columns:
        if src in top.columns:
            display[label] = top[src]
    st.caption(note)
    st.dataframe(
        style.style_stats_table(
            display, team_col="Tm", team_color_fn=fteams.color_for_abbr, precision=precision,
        ),
        use_container_width=True, hide_index=True, height=520,
    )


cover_tab, rush_tab = st.tabs(["Coverage", "Pass Rush"])

with cover_tab:
    style.colored_header("Coverage", "fielding")
    # Ranked by passer rating allowed, the closest thing coverage has to a
    # single number: it folds completions, yards, touchdowns and picks on
    # throws AT this player into one figure, on a scale people already read.
    _board(
        pool, "rat",
        [("Player", "Player"), ("Tm", "Tm"), ("Pos", "Pos"), ("g", "G"),
         ("tgt", "Tgt"), ("cmp", "Cmp"), ("cmp_percent", "Cmp%"),
         ("yds", "Yds"), ("yds_tgt", "Y/Tgt"), ("td", "TD"), ("int", "INT"),
         ("dadot", "aDOT"), ("rat", "Rating")],
        {"G": "{:.0f}", "Tgt": "{:.0f}", "Cmp": "{:.0f}", "Yds": "{:.0f}",
         "TD": "{:.0f}", "INT": "{:.0f}", "Cmp%": "{:.1%}", "Y/Tgt": "{:.1f}",
         "aDOT": "{:.1f}", "Rating": "{:.1f}"},
        f"Passer rating allowed on throws into this player's coverage — lower is better. "
        f"Minimum {fdb.MIN_DEF_TARGETS} targets.",
        ascending=True,
        minimum=("tgt", fdb.MIN_DEF_TARGETS),
    )

with rush_tab:
    style.colored_header("Pass Rush", "pitching")
    # Pressures rather than sacks. A sack is the rare, luck-heavy end of a
    # pass rush; hurries and knockdowns happen far more often and describe
    # the same skill with much less noise — the same argument FIP makes
    # against ERA.
    pool = pool.copy()
    for col in ("hrry", "qbkd", "sk"):
        if col in pool.columns:
            pool[col] = pd.to_numeric(pool[col], errors="coerce")
    if {"hrry", "qbkd", "sk"} <= set(pool.columns):
        pool["pressures"] = pool[["hrry", "qbkd", "sk"]].fillna(0).sum(axis=1)
    _board(
        pool, "pressures",
        [("Player", "Player"), ("Tm", "Tm"), ("Pos", "Pos"), ("g", "G"),
         ("pressures", "Pressures"), ("hrry", "Hurries"), ("qbkd", "Knockdowns"),
         ("sk", "Sacks"), ("bltz", "Blitzes")],
        {"G": "{:.0f}", "Pressures": "{:.0f}", "Hurries": "{:.0f}",
         "Knockdowns": "{:.0f}", "Sacks": "{:.1f}", "Blitzes": "{:.0f}"},
        "Pressures combine hurries, knockdowns and sacks. Sacks alone are the rare, "
        "noisy end of a pass rush; pressures describe the same skill far more often.",
        ascending=False,
    )
