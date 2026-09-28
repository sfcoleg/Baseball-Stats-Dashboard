import sys
from datetime import datetime
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
    st.switch_page("views/4_Team.py")

# The bracket reseeds itself from live standings on every load (see
# db.current_playoff_picture — no stored state), so it tracks the races as
# they move rather than needing to be regenerated. It was gated off early
# in the season, when seeding shuffled nightly and was mostly noise; with
# the races now resolving it's back on. Picks made against a seeding that
# has since changed are dropped rather than trusted (see _pick_row).
SHOW_BRACKET_FEATURES = True

# The interactive predictor is gated separately from the bracket itself.
# Picking series winners only means something once the field is actually
# set — until then the seeding it's built on still moves underneath the
# picks, so a filled-in bracket half-invalidates itself overnight (see
# _pick_row, which drops picks whose matchup no longer exists). The
# postseason field locked when the regular season ended, so this is on.
SHOW_BRACKET_PREDICTOR = True

if SHOW_BRACKET_FEATURES and SHOW_BRACKET_PREDICTOR:
    bracket_picks.bootstrap()

st.title("Playoffs")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
standings = db.load_standings(mtime)
season = db.get_seasons("batting")[0]

if standings.empty:
    st.info("No standings data yet — run the ingest script.")
    st.stop()


def _team_logo(abbr):
    team_id = teams.team_id_for_abbr(abbr)
    return style.team_logo_for_season(abbr, team_id, season) if team_id else None


def _render_bracket_features(mtime):
    """The bracket + the interactive bracket predictor — split into a
    function (rather than inline top-level code) purely so the whole
    thing can be skipped with one `if SHOW_BRACKET_FEATURES:` guard
    instead of re-indenting every line by hand."""
    picture = db.current_playoff_picture(mtime)
    series_lookup = db.current_series_lookup(season, mtime)
    is_live = bool(series_lookup)
    style.colored_header("Playoff Bracket", "headliners")
    st.markdown(style.PLAYOFF_BRACKET_CSS, unsafe_allow_html=True)
    if "AL" in picture and "NL" in picture:
        # Reseeded from whatever standings the nightly refresh last wrote —
        # stamping the date makes it obvious the bracket is live rather than
        # a fixture someone drew once.
        as_of = datetime.fromtimestamp(mtime).strftime("%b %-d") if mtime else None
        if is_live:
            st.caption("Live series records" + (f" as of {as_of}." if as_of else "."))
        else:
            st.caption(
                "Seeding is recomputed from the current standings every time this page loads"
                + (f" — standings last refreshed {as_of}." if as_of else ".")
            )
        st.markdown(
            "<div style='overflow-x:auto'>"
            + style.full_playoff_bracket_html(
                picture["AL"], picture["NL"], teams.color_for_abbr, _team_logo, series_lookup,
            )
            + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("No seeding data yet.")

    st.divider()

    if SHOW_BRACKET_PREDICTOR:
        style.colored_header("Predict the Bracket", "headliners")
        if series_lookup:
            st.caption("The postseason is underway, so your bracket is locked in and being scored below.")
        else:
            st.caption(
                "Pick a winner in each series, based on today's seeding — no account needed, your picks are "
                "saved right in this page's URL, so bookmarking or sharing the link keeps your bracket. Later "
                "rounds unlock as you fill in the ones before them. Once the postseason starts, your bracket "
                "locks and starts scoring against the real results."
            )
        _render_bracket_predictor(picture, series_lookup)
        st.divider()

    style.colored_header("Matchup Preview", "batting")
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
            profile_a = db.team_strength_profile(team_a, season, mtime)
            profile_b = db.team_strength_profile(team_b, season, mtime)
            if profile_a and profile_b:
                st.markdown(style.matchup_preview_html(profile_a, profile_b, teams.color_for_abbr), unsafe_allow_html=True)
            else:
                st.caption("Not enough stats for one of these teams yet.")
    else:
        st.caption("No seeding data yet.")


def _seed_lookup(seeded):
    return {int(row["seed"]): row for _, row in seeded.iterrows()}


def _series_result(abbr_a, abbr_b, series_lookup):
    info = (series_lookup or {}).get(frozenset({abbr_a, abbr_b}))
    if not info:
        return None, None, False
    wins = info["wins"]
    text = f"{wins.get(abbr_a, 0)}-{wins.get(abbr_b, 0)}"
    return info.get("leader"), text, bool(info.get("final"))


def _make_node(node_id, row_a, row_b, picks, series_lookup):
    """One series in a user's predicted bracket: which of the two teams
    they picked, plus (once the real series has actually been played) its
    live score and whether the pick was right. `row_a`/`row_b` are seed
    rows — always the ORIGINAL seed 1-6 rows, threaded through every later
    round via _advance(), so `int(row['seed'])`/wins/losses/team_abbr are
    always present no matter how deep in the bracket this node sits."""
    pick = picks.get(node_id)
    # Seeding is recomputed from live standings on every load (pre-lock),
    # and picks come from a ?bracket= URL param, so a stale/tampered pick
    # could name a team that isn't one of this series' two participants —
    # drop it rather than let a downstream lookup misbehave.
    if pick not in (None, row_a["team_abbr"], row_b["team_abbr"]):
        pick = None
    leader, series_text, is_final = _series_result(row_a["team_abbr"], row_b["team_abbr"], series_lookup)
    correct = (pick == leader) if is_final else None
    return {
        "id": node_id, "team_a": row_a, "team_b": row_b, "pick": pick,
        "series_text": series_text, "final": is_final, "correct": correct,
    }


def _advance(node):
    """Which row the USER'S bracket sends to the next round — driven only
    by their pick, never by the real result (that's what keeps a missed
    early-round pick from silently "fixing itself" later)."""
    if node is None or node["pick"] is None:
        return None
    return node["team_a"] if node["team_a"]["team_abbr"] == node["pick"] else node["team_b"]


def _resolve_league(league, seeded, picks, series_lookup):
    """Every series in one league's predicted bracket, keyed
    wc_top/wc_bottom/ds1/ds2/cs — a later round is None until both of the
    picks it depends on are made. Division Series reseeding follows the
    real rule: the #1 seed plays the better-seeded Wild Card survivor, #2
    plays the other."""
    lookup = _seed_lookup(seeded)
    if len(lookup) < 6:
        return None
    wc_top = _make_node(f"{league}_wc_36", lookup[3], lookup[6], picks, series_lookup)
    wc_bottom = _make_node(f"{league}_wc_45", lookup[4], lookup[5], picks, series_lookup)
    wc_top_adv, wc_bottom_adv = _advance(wc_top), _advance(wc_bottom)
    ds1 = ds2 = None
    if wc_top_adv is not None and wc_bottom_adv is not None:
        survivors = sorted([wc_top_adv, wc_bottom_adv], key=lambda r: int(r["seed"]))
        ds1 = _make_node(f"{league}_ds1", lookup[1], survivors[0], picks, series_lookup)
        ds2 = _make_node(f"{league}_ds2", lookup[2], survivors[1], picks, series_lookup)
    cs = None
    ds1_adv, ds2_adv = _advance(ds1), _advance(ds2)
    if ds1_adv is not None and ds2_adv is not None:
        cs = _make_node(f"{league}_cs", ds1_adv, ds2_adv, picks, series_lookup)
    return {"wc_top": wc_top, "wc_bottom": wc_bottom, "ds1": ds1, "ds2": ds2, "cs": cs}


# Points per correctly-picked round — later rounds (fewer series, harder to
# call) are worth more, the standard shape for a bracket-pool scoring rule.
ROUND_POINTS = {"wc_top": 1, "wc_bottom": 1, "ds1": 2, "ds2": 2, "cs": 4, "ws": 8}
# Fixed regardless of how many picks are actually filled in — 2 leagues x
# (2 Wild Card + 2 Division Series + 1 Championship Series) + 1 World
# Series, at their point values above.
FULL_POSSIBLE_POINTS = sum(ROUND_POINTS[k] for k in ("wc_top", "wc_bottom", "ds1", "ds2", "cs")) * 2 + ROUND_POINTS["ws"]


def _score_bracket(al_nodes, nl_nodes, ws_node):
    earned = 0
    for nodes in (al_nodes, nl_nodes):
        if not nodes:
            continue
        for key, node in nodes.items():
            if node and node["correct"]:
                earned += ROUND_POINTS[key]
    if ws_node and ws_node["correct"]:
        earned += ROUND_POINTS["ws"]
    return earned, FULL_POSSIBLE_POINTS


def _pick_button_row(node):
    """Two side-by-side buttons for one series node; the currently-picked
    team (if any) renders as a highlighted "primary" button. Picks live in
    the page's own ?bracket= URL param (see bracket_picks.py), not an
    account — the current pick set is written back to that param on every
    click, so the URL itself stays a live link to this exact bracket."""
    if node is None:
        return
    picks = st.session_state["bracket_picks"]
    cols = st.columns(2)
    for col, row in zip(cols, (node["team_a"], node["team_b"])):
        with col:
            abbr = row["team_abbr"]
            label = f"{int(row['seed'])}. {abbr} ({int(row['wins'])}-{int(row['losses'])})"
            if st.button(
                label, key=f"pick_{node['id']}_{abbr}",
                type="primary" if node["pick"] == abbr else "secondary",
                use_container_width=True,
            ):
                picks[node["id"]] = abbr
                bracket_picks.save()
                st.rerun()


def _render_league_picker(league, nodes):
    st.markdown(f"**{league} Wild Card**")
    _pick_button_row(nodes["wc_top"])
    _pick_button_row(nodes["wc_bottom"])
    if nodes["ds1"] is None:
        st.caption("Pick both Wild Card series to unlock the Division Series.")
        return
    st.markdown(f"**{league} Division Series**")
    _pick_button_row(nodes["ds1"])
    _pick_button_row(nodes["ds2"])
    if nodes["cs"] is None:
        st.caption("Pick both Division Series to unlock the Championship Series.")
        return
    st.markdown(f"**{league} Championship Series**")
    _pick_button_row(nodes["cs"])


def _render_bracket_predictor(picture, series_lookup):
    """The predictor gets its own bracket-shaped visual (style.
    full_predictor_bracket_html) that fills in as picks are made, whether
    or not the postseason has started. Once it has (series_lookup is
    non-empty — the same signal the real bracket above uses to switch
    into "live" mode), the pick buttons disappear and the bracket becomes
    read-only: locked to whatever was picked, scored against the real
    results as they come in."""
    if "AL" not in picture or "NL" not in picture:
        st.caption("No seeding data yet.")
        return

    picks = st.session_state["bracket_picks"]
    al_nodes = _resolve_league("AL", picture["AL"], picks, series_lookup)
    nl_nodes = _resolve_league("NL", picture["NL"], picks, series_lookup)
    if al_nodes is None or nl_nodes is None:
        st.caption("Not enough seeding data yet.")
        return
    al_champ, nl_champ = _advance(al_nodes["cs"]), _advance(nl_nodes["cs"])
    ws_node = (
        _make_node("WS", al_champ, nl_champ, picks, series_lookup)
        if al_champ is not None and nl_champ is not None else None
    )

    is_locked = bool(series_lookup)
    if is_locked:
        earned, possible = _score_bracket(al_nodes, nl_nodes, ws_node)
        st.markdown(f"#### Your bracket: {earned} / {possible} points")

    st.markdown(style.PREDICTOR_BRACKET_CSS, unsafe_allow_html=True)
    st.markdown(
        "<div style='overflow-x:auto'>"
        + style.full_predictor_bracket_html(al_nodes, nl_nodes, ws_node, _team_logo)
        + "</div>",
        unsafe_allow_html=True,
    )

    if is_locked:
        st.caption("The postseason has started, so this bracket is locked in and can't be changed.")
        return

    st.divider()
    reset_col, _ = st.columns([1, 5])
    with reset_col:
        if st.button("Reset my picks"):
            st.session_state["bracket_picks"] = {}
            bracket_picks.save()
            st.rerun()

    al_col, nl_col = st.columns(2)
    with al_col:
        _render_league_picker("AL", al_nodes)
    with nl_col:
        _render_league_picker("NL", nl_nodes)

    if ws_node is not None:
        st.markdown("**World Series**")
        _pick_button_row(ws_node)
        if ws_node["pick"]:
            color = teams.color_for_abbr(ws_node["pick"])
            st.markdown(
                f"<div style='margin-top:12px;padding:14px 18px;border-radius:10px;"
                f"background-color:{color}33;border:1px solid {color};font-size:1.1rem'>"
                f"Your predicted champion: <strong>{ws_node['pick']}</strong> \U0001F3C6</div>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("Finish both league championships to predict the World Series.")


if SHOW_BRACKET_FEATURES:
    _render_bracket_features(mtime)
