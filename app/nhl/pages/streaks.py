"""NHL Streaks — active point streaks and team win/loss runs."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nhl import db as ndb
from nhl import teams as nteams

st.set_page_config(page_title="NHL Streaks | Diamond Metrics", layout="wide")
st.title("Streaks")

mtime = ndb.nhl_db_mtime()

style.colored_header("Point Streaks", "batting")
streaks = ndb.active_point_streaks(mtime)
window = ndb.skater_log_window()
if window:
    # Say plainly what these are measured over. Daily logs only cover the
    # window the ingest has collected, so a streak longer than that window
    # would be reported at the window's length rather than its true one — and
    # in the offseason these are the streaks as they stood at season's end,
    # not live ones.
    st.caption(
        f"Consecutive games with at least a point. Daily game logs cover "
        f"{window[0]} to {window[1]}, so no streak here can be reported longer "
        f"than that window."
    )
if streaks.empty:
    st.caption("No active point streaks on file.")
else:
    show = pd.DataFrame({
        "Player": streaks["Name"],
        "Pos": streaks["Pos"],
        "Tm": streaks["Tm"].map(nteams._primary),
        "Games": streaks["Games"],
        "Points": streaks["Points"],
        "Through": streaks["Last Game"],
    })
    st.dataframe(
        style.style_stats_table(
            show, team_col="Tm", team_color_fn=nteams.color_for_abbr,
            higher_better=["Games", "Points"],
            precision={"Games": "{:.0f}", "Points": "{:.0f}"},
        ),
        use_container_width=True, hide_index=True, height=460,
    )

style.colored_header("Team Streaks", "headliners")
standings = ndb.load_standings()
if standings.empty:
    st.caption("Standings unavailable right now — the NHL's API may be temporarily down.")
else:
    rows = standings.copy()
    rows["streakCount"] = pd.to_numeric(rows["streakCount"], errors="coerce")
    rows = rows.dropna(subset=["streakCode", "streakCount"])
    # NHL streaks come in three kinds, not two: a shootout/overtime loss is
    # its own code (OT) and is neither a win nor a regulation loss, so it gets
    # its own column rather than being lumped in with losses.
    groups = [("W", "Winning", "higher"), ("L", "Losing", "lower"), ("OT", "Overtime losses", "lower")]
    cols = st.columns(len(groups))
    for col, (code, label, direction) in zip(cols, groups):
        frame = rows[rows["streakCode"] == code].sort_values("streakCount", ascending=False)
        with col:
            st.markdown(f"**{label}**")
            if frame.empty:
                st.caption(f"None active.")
                continue
            show = pd.DataFrame({
                "Tm": frame["teamAbbrev"],
                "Run": frame["streakCount"].astype(int),
                "PTS": frame["points"].astype(int),
                "L10": (
                    frame["l10Wins"].astype(int).astype(str) + "-"
                    + frame["l10Losses"].astype(int).astype(str) + "-"
                    + frame["l10OtLosses"].astype(int).astype(str)
                ),
            })
            st.dataframe(
                style.style_stats_table(
                    show, team_col="Tm", team_color_fn=nteams.color_for_abbr,
                    higher_better=["Run"] if direction == "higher" else ["PTS"],
                    lower_better=["Run"] if direction == "lower" else [],
                    precision={"Run": "{:.0f}", "PTS": "{:.0f}"},
                ),
                use_container_width=True, hide_index=True, height=400,
            )
