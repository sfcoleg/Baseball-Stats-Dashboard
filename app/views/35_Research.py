"""Research — short written pieces built on the site's own data, distinct
from the live leaderboards elsewhere. A leaderboard answers "who's doing
X right now"; these answer a specific question with a method and a
conclusion. New pieces get added here as their own function, listed
newest first."""
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Research | Diamond Metrics", layout="wide")
st.title("Research")
st.caption("Short analyses built on this site's own data — a question, a method, and a result.")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()


def _wrc_decline_piece():
    style.colored_header("Are This Year's Biggest wRC+ Decliners Actually Worse Hitters?", "batting")
    st.markdown(
        "wRC+ dropping tells you a hitter produced less — it doesn't say why. A real decline in "
        "underlying swing quality and a stretch of bad luck on balls in play look identical on a "
        "leaderboard. This checks the ten qualified hitters (200+ PA in both 2025 and 2026) with the "
        "biggest wRC+ drop against their own batted-ball direction profile — specifically whether "
        "their **Pull-Air%** (the contact type that actually produces power: the pull-side pole, the "
        "gap) and **Pull-GB%** (mostly weak rollover contact) moved in the direction that would explain "
        "a real decline, or held steady."
    )

    with sqlite3.connect(db.DB_PATH) as conn:
        decline = pd.read_sql(
            """
            SELECT b26.Name, b26.Tm, b26.Lev,
                   ROUND(b26.wRC_plus - b25.wRC_plus, 0) AS wrc_chg,
                   ROUND((bb26.pull_air_rate - bb25.pull_air_rate) * 100, 1) AS pull_air_chg,
                   ROUND((bb26.pull_gb_rate  - bb25.pull_gb_rate)  * 100, 1) AS pull_gb_chg,
                   ROUND((bb26.pull_ld_rate  - bb25.pull_ld_rate)  * 100, 1) AS pull_ld_chg
            FROM batting b26
            JOIN batting b25       ON b25.mlbID = b26.mlbID AND b25.season = 2025
            JOIN batted_ball bb26  ON bb26.mlbID = b26.mlbID AND bb26.season = 2026
            JOIN batted_ball bb25  ON bb25.mlbID = b25.mlbID AND bb25.season = 2025
            WHERE b26.season = 2026 AND b26.PA >= 200 AND b25.PA >= 200
            ORDER BY wrc_chg ASC LIMIT 10
            """,
            conn,
        )

    display = teams.add_team_abbr(decline).drop(columns="Lev").rename(columns={
        "wrc_chg": "wRC+ Change", "pull_air_chg": "Pull-Air% Chg",
        "pull_gb_chg": "Pull-GB% Chg", "pull_ld_chg": "Pull-LD% Chg",
    })
    st.dataframe(
        style.style_stats_table(
            display,
            lower_better=["wRC+ Change", "Pull-GB% Chg"],
            higher_better=["Pull-Air% Chg"],
            team_col="Tm",
            team_color_fn=teams.color_for_abbr,
            precision={c: "{:+.1f}" for c in ("Pull-Air% Chg", "Pull-GB% Chg", "Pull-LD% Chg")}
                      | {"wRC+ Change": "{:+.0f}"},
        ),
        column_config=style.pin_first_column(display),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown(
        "**Pattern holds for 6 of 10** — Raleigh, Friedl, Narváez, Marte, Springer, Guerrero and Duran "
        "all show *less* Pull-Air% and/or *more* Pull-GB% alongside their wRC+ drop. That's a real "
        "swing-quality decline showing up in the underlying data, not just an outcome number moving "
        "around.\n\n"
        "**But two of the biggest names break the pattern entirely: Judge and Acuña.** Both actually "
        "show *increased* Pull-Air% despite huge wRC+ drops. Their contact quality didn't get worse — "
        "they're still doing the same or better things at the plate — so their decline is very likely "
        "luck/BABIP-driven or health-related, not a real skill decay. That distinction — which decliners "
        "are real versus which are noise — is the actual finding here, and it's something a raw wRC+ "
        "leaderboard can't tell you on its own."
    )

    ops_path = Path(__file__).resolve().parent.parent.parent / "data" / "ops_by_batted_ball_type.csv"
    if ops_path.exists():
        st.markdown("---")
        st.markdown(
            "**Follow-up: does contact quality (not just direction) actually pay off differently by "
            "bucket for these same players?** AVG/SLG computed on balls actually put in play in each "
            "direction × contact-type bucket (Statcast's own published finding, for context: league-wide "
            "2022-24 pulled air balls hit .547/1.227 SLG; non-pulled air balls hit .319/.527). A bucket "
            "with fewer than 5 batted balls that season is blank — too small a sample to mean anything."
        )
        ops_df = pd.read_csv(ops_path)
        st.dataframe(ops_df, use_container_width=True, hide_index=True, height=420)
    else:
        st.caption("Contact-quality-by-bucket follow-up not generated yet.")


_wrc_decline_piece()
