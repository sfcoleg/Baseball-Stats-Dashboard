"""NHL Playoff Picture — who's in, who's chasing, and by how much.

The Standings page lists teams by division; this one lists them by
QUALIFICATION, which is a different question. The NHL takes the top three in
each division plus two conference wild cards, so a team can sit fourth in its
division and still be comfortably in, while a team third in the other division
is out. The NHL's standings API answers this directly through
wildcardSequence: 0 means qualified via the division, 1-2 are the wild cards,
and 3+ is the chase, in order."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nhl import db as ndb
from nhl import teams as nteams

st.set_page_config(page_title="NHL Playoff Picture | Diamond Metrics", layout="wide")

clicked_team = st.query_params.get("team")
if clicked_team:
    st.session_state["nhl_team_page_selected_team"] = clicked_team
    st.switch_page("nhl/pages/team.py")

st.title("Playoff Picture")

standings = ndb.load_standings()
if standings.empty:
    st.info("Standings unavailable right now — the NHL's API may be temporarily down. Try again shortly.")
    st.stop()

GAMES_IN_SEASON = 82
CLINCH_LABELS = {
    "p": "Presidents' Trophy", "z": "Conference", "y": "Division",
    "x": "Clinched", "e": "Eliminated",
}

standings = standings.copy()
standings["remaining"] = GAMES_IN_SEASON - standings["gamesPlayed"]
season_over = standings["remaining"].max() <= 0
# Points pace only means something with games left to play; once every team has
# played 82 it is just their points again, so the column is dropped entirely.
standings["Pace"] = (
    (standings["points"] / standings["gamesPlayed"].replace(0, pd.NA)) * GAMES_IN_SEASON
).round(0)

if season_over:
    st.caption(
        "The season is complete — this is the final picture. During the season the "
        "same page shows the live race, with points back and games in hand."
    )


def _frame(rows: pd.DataFrame, cut_points=None) -> pd.DataFrame:
    out = pd.DataFrame({
        "Team": rows["teamAbbrev"],
        "GP": rows["gamesPlayed"],
        "W": rows["wins"],
        "L": rows["losses"],
        "OTL": rows["otLosses"],
        "PTS": rows["points"],
        "ROW": rows["regulationPlusOtWins"],
        "GD": rows["goalDifferential"],
        "L10": (
            rows["l10Wins"].astype(int).astype(str) + "-" + rows["l10Losses"].astype(int).astype(str)
            + "-" + rows["l10OtLosses"].astype(int).astype(str)
        ),
        "Status": rows["clinchIndicator"].map(CLINCH_LABELS).fillna(""),
    })
    if not season_over:
        out.insert(6, "Pace", rows["Pace"])
        out.insert(2, "Left", rows["remaining"])
        if cut_points is not None:
            out["PTS Back"] = (cut_points - rows["points"]).astype(int)
    return out


def _table(frame: pd.DataFrame, height=None):
    st.dataframe(
        style.style_stats_table(
            frame, team_col="Team", team_color_fn=nteams.color_for_abbr,
            higher_better=["PTS", "GD", "ROW", "Pace"],
            lower_better=["PTS Back"],
            precision={"Pace": "{:.0f}"},
        ),
        use_container_width=True, hide_index=True,
        **({"height": height} if height else {}),
    )


for conf_abbr, conf_name in (("E", "Eastern Conference"), ("W", "Western Conference")):
    conf = standings[standings["conferenceAbbrev"] == conf_abbr].sort_values("conferenceSequence")
    if conf.empty:
        continue
    style.colored_header(conf_name, "batting")

    qualified = conf[conf["wildcardSequence"].fillna(99) <= 2]
    chasing = conf[conf["wildcardSequence"].fillna(0) >= 3]
    # The cut line is the second wild card's points total — what everyone
    # below is actually chasing.
    wc_cut = qualified["points"].min() if not qualified.empty else None

    st.markdown("**In the playoff field**")
    st.caption(
        "Top three in each division, then the two wild cards — in conference seeding order."
    )
    _table(_frame(qualified))

    if not chasing.empty:
        st.markdown("**Outside looking in**" if not season_over else "**Missed the field**")
        if not season_over and wc_cut is not None:
            st.caption(f"Points back is measured against the second wild card ({int(wc_cut)} points).")
        _table(_frame(chasing, cut_points=wc_cut), height=380)
