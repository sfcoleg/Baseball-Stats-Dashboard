import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style

st.set_page_config(page_title="Umpires | Diamond Metrics", layout="wide")
st.title("Umpires")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
ump_games = db.load_ump_games(mtime)
today = db.today_pacific()


def _accuracy_line(called: int, correct: int) -> str:
    return f"{100 * correct / called:.1f}% accuracy on {called} called pitches" if called else "—"


def _favor_line(favor_home: int, away_abbr: str, home_abbr: str) -> str:
    if favor_home > 0:
        return f"Misses favored {home_abbr} by {favor_home}"
    if favor_home < 0:
        return f"Misses favored {away_abbr} by {-favor_home}"
    return "Misses evened out"


# --- Live: whoever is behind the plate right now ---------------------------
todays_games = db.load_todays_games(mtime)
live_scores = db.load_live_scores(today)
in_progress = [pk for pk, g in live_scores.items() if g.get("status") == "In Progress"]
matchup_by_pk = (
    {row["game_pk"]: f"{row['away_abbr']} @ {row['home_abbr']}" for _, row in todays_games.iterrows()}
    if not todays_games.empty else {}
)
if in_progress:
    style.colored_header("Behind the Plate Right Now", "pitching")
    st.caption("Live accuracy, updating as calls come in. Expand a game for the zone plot.")
    cols = st.columns(min(3, len(in_progress)))
    for i, pk in enumerate(in_progress):
        detail = db.load_ump_game_detail(pk)
        with cols[i % len(cols)]:
            with st.container(border=True):
                st.markdown(f"**{matchup_by_pk.get(pk, 'Game')}**")
                if not detail:
                    st.caption("No called pitches yet.")
                    continue
                st.markdown(f"{detail['ump_name'] or 'Unknown umpire'}")
                st.metric("Accuracy", f"{detail['accuracy']:.1f}%", f"{detail['called']} called pitches",
                          delta_color="off")
                st.caption(
                    f"{detail['wrong_strikes']} wrong strike{'s' if detail['wrong_strikes'] != 1 else ''}, "
                    f"{detail['wrong_balls']} wrong ball{'s' if detail['wrong_balls'] != 1 else ''}"
                )
                with st.expander("Zone plot"):
                    st.plotly_chart(style.ump_zone_plot(detail["pitches"]), use_container_width=True,
                                    key=f"live_zone_{pk}")

# --- Daily scorecards ------------------------------------------------------
style.colored_header("Daily Scorecards", "batting")
if ump_games.empty:
    st.caption("No graded games yet — run ingest/ump_scorecards.py to backfill.")
else:
    min_day = pd.to_datetime(ump_games["date"]).min().date()
    pick = st.date_input(
        "Date", value=today - timedelta(days=1), min_value=min_day, max_value=today,
    )
    day_rows = ump_games[ump_games["date"] == pick.isoformat()].sort_values("ump_name")
    if day_rows.empty:
        st.caption("No graded games on this date.")
    else:
        league_day_acc = 100 * day_rows["correct"].sum() / day_rows["called"].sum()
        st.caption(f"{len(day_rows)} games · league accuracy {league_day_acc:.1f}% this day")
        card_cols = st.columns(2)
        for i, (_, g) in enumerate(day_rows.iterrows()):
            with card_cols[i % 2]:
                with st.container(border=True):
                    score_bit = (
                        f" ({int(g['away_score'])}-{int(g['home_score'])})"
                        if pd.notna(g["away_score"]) and pd.notna(g["home_score"]) else ""
                    )
                    st.markdown(f"**{g['ump_name']}** — {g['away_abbr']} @ {g['home_abbr']}{score_bit}")
                    st.markdown(
                        f"<div style='font-size:1.6rem;font-weight:700'>"
                        f"{100 * g['correct'] / g['called']:.1f}%</div>",
                        unsafe_allow_html=True,
                    )
                    st.caption(_accuracy_line(g["called"], g["correct"]))
                    st.caption(
                        f"{g['wrong_strikes']} wrong strikes · {g['wrong_balls']} wrong balls · "
                        + _favor_line(g["favor_home"], g["away_abbr"], g["home_abbr"])
                    )
                    if g["worst_desc"]:
                        st.caption(f"Worst call: {g['worst_desc']}")
                    with st.expander("Zone plot"):
                        detail = db.load_ump_game_detail(g["game_pk"])
                        if detail:
                            st.plotly_chart(
                                style.ump_zone_plot(detail["pitches"]), use_container_width=True,
                                key=f"day_zone_{g['game_pk']}",
                            )
                        else:
                            st.caption("Pitch detail unavailable for this game.")

# --- Season leaderboard ----------------------------------------------------
style.colored_header("Season Leaderboard", "fielding")
if not ump_games.empty:
    lb_col1, lb_col2 = st.columns([1, 2])
    with lb_col1:
        seasons = sorted(ump_games["season"].unique(), reverse=True)
        lb_season = st.selectbox("Season", seasons)
    with lb_col2:
        min_games = st.slider("Minimum plate games", 1, 30, 10)
    lb = db.ump_leaderboard(ump_games, lb_season, min_games)
    if lb.empty:
        st.caption("No umpires meet the minimum for this season.")
    else:
        st.caption(
            '"vs Expected" is the difficulty adjustment: this ump\'s accuracy minus what a league-average '
            "ump would have scored on the same pitches (league accuracy per distance-from-zone-edge bucket, "
            "weighted by the borderline-pitch mix this ump actually faced). Positive = better than the "
            "schedule they were dealt."
        )
        st.dataframe(
            style.style_stats_table(
                lb,
                higher_better=["Accuracy", "vs Expected"],
                lower_better=["Wrong K", "Wrong BB", "Clear Misses/G"],
                precision={
                    "Accuracy": "{:.2f}", "vs Expected": "{:+.2f}", "Clear Misses/G": "{:.1f}",
                },
            ),
            use_container_width=True, height=600, hide_index=True,
        )

# --- Umpire trends ---------------------------------------------------------
style.colored_header("Umpire Trends", "headliners")
if not ump_games.empty:
    by_games = ump_games.groupby("ump_name")["game_pk"].count().sort_values(ascending=False)
    chosen = st.selectbox("Umpire", by_games.index.tolist())
    mine = ump_games[ump_games["ump_name"] == chosen].sort_values("date").copy()
    mine["acc"] = 100 * mine["correct"] / mine["called"]
    season_cols = st.columns(len(sorted(mine["season"].unique())) or 1)
    for col, (season, seg) in zip(season_cols, sorted(mine.groupby("season"), key=lambda kv: kv[0])):
        with col:
            st.metric(
                f"{season}", f"{100 * seg['correct'].sum() / seg['called'].sum():.1f}%",
                f"{len(seg)} games", delta_color="off",
            )
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=mine["date"], y=mine["acc"], mode="markers", name="Game accuracy",
        marker=dict(size=6, color=style.CHART_BLUE, opacity=0.55),
        hovertext=[
            f"{r['date']} — {r['away_abbr']} @ {r['home_abbr']}: {r['acc']:.1f}%"
            for _, r in mine.iterrows()
        ],
        hoverinfo="text",
    ))
    rolling = mine["acc"].rolling(7, min_periods=3).mean()
    fig.add_trace(go.Scatter(
        x=mine["date"], y=rolling, mode="lines", name="7-game average",
        line=dict(color=style.CHART_AMBER, width=2.5),
    ))
    fig.update_yaxes(ticksuffix="%", gridcolor="rgba(74,82,102,0.25)", color=style.CHART_DIM)
    fig.update_xaxes(color="#9AA3B5")
    fig.update_layout(
        height=320, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=style.CHART_TEXT,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
    )
    st.plotly_chart(fig, use_container_width=True)

# --- Methodology -----------------------------------------------------------
with st.expander("Methodology & honest limitations"):
    st.markdown(
        """
- **The zone, per batter.** A called strike is graded correct if any part of the ball crossed the
  rulebook zone: plate width plus the ball's radius horizontally, and *that batter's own* measured
  zone top/bottom vertically (from MLB's tracking of their stance, pitch by pitch). A called ball is
  correct if the ball missed that region entirely.
- **Tracking error is real.** Pitch tracking carries roughly half an inch of measurement error, so
  razor-thin "misses" are approximate. Headline accuracy uses the strict geometric test; the
  "clear misses" figures only count calls more than 1 inch beyond the boundary.
- **Zone plots are normalized.** Every batter's zone is a different height, so each pitch is drawn
  relative to its own batter's zone mapped onto one reference box — a dot's inside/outside position
  always matches how the call was actually judged.
- **Difficulty adjustment.** Raw accuracy punishes umps who happened to face more borderline
  pitches. "vs Expected" compares each ump to what a league-average ump would score on the exact
  pitches they faced, bucketed by distance from the zone edge (computed per season).
- **2026 caveat.** Under the ABS challenge system, an overturned call may be recorded
  post-correction, which can slightly flatter measured accuracy this season.
- **Only judgment calls count.** Automatic balls/strikes (pitch-clock violations), pitchouts, and
  swings are excluded — only pitches where the umpire actually made a ball/strike decision.
        """
    )
