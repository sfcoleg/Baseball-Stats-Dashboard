"""NFL Kicking — field goals, extra points, and the kicks that actually
separate kickers.

Raw field-goal percentage is close to useless on its own: a kicker fed
nothing but chip shots and one asked for 50-yarders every week can post the
same number while being very different kickers. So distance is front and
centre, and the headline board ranks by makes from 40+."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import db as fdb
from nfl import teams as fteams

st.set_page_config(page_title="NFL Kicking | Diamond Metrics", layout="wide")
st.title("Kicking")

mtime = fdb.nfl_db_mtime()
season_list = fdb.seasons(mtime)
if not season_list:
    st.info("No NFL data yet — run `python ingest/nfl_refresh.py` to build it.")
    st.stop()

c1, c2 = st.columns(2)
season = c1.selectbox("Season", season_list, index=fdb.season_index(season_list, mtime),
                      format_func=fdb.season_label)
season_type = c2.selectbox(
    "Games", ["REG", "POST"],
    format_func=lambda t: "Regular season" if t == "REG" else "Playoffs",
)

players = fdb.load_player_seasons(season, mtime, season_type)
if players.empty or "fg_att" not in players.columns:
    st.caption(
        f"No kicking data for {fdb.season_label(season)} yet. If this season should have "
        "it, re-run `python ingest/nfl_refresh.py` — kicking columns were added after the "
        "first build."
    )
    st.stop()

kickers = players[pd.to_numeric(players["fg_att"], errors="coerce").fillna(0) >= fdb.MIN_FG_ATTEMPTS].copy()
if kickers.empty:
    st.caption(f"No kickers with {fdb.MIN_FG_ATTEMPTS}+ attempts this season.")
    st.stop()

acc_tab, dist_tab = st.tabs(["Accuracy", "By Distance"])

with acc_tab:
    style.colored_header("Field Goals", "pitching")
    st.caption(
        f"Minimum {fdb.MIN_FG_ATTEMPTS} attempts. Ranked by makes from 40 yards and out, "
        "not by raw percentage — a kicker who only attempts short ones can lead on "
        "percentage while never being asked to do the hard part."
    )
    board = kickers.sort_values(
        "fg_long_made" if "fg_long_made" in kickers.columns else "fg_made",
        ascending=False,
    ).head(25)
    display = pd.DataFrame({
        "Kicker": board["player_display_name"],
        "Tm": board["team"],
        "G": board["games"],
        "FGM": board["fg_made"],
        "FGA": board["fg_att"],
        "FG%": board.get("fg_pct"),
        "40+ M": board.get("fg_long_made"),
        "40+ A": board.get("fg_long_att"),
        "40+ %": board.get("fg_long_pct"),
        "Long": board.get("fg_long"),
        "XPM": board.get("pat_made"),
        "XPA": board.get("pat_att"),
    })
    st.dataframe(
        style.style_stats_table(
            display, team_col="Tm", team_color_fn=fteams.color_for_abbr,
            higher_better=["FGM", "FG%", "40+ M", "40+ %", "Long", "XPM"],
            precision={"G": "{:.0f}", "FGM": "{:.0f}", "FGA": "{:.0f}", "FG%": "{:.1f}",
                       "40+ M": "{:.0f}", "40+ A": "{:.0f}", "40+ %": "{:.1f}",
                       "Long": "{:.0f}", "XPM": "{:.0f}", "XPA": "{:.0f}"},
        ),
        use_container_width=True, hide_index=True, height=520,
    )

with dist_tab:
    style.colored_header("By Distance", "batting")
    st.caption(
        "Makes and misses split by range. This is where the differences live — every "
        "kicker in the league makes them from inside 40."
    )
    board = kickers.sort_values("fg_made", ascending=False).head(25)

    def _bucket(made_col, missed_col):
        made = pd.to_numeric(board.get(made_col), errors="coerce").fillna(0)
        missed = pd.to_numeric(board.get(missed_col), errors="coerce").fillna(0)
        attempts = made + missed
        return made, attempts

    m40, a40 = _bucket("fg_made_40_49", "fg_missed_40_49")
    m50, a50 = _bucket("fg_made_50_59", "fg_missed_50_59")
    m60, a60 = _bucket("fg_made_60_", "fg_missed_60_")
    display = pd.DataFrame({
        "Kicker": board["player_display_name"],
        "Tm": board["team"],
        "40-49": m40.astype(int).astype(str) + "/" + a40.astype(int).astype(str),
        "50-59": m50.astype(int).astype(str) + "/" + a50.astype(int).astype(str),
        "60+": m60.astype(int).astype(str) + "/" + a60.astype(int).astype(str),
        "Long": board.get("fg_long"),
        "GW M": board.get("gwfg_made"),
        "GW A": board.get("gwfg_att"),
    })
    st.dataframe(
        style.style_stats_table(
            display, team_col="Tm", team_color_fn=fteams.color_for_abbr,
            higher_better=["Long", "GW M"],
            precision={"Long": "{:.0f}", "GW M": "{:.0f}", "GW A": "{:.0f}"},
        ),
        use_container_width=True, hide_index=True, height=520,
    )
    st.caption("GW = game-winning field goal attempts, the ones taken with the game on the line.")
