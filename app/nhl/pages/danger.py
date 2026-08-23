"""Danger Zones — where a team creates and concedes scoring chances, drawn
as a smooth expected-goals surface on the rink rather than a scatter of dots.

Everything here is powered by SLOT (Shot Location & Outcome Threat), our own
expected-goals model — see ingest/nhl_xg.py. Because SLOT is deliberately
shooter-agnostic, the gap between what a team (or player, or goalie) actually
did and what SLOT expected is itself the finding: goals above expected is
finishing talent, goals prevented below expected is goaltending."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nhl import db as ndb
from nhl import style as nstyle
from nhl import teams as nteams

st.set_page_config(page_title="NHL Danger Zones | Diamond Metrics", layout="wide")
st.title("Danger Zones")

mtime = ndb.nhl_db_mtime()
seasons = ndb.skater_seasons(mtime)
if not seasons:
    st.info("No NHL data yet — run ingest/nhl_refresh.py to backfill.")
    st.stop()

col_season, col_team, _ = st.columns([1, 1, 2])
season = col_season.selectbox("Season", seasons, format_func=lambda s: f"{s}-{s + 1}")

shots = ndb.load_shot_xg(season, mtime)
if shots.empty:
    st.info("No SLOT-scored shots for this season yet — run `python ingest/nhl_xg.py`.")
    st.stop()

games_played = ndb.team_games_played(season, mtime)
team_options = sorted(t for t in shots["forTeam"].dropna().unique())
default_team = team_options.index("EDM") if "EDM" in team_options else 0
team = col_team.selectbox("Team", team_options, index=default_team,
                          format_func=lambda a: f"{a} — {nteams.nickname_for_abbr(a)}")

gp = games_played.get(team, 0) or 1
league_team_games = sum(games_played.values()) or 1

# --- the surface -------------------------------------------------------------
view = st.radio("View", ["Offense", "Defense", "Offense vs league", "Defense vs league"],
                horizontal=True, label_visibility="collapsed")

is_defense = view.startswith("Defense")
is_diff = view.endswith("vs league")
side_col = "againstTeam" if is_defense else "forTeam"
sub = shots[shots[side_col] == team]

xc, yc, z_team = nstyle.surface_grid(sub["x"], sub["y"], weights=sub["xg"], games=gp)
if is_diff:
    # League baseline is per TEAM-GAME, so it's directly comparable to one
    # team's per-game rate: every game contributes an offense and a defense.
    _, _, z_league = nstyle.surface_grid(shots["x"], shots["y"], weights=shots["xg"],
                                         games=league_team_games)
    z = z_team - z_league
    label = ("xG conceded vs league" if is_defense else "xG created vs league")
else:
    z = z_team
    label = ("xG conceded per game" if is_defense else "xG created per game")

fig = nstyle.surface_chart(
    xc, yc, z, diverging=is_diff, unit="xG/game",
    title=f"{nteams.nickname_for_abbr(team)} — {label}", height=520,
)
st.plotly_chart(fig, use_container_width=True)
if is_diff:
    st.caption("Red = more than a league-average team generates from that spot; blue = less. "
               "Every shot is normalized to attack the right-hand goal.")

# --- team totals -------------------------------------------------------------
by_for = shots.groupby("forTeam").agg(xGF=("xg", "sum"), GF=("is_goal", "sum"))
by_against = shots.groupby("againstTeam").agg(xGA=("xg", "sum"), GA=("is_goal", "sum"))
totals = by_for.join(by_against, how="outer").fillna(0.0)
totals["GP"] = totals.index.map(lambda a: games_played.get(a, 0))
totals = totals[totals["GP"] > 0]
totals["xGF/GP"] = totals["xGF"] / totals["GP"]
totals["xGA/GP"] = totals["xGA"] / totals["GP"]
totals["xG%"] = 100 * totals["xGF"] / (totals["xGF"] + totals["xGA"])
totals["Finishing"] = totals["GF"] - totals["xGF"]      # scored more than the chances were worth
totals["Goaltending"] = totals["xGA"] - totals["GA"]    # saved more than expected

row = totals.loc[team]
m = st.columns(5)
m[0].metric("xG created / game", f"{row['xGF/GP']:.2f}")
m[1].metric("xG conceded / game", f"{row['xGA/GP']:.2f}")
m[2].metric("Share of xG", f"{row['xG%']:.1f}%")
m[3].metric("Finishing", f"{row['Finishing']:+.1f}", help="Goals scored minus SLOT expected — shooting talent (or luck).")
m[4].metric("Goaltending", f"{row['Goaltending']:+.1f}", help="SLOT expected against minus goals allowed — saves above expected.")

# --- league table ------------------------------------------------------------
style.colored_header("Every team", "headliners")
table = totals.reset_index().rename(columns={"index": "Team"})
table.columns = ["Team"] + list(table.columns[1:])
table = table.sort_values("xG%", ascending=False)
st.dataframe(
    table[["Team", "GP", "xGF/GP", "xGA/GP", "xG%", "GF", "GA", "Finishing", "Goaltending"]],
    hide_index=True, use_container_width=True,
    column_config={
        "xGF/GP": st.column_config.NumberColumn("xGF/GP", format="%.2f"),
        "xGA/GP": st.column_config.NumberColumn("xGA/GP", format="%.2f"),
        "xG%": st.column_config.NumberColumn("xG%", format="%.1f%%"),
        "GF": st.column_config.NumberColumn("GF", format="%d"),
        "GA": st.column_config.NumberColumn("GA", format="%d"),
        "Finishing": st.column_config.NumberColumn("Finishing", format="%+.1f"),
        "Goaltending": st.column_config.NumberColumn("Goaltending", format="%+.1f"),
    },
)

# --- who beats the model -----------------------------------------------------
skaters = ndb.load_skaters(season, mtime)
if not skaters.empty:
    style.colored_header("Finishing — goals above SLOT", "batting")
    per_shooter = shots.groupby("shooterId").agg(
        Shots=("xg", "size"), xG=("xg", "sum"), G=("is_goal", "sum"), Tm=("forTeam", "last"))
    per_shooter = per_shooter[per_shooter["Shots"] >= 100]
    per_shooter["Above"] = per_shooter["G"] - per_shooter["xG"]
    names = skaters[["playerId", "skaterFullName"]].drop_duplicates("playerId")
    per_shooter = (per_shooter.reset_index()
                   .merge(names, left_on="shooterId", right_on="playerId", how="left")
                   .dropna(subset=["skaterFullName"]))
    best = per_shooter.nlargest(10, "Above")
    worst = per_shooter.nsmallest(5, "Above")
    c1, c2 = st.columns(2)
    for col, frame, heading in ((c1, best, "Most above expected"), (c2, worst, "Most below expected")):
        with col:
            st.markdown(f"**{heading}**")
            st.dataframe(
                frame[["skaterFullName", "Tm", "Shots", "xG", "G", "Above"]]
                .rename(columns={"skaterFullName": "Player"}),
                hide_index=True, use_container_width=True,
                column_config={
                    "xG": st.column_config.NumberColumn("xG", format="%.1f"),
                    "G": st.column_config.NumberColumn("G", format="%d"),
                    "Above": st.column_config.NumberColumn("+/-", format="%+.1f"),
                },
            )

goalies = ndb.load_goalies(season, mtime)
if not goalies.empty:
    style.colored_header("Goaltending — goals saved above expected (GSAx)", "pitching")
    faced = shots[shots["goalieId"].notna()]
    per_goalie = faced.groupby("goalieId").agg(
        Shots=("xg", "size"), xGA=("xg", "sum"), GA=("is_goal", "sum"), Tm=("againstTeam", "last"))
    per_goalie = per_goalie[per_goalie["Shots"] >= 400]
    per_goalie["GSAx"] = per_goalie["xGA"] - per_goalie["GA"]
    gnames = goalies[["playerId", "goalieFullName"]].drop_duplicates("playerId")
    per_goalie = (per_goalie.reset_index()
                  .merge(gnames, left_on="goalieId", right_on="playerId", how="left")
                  .dropna(subset=["goalieFullName"]))
    st.dataframe(
        per_goalie.nlargest(12, "GSAx")[["goalieFullName", "Tm", "Shots", "xGA", "GA", "GSAx"]]
        .rename(columns={"goalieFullName": "Goalie", "Shots": "Shots faced"}),
        hide_index=True, use_container_width=True,
        column_config={
            "xGA": st.column_config.NumberColumn("xGA", format="%.1f"),
            "GA": st.column_config.NumberColumn("GA", format="%d"),
            "GSAx": st.column_config.NumberColumn("GSAx", format="%+.1f"),
        },
    )

# --- model card --------------------------------------------------------------
card = ndb.load_slot_metrics()
if card:
    hold = card.get("holdout", {})
    with st.expander("How SLOT works, and how well it does"):
        st.markdown(
            f"**SLOT — {card.get('full_name', '')}** estimates the chance an unblocked shot "
            "becomes a goal from where it was taken (distance and angle), how "
            "(shot type), the state it was taken in (skaters on each side, empty net), "
            "whether it came off a rebound, and how long since the last attempt. "
            "No player identity is a feature — that's what makes the gap between actual "
            "and expected readable as finishing or goaltending talent.\n\n"
            f"Trained on {card.get('n_attempts', 0):,} attempts and validated on a *temporal* "
            f"holdout — the last {hold.get('n', 0):,} attempts of the season, from "
            f"{hold.get('first_date', '')} on, which the model never saw in training."
        )
        res = pd.DataFrame(hold.get("results", []))
        if not res.empty:
            st.dataframe(res.rename(columns={"model": "Model", "auc": "AUC",
                                             "log_loss": "Log loss", "brier": "Brier"}),
                         hide_index=True, use_container_width=True,
                         column_config={
                             "AUC": st.column_config.NumberColumn("AUC", format="%.4f"),
                             "Log loss": st.column_config.NumberColumn("Log loss", format="%.4f"),
                             "Brier": st.column_config.NumberColumn("Brier", format="%.5f"),
                         })
        cal = pd.DataFrame(hold.get("calibration", []))
        if not cal.empty:
            st.markdown("**Calibration** — of the shots SLOT rated at each level, how many actually went in:")
            st.dataframe(cal.rename(columns={"bin": "Decile", "n": "Shots",
                                             "predicted": "Predicted", "actual": "Actual"}),
                         hide_index=True, use_container_width=True,
                         column_config={
                             "Predicted": st.column_config.NumberColumn("Predicted", format="%.4f"),
                             "Actual": st.column_config.NumberColumn("Actual", format="%.4f"),
                         })
        st.caption("Blocked shots are excluded: the NHL records them from the blocking team's "
                   "point of view, so their coordinates are the block point at the wrong end of "
                   "the ice. Shootout attempts are excluded as a different kind of event.")
