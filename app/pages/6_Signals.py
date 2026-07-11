import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import sidebar
import style
import teams

st.set_page_config(page_title="Signals | Sabermetrics Dashboard", layout="wide")
sidebar.render_search()
st.title("Breakout & Regression Signals")
st.caption(
    "Compares actual results against quality-of-contact/skill indicators (xwOBA for hitters, "
    "FIP for pitchers) to flag players whose performance looks unsustainable — in either direction. "
    "This isn't a guarantee, just a gap between results and the underlying process."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
seasons = db.get_seasons("batting")
season = st.selectbox("Season", seasons, index=0)

batting = db.load_batting(season, mtime)
pitching = db.load_pitching(season, mtime)
qualified_batting = batting[batting["PA"] >= 50].dropna(subset=["wOBA", "xwOBA"]).copy()
qualified_pitching = pitching[pitching["IP"] >= 20].dropna(subset=["ERA", "FIP"]).copy()

qualified_batting["gap"] = (qualified_batting["xwOBA"] - qualified_batting["wOBA"]).round(3)
qualified_pitching["gap"] = (qualified_pitching["ERA"] - qualified_pitching["FIP"]).round(2)

style.colored_header("Batting: Underlying Quality vs. Results", "batting")
st.caption("xwOBA = expected wOBA from quality of contact. A positive gap means the underlying contact quality is better than the results so far — a buy-low signal. A negative gap means results are outrunning the quality of contact — due for regression.")

bcol1, bcol2 = st.columns(2)
with bcol1:
    st.markdown("**Buy Low (underperforming their contact quality)**")
    buy_low = qualified_batting.sort_values("gap", ascending=False).head(15)
    display = teams.add_team_abbr(buy_low)[["Name", "Tm", "PA", "wOBA", "xwOBA", "gap"]]
    st.dataframe(
        style.style_stats_table(
            display, higher_better=["gap"], team_col="Tm", team_color_fn=teams.color_for_abbr,
            precision={"wOBA": "{:.3f}", "xwOBA": "{:.3f}", "gap": "{:+.3f}"},
        ),
        use_container_width=True, height=520, hide_index=True,
    )
with bcol2:
    st.markdown("**Sell High / Regression Risk (outperforming their contact quality)**")
    sell_high = qualified_batting.sort_values("gap", ascending=True).head(15)
    display = teams.add_team_abbr(sell_high)[["Name", "Tm", "PA", "wOBA", "xwOBA", "gap"]]
    st.dataframe(
        style.style_stats_table(
            display, lower_better=["gap"], team_col="Tm", team_color_fn=teams.color_for_abbr,
            precision={"wOBA": "{:.3f}", "xwOBA": "{:.3f}", "gap": "{:+.3f}"},
        ),
        use_container_width=True, height=520, hide_index=True,
    )

style.colored_header("Pitching: FIP vs. ERA", "pitching")
st.caption("FIP strips out defense/luck on balls in play. A positive gap (ERA above FIP) means the pitcher has been unlucky or poorly supported — a buy-low signal. A negative gap means ERA is being flattered by luck/defense — due for regression.")

pcol1, pcol2 = st.columns(2)
with pcol1:
    st.markdown("**Buy Low (ERA worse than FIP suggests it should be)**")
    buy_low_p = qualified_pitching.sort_values("gap", ascending=False).head(15)
    display = teams.add_team_abbr(buy_low_p)[["Name", "Tm", "IP", "ERA", "FIP", "gap"]]
    st.dataframe(
        style.style_stats_table(
            display, higher_better=["gap"], team_col="Tm", team_color_fn=teams.color_for_abbr,
            precision={"ERA": "{:.2f}", "FIP": "{:.2f}", "gap": "{:+.2f}"},
        ),
        use_container_width=True, height=520, hide_index=True,
    )
with pcol2:
    st.markdown("**Sell High / Regression Risk (ERA better than FIP suggests it should be)**")
    sell_high_p = qualified_pitching.sort_values("gap", ascending=True).head(15)
    display = teams.add_team_abbr(sell_high_p)[["Name", "Tm", "IP", "ERA", "FIP", "gap"]]
    st.dataframe(
        style.style_stats_table(
            display, lower_better=["gap"], team_col="Tm", team_color_fn=teams.color_for_abbr,
            precision={"ERA": "{:.2f}", "FIP": "{:.2f}", "gap": "{:+.2f}"},
        ),
        use_container_width=True, height=520, hide_index=True,
    )
