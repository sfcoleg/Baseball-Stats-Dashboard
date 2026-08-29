"""NFL Player profile — reached from search or from a leaderboard, not from
the nav (same convention as the MLB and NHL player pages)."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nfl import db as fdb
from nfl import teams as fteams

st.set_page_config(page_title="NFL Player | Diamond Metrics", layout="wide")

mtime = fdb.nfl_db_mtime()

# Deep links carry the id in the URL; in-app navigation puts it in session
# state. Either is enough to land on a player.
if "nfl_selected_player" not in st.session_state and "player" in st.query_params:
    st.session_state["nfl_selected_player"] = st.query_params["player"]

player_id = st.session_state.get("nfl_selected_player")
if not player_id:
    st.title("Player")
    st.info("Search for a player using the box in the top bar.")
    st.stop()

career = fdb.load_player_career(player_id, mtime)
position = fdb.player_position(player_id, mtime)
defensive = fdb.is_defensive(position)

# A defender has no rows in the offensive stats feed at all, so the old
# "no career rows means no player" check would have turned every corner and
# linebacker into a warning page.
if career.empty and not defensive:
    st.title("Player")
    st.warning("No data on file for that player.")
    st.stop()

reg = career[career["season_type"] == "REG"] if not career.empty else career
_def_rows = fdb.player_pfr(player_id, "def", mtime)
if not career.empty:
    latest = (reg if not reg.empty else career).iloc[0]
    name = latest["player_display_name"]
    team = latest.get("team") or ""
else:
    # Identity comes from the defensive feed for players the offensive one
    # never sees.
    latest = _def_rows.iloc[0] if not _def_rows.empty else {}
    name = latest.get("player") or "Player"
    team = latest.get("tm") or ""
color = fteams.color_for_abbr(team)
st.query_params["player"] = str(player_id)

st.title(name)
head = []
if latest.get("headshot_url"):
    head.append(
        f"<img src='{latest['headshot_url']}' style='width:74px;height:74px;border-radius:50%;"
        f"object-fit:cover;border:2px solid {color};background:var(--dm-surface-mute)' />"
    )
badge = (
    f"<span style='background-color:{color}66;color:var(--dm-text);padding:3px 12px;"
    f"border-radius:8px;font-weight:700'>{team}</span>" if team else ""
)
st.markdown(
    "<div style='display:flex;align-items:center;gap:14px;margin-bottom:8px'>"
    + "".join(head)
    + f"<div>{badge} <span style='color:var(--dm-dim)'>{latest.get('position') or ''}</span></div>"
    "</div>",
    unsafe_allow_html=True,
)

# --- Which side of the ball to show ----------------------------------------
# A profile shouldn't show a receiver an empty passing table. Pick the groups
# this player actually has volume in, and fall back to his position group.
# A threshold, not just "> 0". Quarterbacks pick up a target or two on trick
# plays across a career, and receivers throw the odd pass — testing for any
# volume at all gave Mahomes a receiving table built on two catches.
_MIN_CAREER_VOLUME = 20


def _has(col: str) -> bool:
    if reg.empty or col not in reg.columns:
        return False
    return pd.to_numeric(reg[col], errors="coerce").fillna(0).sum() >= _MIN_CAREER_VOLUME

sections = [k for k, col in (("Passing", "attempts"), ("Rushing", "carries"), ("Receiving", "targets")) if _has(col)]
if not sections and not defensive:
    sections = ["Passing"] if position == "QB" else ["Receiving"]

SECTION_COLUMNS = {
    "Passing": ([("season", "Season"), ("team", "Tm"), ("games", "G"), ("attempts", "Att"),
                 ("completion_pct", "Cmp%"), ("passing_yards", "Yds"), ("yards_per_attempt", "Y/A"),
                 ("passing_tds", "TD"), ("passing_interceptions", "INT"),
                 ("passing_epa", "EPA"), ("passing_epa_per_att", "EPA/Att"), ("passing_cpoe", "CPOE")],
                {"Cmp%": "{:.1f}", "Y/A": "{:.1f}", "EPA": "{:.1f}", "EPA/Att": "{:.2f}", "CPOE": "{:.1f}"}),
    "Rushing": ([("season", "Season"), ("team", "Tm"), ("games", "G"), ("carries", "Att"),
                 ("rushing_yards", "Yds"), ("yards_per_carry", "Y/C"), ("rushing_tds", "TD"),
                 ("rushing_first_downs", "1D"), ("rushing_epa", "EPA"), ("rushing_epa_per_carry", "EPA/Att")],
                {"Y/C": "{:.1f}", "EPA": "{:.1f}", "EPA/Att": "{:.2f}"}),
    "Receiving": ([("season", "Season"), ("team", "Tm"), ("games", "G"), ("targets", "Tgt"),
                   ("receptions", "Rec"), ("receiving_yards", "Yds"), ("yards_per_reception", "Y/R"),
                   ("receiving_tds", "TD"), ("receiving_yards_after_catch", "YAC"),
                   ("receiving_epa", "EPA"), ("receiving_epa_per_target", "EPA/Tgt")],
                  {"Y/R": "{:.1f}", "EPA": "{:.1f}", "EPA/Tgt": "{:.2f}"}),
}

for section in sections:
    columns, precision = SECTION_COLUMNS[section]
    style.colored_header(f"{section} by Season", "batting", color)
    display = pd.DataFrame()
    for src, label in columns:
        if src in reg.columns:
            display[label] = reg[src]
    st.dataframe(
        style.style_stats_table(
            display, team_col="Tm", team_color_fn=fteams.color_for_abbr,
            higher_better=[l for _, l in columns if l not in ("Season", "Tm", "INT")],
            lower_better=["INT"] if "INT" in display.columns else [],
            precision={**precision, "Season": "{:.0f}"},
        ),
        use_container_width=True, hide_index=True,
    )

# --- Game log ---------------------------------------------------------------
weekly_seasons = (
    sorted(reg["season"].astype(int).unique(), reverse=True)
    if not reg.empty and not defensive else []
)
if weekly_seasons:
    style.colored_header("Game Log", "headliners", color)
    picked = st.selectbox("Season", weekly_seasons, format_func=fdb.season_label, key="nfl_gamelog_season")
    log = fdb.load_player_weeks(player_id, picked, mtime)
    if log.empty:
        st.caption(
            "Weekly detail is kept for the most recent seasons only — season totals above cover the rest."
        )
    else:
        cols = [("week", "Wk"), ("opponent_team", "Opp")]
        if "Passing" in sections:
            cols += [("attempts", "Att"), ("passing_yards", "Pass Yds"), ("passing_tds", "Pass TD"),
                     ("passing_interceptions", "INT"), ("passing_epa", "Pass EPA")]
        if "Rushing" in sections:
            cols += [("carries", "Car"), ("rushing_yards", "Rush Yds"), ("rushing_tds", "Rush TD")]
        if "Receiving" in sections:
            cols += [("targets", "Tgt"), ("receptions", "Rec"), ("receiving_yards", "Rec Yds"),
                     ("receiving_tds", "Rec TD")]
        display = pd.DataFrame()
        for src, label in cols:
            if src in log.columns:
                display[label] = log[src]
        st.dataframe(
            style.style_stats_table(
                display, team_col="Opp", team_color_fn=fteams.color_for_abbr,
                higher_better=[l for _, l in cols if l not in ("Wk", "Opp", "INT")],
                lower_better=["INT"] if "INT" in display.columns else [],
                precision={"Pass EPA": "{:.1f}"},
            ),
            use_container_width=True, hide_index=True, height=460,
        )


# --- Advanced, chosen by position ------------------------------------------
def _season_table(frame, columns, precision, header, note):
    """Render one advanced season-by-season block, or nothing at all.

    Silently skipping an empty frame is deliberate: a receiver has no
    passing-pressure rows and a quarterback has no coverage rows, and a
    profile full of "no data" panels is worse than a shorter one."""
    if frame is None or frame.empty:
        return
    display = pd.DataFrame()
    for src, label in columns:
        if src in frame.columns:
            display[label] = frame[src]
    if display.empty or len(display.columns) <= 1:
        return
    style.colored_header(header, "chart", color)
    if note:
        st.caption(note)
    st.dataframe(
        style.style_stats_table(display, precision={**precision, "Season": "{:.0f}"}),
        use_container_width=True, hide_index=True,
    )


if defensive:
    # Coverage first: for most defenders it is the larger part of the job,
    # and for corners and safeties it is nearly all of it.
    _season_table(
        _def_rows,
        [("season", "Season"), ("tm", "Tm"), ("pos", "Pos"), ("g", "G"),
         ("tgt", "Tgt"), ("cmp", "Cmp"), ("cmp_percent", "Cmp%"),
         ("yds", "Yds"), ("yds_tgt", "Y/Tgt"), ("td", "TD"), ("int", "INT"),
         ("dadot", "aDOT"), ("rat", "Rating")],
        {"G": "{:.0f}", "Tgt": "{:.0f}", "Cmp": "{:.0f}", "Yds": "{:.0f}",
         "TD": "{:.0f}", "INT": "{:.0f}", "Cmp%": "{:.1%}", "Y/Tgt": "{:.1f}",
         "aDOT": "{:.1f}", "Rating": "{:.1f}"},
        "Coverage",
        "Passer rating allowed on throws into his coverage — lower is better.",
    )
    rush_rows = _def_rows.copy()
    if not rush_rows.empty and {"hrry", "qbkd", "sk"} <= set(rush_rows.columns):
        for col in ("hrry", "qbkd", "sk"):
            rush_rows[col] = pd.to_numeric(rush_rows[col], errors="coerce")
        rush_rows["pressures"] = rush_rows[["hrry", "qbkd", "sk"]].fillna(0).sum(axis=1)
    _season_table(
        rush_rows,
        [("season", "Season"), ("tm", "Tm"), ("g", "G"), ("pressures", "Pressures"),
         ("hrry", "Hurries"), ("qbkd", "Knockdowns"), ("sk", "Sacks"), ("bltz", "Blitzes")],
        {"G": "{:.0f}", "Pressures": "{:.0f}", "Hurries": "{:.0f}",
         "Knockdowns": "{:.0f}", "Sacks": "{:.1f}", "Blitzes": "{:.0f}"},
        "Pass Rush",
        "Pressures combine hurries, knockdowns and sacks.",
    )
else:
    if "Passing" in sections:
        _season_table(
            fdb.player_nextgen(player_id, "passing", mtime),
            [("season", "Season"), ("attempts", "Att"),
             ("avg_time_to_throw", "Time to Throw"),
             ("avg_intended_air_yards", "Intended Air Yds"),
             ("avg_air_yards_to_sticks", "Air Yds to Sticks"),
             ("aggressiveness", "Aggressiveness%"),
             ("completion_percentage_above_expectation", "CPOE")],
            {"Att": "{:.0f}", "Time to Throw": "{:.2f}", "Intended Air Yds": "{:.1f}",
             "Air Yds to Sticks": "{:+.1f}", "Aggressiveness%": "{:.1f}", "CPOE": "{:+.1f}"},
            "Passing — Tracking",
            "How long he holds it, how far downfield he throws, and how often into coverage.",
        )
        _season_table(
            fdb.player_pfr(player_id, "pass", mtime),
            [("season", "Season"), ("pocket_time", "Pocket Time"),
             ("times_pressured", "Pressured"), ("pressure_pct", "Pressure%"),
             ("times_blitzed", "Blitzed"), ("bad_throws", "Bad Throws"),
             ("bad_throw_pct", "Bad Throw%"), ("on_tgt_pct", "On Target%"),
             ("drops", "Drops")],
            {"Pocket Time": "{:.1f}", "Pressured": "{:.0f}", "Pressure%": "{:.1f}",
             "Blitzed": "{:.0f}", "Bad Throws": "{:.0f}", "Bad Throw%": "{:.1f}",
             "On Target%": "{:.1f}", "Drops": "{:.0f}"},
            "Passing — Pocket & Accuracy",
            "Bad-throw and on-target rates separate his accuracy from his receivers' hands.",
        )
    if "Rushing" in sections:
        _season_table(
            fdb.player_nextgen(player_id, "rushing", mtime),
            [("season", "Season"), ("rush_attempts", "Att"),
             ("expected_rush_yards", "Expected"),
             ("rush_yards_over_expected", "RYOE"),
             ("rush_yards_over_expected_per_att", "RYOE/Att"),
             ("percent_attempts_gte_eight_defenders", "8+ Box%"),
             ("avg_time_to_los", "Time to LOS")],
            {"Att": "{:.0f}", "Expected": "{:.0f}", "RYOE": "{:+.0f}",
             "RYOE/Att": "{:+.2f}", "8+ Box%": "{:.1f}", "Time to LOS": "{:.2f}"},
            "Rushing — Over Expected",
            "What he gained against what the blocking and the box were worth.",
        )
    if "Receiving" in sections:
        _season_table(
            fdb.player_nextgen(player_id, "receiving", mtime),
            [("season", "Season"), ("targets", "Tgt"), ("avg_separation", "Separation"),
             ("avg_cushion", "Cushion"), ("avg_intended_air_yards", "aDOT"),
             ("avg_yac", "YAC"), ("avg_expected_yac", "Expected YAC"),
             ("avg_yac_above_expectation", "YAC +/-")],
            {"Tgt": "{:.0f}", "Separation": "{:.2f}", "Cushion": "{:.2f}",
             "aDOT": "{:.1f}", "YAC": "{:.1f}", "Expected YAC": "{:.1f}",
             "YAC +/-": "{:+.2f}"},
            "Receiving — Separation & YAC",
            "Separation is yards from the nearest defender at the catch.",
        )
