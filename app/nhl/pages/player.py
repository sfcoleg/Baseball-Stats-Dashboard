"""NHL Player profile — bio + headline stats (with league percentiles) from
the NHL's own player-landing API, plus a season-by-season table from our
own ingested columns (which carry xG/CF%/GSAx that the NHL's own profile
API doesn't have). Deep-linkable via ?nhlid=<playerId>[&season=<year>]."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nhl import db as ndb
from nhl import teams as nteams

st.set_page_config(page_title="NHL Player | Diamond Metrics", layout="wide")

# Hydrates a shared link (?nhlid=...) into session_state — the sidebar
# search sets nhl_selected_playerId directly (st.switch_page doesn't
# carry query params), so a link opened fresh needs this fallback path,
# same pattern as the MLB side's _Player.py.
if "nhl_selected_playerId" not in st.session_state and "nhlid" in st.query_params:
    try:
        st.session_state["nhl_selected_playerId"] = int(st.query_params["nhlid"])
    except (TypeError, ValueError):
        pass

if "nhl_selected_playerId" not in st.session_state:
    st.title("Player")
    st.info("Use the search box in the sidebar, or open a profile from Skaters, Goalies, Team, or Standings.")
    st.stop()
player_id = st.session_state["nhl_selected_playerId"]

landing = ndb.load_player_landing(player_id)
if not landing:
    st.error("Couldn't load this player right now — the NHL's API may be temporarily down.")
    st.stop()

is_goalie = landing.get("position") == "G"
name = f"{landing['firstName']['default']} {landing['lastName']['default']}"
abbr = landing.get("currentTeamAbbrev")
color = nteams.color_for_abbr(abbr) if abbr else "#666666"

mtime = ndb.nhl_db_mtime()
career = ndb.load_goalie_career(player_id, mtime) if is_goalie else ndb.load_skater_career(player_id, mtime)
seasons_on_file = sorted(career["season"].unique().tolist(), reverse=True) if not career.empty else []

st.title(name)
h1, h2 = st.columns([1, 4])
with h1:
    if landing.get("headshot"):
        st.image(landing["headshot"], width=160)
with h2:
    st.markdown(
        f"<span style='background-color:{color}66;color:var(--dm-text);padding:3px 12px;border-radius:8px;"
        f"font-weight:700'>{abbr or 'Free Agent'}</span> "
        f"<span style='color:var(--dm-dim)'>#{landing.get('sweaterNumber', '—')} · {landing.get('position', '')} · "
        f"Shoots/Catches {landing.get('shootsCatches', '—')}</span>",
        unsafe_allow_html=True,
    )
    bio_bits = []
    if landing.get("birthDate"):
        bio_bits.append(f"Born {landing['birthDate']}"
                         f" in {(landing.get('birthCity') or {}).get('default', '')}, {landing.get('birthCountry', '')}")
    if landing.get("heightInInches"):
        ft, inch = divmod(int(landing["heightInInches"]), 12)
        bio_bits.append(f"{ft}'{inch}\" · {landing.get('weightInPounds', '—')} lb")
    draft = landing.get("draftDetails")
    if draft:
        bio_bits.append(f"Drafted {draft['year']} Rd {draft['round']}, Pick {draft['overallPick']} ({draft.get('teamAbbrev', '')})")
    else:
        bio_bits.append("Undrafted")
    st.caption(" · ".join(bio_bits))

st.divider()

# --- Headline stats for a selected season, with league percentiles -----
if seasons_on_file:
    default_idx = 0
    q_season = st.query_params.get("season")
    if q_season and int(q_season) in seasons_on_file:
        default_idx = seasons_on_file.index(int(q_season))
    season = st.selectbox("Season", seasons_on_file, index=default_idx, format_func=ndb.season_label)
    row = career[career["season"] == season].iloc[0]

    if is_goalie:
        pool = ndb.load_goalies(season, mtime)
        pool = pool[pool["gamesPlayed"] >= 10]
        gsax = row["xGA"] - row["goalsAgainst"] if pd.notna(row.get("xGA")) else None
        cards = [
            ("Record", f"{int(row['wins'])}-{int(row['losses'])}-{int(row['otLosses'])}", None),
            ("GAA", f"{row['goalsAgainstAverage']:.2f}", ndb.percentile_rank(pool["goalsAgainstAverage"], row["goalsAgainstAverage"], lower_is_better=True)),
            ("SV%", f"{row['savePct']:.1f}", ndb.percentile_rank(pool["savePct"], row["savePct"])),
            ("Shutouts", int(row["shutouts"]), ndb.percentile_rank(pool["shutouts"], row["shutouts"])),
            ("GSAx", f"{gsax:+.1f}" if gsax is not None else "—",
             ndb.percentile_rank(pool["xGA"] - pool["goalsAgainst"], gsax) if gsax is not None else None),
        ]
    else:
        pos_group = ["C", "L", "R"] if row.get("positionCode") in ("C", "L", "R") else ["D"]
        pool = ndb.load_skaters(season, mtime)
        pool = pool[(pool["gamesPlayed"] >= 20) & (pool["positionCode"].isin(pos_group))]
        finishing = row["goals"] - row["ixG"] if pd.notna(row.get("ixG")) else None
        cards = [
            ("GP", int(row["gamesPlayed"]), None),
            ("Points", int(row["points"]), ndb.percentile_rank(pool["points"], row["points"])),
            ("Goals", int(row["goals"]), ndb.percentile_rank(pool["goals"], row["goals"])),
            ("Assists", int(row["assists"]), ndb.percentile_rank(pool["assists"], row["assists"])),
            ("xG", f"{row['ixG']:.1f}" if pd.notna(row.get("ixG")) else "—",
             ndb.percentile_rank(pool["ixG"], row.get("ixG")) if pd.notna(row.get("ixG")) else None),
            ("CF%", f"{row['satPercentage']:.1f}" if pd.notna(row.get("satPercentage")) else "—",
             ndb.percentile_rank(pool["satPercentage"], row.get("satPercentage")) if pd.notna(row.get("satPercentage")) else None),
        ]
        st.caption(f"Percentiles vs. {'forwards' if pos_group != ['D'] else 'defensemen'} with 20+ GP in {ndb.season_label(season)}.")

    stat_cols = st.columns(len(cards))
    for col, (label, value, pct) in zip(stat_cols, cards):
        col.metric(label, value, delta=(f"{pct}th pctile" if pct is not None else None), delta_color="off")

    st.divider()

    # --- Season-by-season (our own ingested columns) --------------------
    style.colored_header("Season by Season", "batting" if not is_goalie else "pitching")
    career_display = career.sort_values("season", ascending=False).copy()
    career_display["Season"] = career_display["season"].map(ndb.season_label)
    career_display["Tm"] = career_display["teamAbbrevs"].map(nteams._primary)
    if is_goalie:
        career_display["GSAx"] = career_display["xGA"] - career_display["goalsAgainst"]
        cols = ["Season", "Tm", "gamesPlayed", "wins", "losses", "otLosses", "goalsAgainstAverage",
                "savePct", "shutouts", "GSAx"]
    else:
        career_display["finishing"] = career_display["goals"] - career_display["ixG"]
        cols = ["Season", "Tm", "gamesPlayed", "goals", "assists", "points", "plusMinus", "ixG",
                "finishing", "satPercentage", "hits", "blockedShots"]
    ndb.STAT_LABELS.setdefault("finishing", "G − xG")
    ndb.STAT_LABELS.setdefault("GSAx", "GSAx")
    present = [c for c in cols if c in career_display.columns]
    st.dataframe(
        career_display[present].rename(columns=ndb.STAT_LABELS),
        use_container_width=True, hide_index=True,
    )
else:
    st.info("No seasons on file for this player yet in our database.")

# --- Awards --------------------------------------------------------------
awards = landing.get("awards") or []
if awards:
    style.colored_header("Awards", "fielding")
    for a in awards:
        trophy = a["trophy"]["default"]
        years = ", ".join(str(s["seasonId"])[:4] for s in a.get("seasons", []))
        st.markdown(f"**{trophy}** — {years}")
