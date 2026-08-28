"""NHL Awards Race — Hart, Norris, Vezina and Calder composites.

Each is a weighted blend of z-scores over that award's qualifying pool, so a
score says "how far above this season's field", not "who the voters will
pick". The NHL counterpart to the MLB Awards Race page."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nhl import db as ndb
from nhl import style as nstyle
from nhl import teams as nteams

st.set_page_config(page_title="NHL Awards Race | Diamond Metrics", layout="wide")
st.title("Awards Race")
nstyle.glossary_link()

mtime = ndb.nhl_db_mtime()
seasons = ndb.skater_seasons(mtime)
if not seasons:
    st.info("No NHL skater data yet — run ingest/nhl_refresh.py to backfill.")
    st.stop()

season = st.selectbox("Season", seasons, format_func=ndb.season_label)


def _toi(seconds) -> str:
    """timeOnIcePerGame is stored in seconds; ice time reads as MM:SS."""
    if pd.isna(seconds):
        return "—"
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


def _render(df: pd.DataFrame, name_col: str, score_col: str, columns, precision, empty_note: str):
    if df.empty:
        st.caption(empty_note)
        return
    top = df.head(5).copy()
    top["Tm"] = top["teamAbbrevs"].map(nteams._primary)
    if "timeOnIcePerGame" in top.columns:
        top["TOI/GP"] = top["timeOnIcePerGame"].map(_toi)
    display = top[[name_col, "Tm"] + [c for c, _ in columns] + [score_col]].rename(
        columns={name_col: "Name", **{c: label for c, label in columns}}
    )
    st.dataframe(
        style.style_stats_table(
            display, team_col="Tm", team_color_fn=nteams.color_for_abbr,
            precision={**precision, score_col: "{:.2f}"},
        ),
        use_container_width=True, hide_index=True,
    )


style.colored_header("Hart Trophy", "batting")
st.caption(
    "Most valuable skater. Points lead, but raw totals flatter whoever gets the most "
    "power-play time — so 5v5 scoring rate and on-ice expected-goals share carry real "
    "weight, separating a player driving results from one riding a good line."
)
_render(
    ndb.hart_race(season, mtime), "skaterFullName", "Hart Score",
    [("gamesPlayed", "GP"), ("goals", "G"), ("assists", "A"), ("points", "P"),
     ("pointsPer605v5", "P/60 5v5"), ("xGF_pct_5v5", "xGF% 5v5")],
    {"P/60 5v5": "{:.2f}", "xGF% 5v5": "{:.1f}"},
    f"Not enough skaters with {ndb.HART_MIN_GP}+ games this season.",
)

style.colored_header("Norris Trophy", "fielding")
st.caption(
    "Best all-round defenceman, scored against other defencemen only rather than "
    "against forwards who out-point them by definition. Ice time counts here in a way "
    "it doesn't for forwards — coaches give their best defenceman the hardest minutes."
)
_render(
    ndb.norris_race(season, mtime), "skaterFullName", "Norris Score",
    [("gamesPlayed", "GP"), ("points", "P"), ("xGF_pct_5v5", "xGF% 5v5"),
     ("TOI/GP", "TOI/GP"), ("blockedShots", "Blocks")],
    {"xGF% 5v5": "{:.1f}"},
    f"Not enough defencemen with {ndb.NORRIS_MIN_GP}+ games this season.",
)

style.colored_header("Vezina Trophy", "pitching")
st.caption(
    "Best goaltender, led by goals saved above expected — xGA minus the goals actually "
    "allowed, which prices how hard the shots were instead of treating every save alike "
    "the way raw save percentage does. Save rate is scaled by games played so a short "
    "hot run can't outrank a starter's season."
)
_render(
    ndb.vezina_race(season, mtime), "goalieFullName", "Vezina Score",
    [("gamesPlayed", "GP"), ("wins", "W"), ("GSAx", "GSAx"), ("savePct", "SV%"),
     ("goalsAgainstAverage", "GAA"), ("shutouts", "SO")],
    {"GSAx": "{:+.1f}", "SV%": "{:.1f}", "GAA": "{:.2f}"},
    f"Not enough goalies with {ndb.VEZINA_MIN_GP}+ games this season.",
)

style.colored_header("Calder Trophy", "headliners")
st.caption(
    "Best rookie skater. Rookie status is derived rather than given — a player counts "
    "as a rookie in the first season they appear in the data at all, which means the "
    "earliest season on file can't be scored, since everyone looks new in it."
)
_render(
    ndb.calder_race(season, mtime), "skaterFullName", "Calder Score",
    [("gamesPlayed", "GP"), ("goals", "G"), ("assists", "A"), ("points", "P"),
     ("pointsPer605v5", "P/60 5v5")],
    {"P/60 5v5": "{:.2f}"},
    "No rookie pool for this season — it's the earliest season on file, so every "
    "player in it would count as a rookie.",
)
