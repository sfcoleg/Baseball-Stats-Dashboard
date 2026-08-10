import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import bracket_picks
import db
import style
import teams

st.set_page_config(page_title="Playoffs | Diamond Metrics", layout="wide")

clicked_team = st.query_params.get("team")
if clicked_team:
    st.session_state["team_page_selected_team"] = clicked_team
    st.switch_page("pages/4_Team.py")

# Off for now: with most of the regular season still to play, the actual
# bracket seeding (and therefore the "if the season ended today" bracket and
# the bracket predictor built on top of it) is too unsettled to be
# meaningful — it'll shuffle constantly and mostly just be noise until
# real playoff races start resolving. Flip this back on closer to
# September; the Playoff & World Series odds table below (a Monte Carlo
# projection, not today's actual seeding) stays useful year-round and isn't
# gated by this.
SHOW_BRACKET_FEATURES = False

if SHOW_BRACKET_FEATURES:
    bracket_picks.bootstrap()

st.title("Playoffs")
st.caption(
    "Playoff and World Series odds are a Monte Carlo simulation of the rest of the season (see the Team "
    "page for the methodology)."
    + (
        " The bracket below is the actual current seeding if the season ended today — not a simulated "
        "outcome. Click a team to jump to its Team page."
        if SHOW_BRACKET_FEATURES else ""
    )
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
standings = db.load_standings(mtime)
playoff_odds = db.compute_playoff_odds(mtime)

if standings.empty or playoff_odds.empty:
    st.info("No standings/odds data yet — run the ingest script.")
    st.stop()


def _render_bracket_features(standings, playoff_odds, mtime):
    """The "if the season ended today" bracket + the interactive bracket
    predictor — split into a function (rather than inline top-level code)
    purely so the whole thing can be skipped with one `if
    SHOW_BRACKET_FEATURES:` guard instead of re-indenting every line by
    hand. See SHOW_BRACKET_FEATURES above for why it's off right now."""
    style.colored_header("If the Season Ended Today", "headliners")
    st.markdown(style.PLAYOFF_BRACKET_CSS, unsafe_allow_html=True)
    picture = db.current_playoff_picture(mtime)
    if "AL" in picture and "NL" in picture:
        st.markdown(
            "<div style='overflow-x:auto'>"
            + style.full_playoff_bracket_html(picture["AL"], picture["NL"], teams.color_for_abbr)
            + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("No seeding data yet.")

    st.divider()

    style.colored_header("Predict the Bracket", "headliners")
    st.caption(
        "Pick a winner in each series, based on today's seeding — no account needed, your picks are saved "
        "right in this page's URL, so bookmarking or sharing the link keeps your bracket. Later rounds "
        "unlock as you fill in the ones before them."
    )
    _render_bracket_predictor(picture)
    st.divider()

    style.colored_header("Matchup Preview", "batting")
    st.caption("Stat-driven strengths/weaknesses for any two playoff teams — offense, rotation, bullpen, and defense.")
    all_teams = sorted(picture["AL"]["team_abbr"].tolist() + picture["NL"]["team_abbr"].tolist()) \
        if "AL" in picture and "NL" in picture else []
    if len(all_teams) >= 2:
        mcol1, mcol2 = st.columns(2)
        with mcol1:
            team_a = st.selectbox("Team A", all_teams, index=0, key="matchup_team_a")
        with mcol2:
            default_b = 1 if all_teams[0] == team_a and len(all_teams) > 1 else 0
            team_b = st.selectbox("Team B", all_teams, index=default_b, key="matchup_team_b")
        if team_a == team_b:
            st.caption("Pick two different teams.")
        else:
            season = db.get_seasons("batting")[0]
            profile_a = db.team_strength_profile(team_a, season, mtime)
            profile_b = db.team_strength_profile(team_b, season, mtime)
            if profile_a and profile_b:
                st.markdown(style.matchup_preview_html(profile_a, profile_b, teams.color_for_abbr), unsafe_allow_html=True)
            else:
                st.caption("Not enough stats for one of these teams yet.")
    else:
        st.caption("No seeding data yet.")


def _seed_lookup(seeded):
    return {int(row.seed): row for row in seeded.itertuples()}


def _pick_row(node_id, team_a, team_b):
    """Two side-by-side buttons for one series; the currently-picked team
    (if any) renders as a highlighted "primary" button. Picks live in the
    page's own ?bracket= URL param (see bracket_picks.py), not an account —
    the current pick set is written back to that param on every click, so
    the URL itself stays a live link to this exact bracket."""
    picks = st.session_state["bracket_picks"]
    current = picks.get(node_id)
    cols = st.columns(2)
    for col, team in zip(cols, (team_a, team_b)):
        with col:
            label = f"{team['seed']}. {team['abbr']} ({team['wins']}-{team['losses']})"
            if st.button(
                label, key=f"pick_{node_id}_{team['abbr']}",
                type="primary" if current == team["abbr"] else "secondary",
                use_container_width=True,
            ):
                picks[node_id] = team["abbr"]
                bracket_picks.save()
                st.rerun()
    return current


def _team_dict(row):
    return {"seed": int(row.seed), "abbr": row.team_abbr, "wins": int(row.wins), "losses": int(row.losses)}


def _predict_league(league, seeded):
    lookup = _seed_lookup(seeded)
    if len(lookup) < 6:
        st.caption(f"Not enough {league} seeding data yet.")
        return None

    st.markdown(f"**{league} Wild Card**")
    wc1 = _pick_row(f"{league}_wc_36", _team_dict(lookup[3]), _team_dict(lookup[6]))
    wc2 = _pick_row(f"{league}_wc_45", _team_dict(lookup[4]), _team_dict(lookup[5]))

    if not (wc1 and wc2):
        st.caption("Pick both Wild Card series to unlock the Division Series.")
        return None

    # Reseeding: #1 seed plays the lower-numbered (stronger) surviving
    # seed, #2 seed plays the other — same rule as the real bracket sim in
    # db.compute_playoff_odds.
    abbr_to_row = {lookup[s].team_abbr: lookup[s] for s in (3, 4, 5, 6)}
    survivors = sorted([wc1, wc2], key=lambda a: int(abbr_to_row[a].seed))
    st.markdown(f"**{league} Division Series**")
    ds1 = _pick_row(f"{league}_ds1", _team_dict(lookup[1]), _team_dict(abbr_to_row[survivors[0]]))
    ds2 = _pick_row(f"{league}_ds2", _team_dict(lookup[2]), _team_dict(abbr_to_row[survivors[1]]))

    if not (ds1 and ds2):
        st.caption("Pick both Division Series to unlock the Championship Series.")
        return None

    abbr_to_row.update({lookup[1].team_abbr: lookup[1], lookup[2].team_abbr: lookup[2]})
    st.markdown(f"**{league} Championship Series**")
    champ = _pick_row(f"{league}_cs", _team_dict(abbr_to_row[ds1]), _team_dict(abbr_to_row[ds2]))
    return champ, (abbr_to_row[champ] if champ else None)


def _render_bracket_predictor(picture):
    if "AL" in picture and "NL" in picture:
        reset_col, _ = st.columns([1, 5])
        with reset_col:
            if st.button("Reset my picks"):
                st.session_state["bracket_picks"] = {}
                bracket_picks.save()
                st.rerun()

        al_col, nl_col = st.columns(2)
        with al_col:
            al_result = _predict_league("AL", picture["AL"])
        with nl_col:
            nl_result = _predict_league("NL", picture["NL"])

        al_champ = al_result[0] if al_result else None
        nl_champ = nl_result[0] if nl_result else None
        if al_champ and nl_champ:
            al_row, nl_row = al_result[1], nl_result[1]
            st.markdown("**World Series**")
            ws_champ = _pick_row(
                "WS",
                {"seed": al_row.seed, "abbr": al_champ, "wins": int(al_row.wins), "losses": int(al_row.losses)},
                {"seed": nl_row.seed, "abbr": nl_champ, "wins": int(nl_row.wins), "losses": int(nl_row.losses)},
            )
            if ws_champ:
                color = teams.color_for_abbr(ws_champ)
                st.markdown(
                    f"<div style='margin-top:12px;padding:14px 18px;border-radius:10px;"
                    f"background-color:{color}33;border:1px solid {color};font-size:1.1rem'>"
                    f"Your predicted champion: <strong>{ws_champ}</strong> \U0001F3C6</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Finish both league championships to predict the World Series.")
    else:
        st.caption("No seeding data yet.")


if SHOW_BRACKET_FEATURES:
    _render_bracket_features(standings, playoff_odds, mtime)

style.colored_header("Playoff & World Series Odds", "batting")
merged = standings.merge(
    playoff_odds[["team_abbr", "playoff_pct", "division_pct", "wildcard_pct", "ws_pct"]],
    on="team_abbr", how="left",
)
for league, header_color in (("AL", "batting"), ("NL", "pitching")):
    league_df = merged[merged["league"] == league].sort_values(
        ["playoff_pct", "ws_pct"], ascending=[False, False],
    )
    if league_df.empty:
        continue
    st.markdown(f"**{league} — {'American' if league == 'AL' else 'National'} League**")
    display = league_df[["team_abbr", "wins", "losses", "playoff_pct", "division_pct", "wildcard_pct", "ws_pct"]].rename(
        columns={
            "team_abbr": "Team", "wins": "W", "losses": "L", "playoff_pct": "Playoff%",
            "division_pct": "Division%", "wildcard_pct": "Wildcard%", "ws_pct": "WS%",
        }
    )
    st.markdown(
        "<div style='overflow-x:auto'>" + style.playoff_odds_table(display, teams.color_for_abbr) + "</div>",
        unsafe_allow_html=True,
    )
