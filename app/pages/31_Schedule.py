"""Schedule — the league-wide week ahead: every upcoming game with probable
starters and our model's odds, plus the pitching duels worth circling.
Today's Games covers today in depth; this is the forward view."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Schedule | Diamond Metrics", layout="wide")
st.title("Schedule")
if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
season = db.get_seasons("pitching")[0]
pitching = db.load_pitching(season, mtime)

with st.spinner("Loading the week ahead..."):
    upcoming = db.load_upcoming_games(7)

if upcoming.empty:
    st.info("No upcoming games found — the schedule API may be unavailable right now.")
    st.stop()

# Only genuinely upcoming (skip today's already-live/final games).
upcoming = upcoming[upcoming["status"] == "Preview"]

era_by_id = dict(zip(pitching["mlbID"], pitching["ERA"]))
gs_by_id = dict(zip(pitching["mlbID"], pitching["GS"]))


def team_logo(abbr):
    team_id = teams.team_id_for_abbr(teams.normalize_mlb_abbr(abbr))
    return style.team_logo_for_season(teams.normalize_mlb_abbr(abbr), team_id, season) if team_id else None


def _logo_img(abbr, size=22):
    logo = team_logo(abbr)
    return (
        f"<img src='{logo}' style='height:{size}px;width:{size}px;object-fit:contain;"
        f"vertical-align:middle;margin-right:4px'>" if logo else ""
    )


def _sp_line(name, pid):
    # NaN (a float) is truthy, so a plain `if not name` lets pandas' missing
    # values through and renders a literal "nan".
    if not isinstance(name, str) or not name:
        return "TBD"
    era = era_by_id.get(int(pid)) if pd.notna(pid) else None
    return f"{name} ({era:.2f} ERA)" if era is not None and pd.notna(era) else name


# --- Duels to watch ---------------------------------------------------------
duels = upcoming.dropna(subset=["away_pitcher_mlbID", "home_pitcher_mlbID"]).copy()
if not duels.empty:
    duels["away_era"] = duels["away_pitcher_mlbID"].map(era_by_id)
    duels["home_era"] = duels["home_pitcher_mlbID"].map(era_by_id)
    # Real starters only (3+ starts) with real ERAs, both good.
    duels = duels.dropna(subset=["away_era", "home_era"])
    duels = duels[
        (duels["away_pitcher_mlbID"].map(gs_by_id).fillna(0) >= 3)
        & (duels["home_pitcher_mlbID"].map(gs_by_id).fillna(0) >= 3)
    ]
    duels["combined_era"] = duels["away_era"] + duels["home_era"]
    duels = duels[(duels["away_era"] <= 3.80) & (duels["home_era"] <= 3.80)].sort_values("combined_era")

if not duels.empty:
    style.colored_header("Duels to Watch", "headliners")
    for _, g in duels.head(5).iterrows():
        away_color = teams.color_for_abbr(g["away_abbr"])
        home_color = teams.color_for_abbr(g["home_abbr"])
        st.markdown(
            f"<div style='background-color:var(--dm-surface-mute);border-left:4px solid var(--dm-amber);padding:8px 14px;"
            f"border-radius:6px;margin:5px 0'>"
            f"<span style='color:var(--dm-dim);font-size:0.85rem'>{g['date']}</span><br>"
            f"{_logo_img(g['away_abbr'])}"
            f"<span style='background-color:{away_color}66;color:var(--dm-text);padding:2px 8px;border-radius:6px;"
            f"font-weight:700'>{g['away_abbr']}</span> "
            f"<b>{_sp_line(g['away_pitcher_name'], g['away_pitcher_mlbID'])}</b>"
            f" <span style='color:var(--dm-dim)'>vs</span> "
            f"{_logo_img(g['home_abbr'])}"
            f"<span style='background-color:{home_color}66;color:var(--dm-text);padding:2px 8px;border-radius:6px;"
            f"font-weight:700'>{g['home_abbr']}</span> "
            f"<b>{_sp_line(g['home_pitcher_name'], g['home_pitcher_mlbID'])}</b>"
            f"</div>",
            unsafe_allow_html=True,
        )

# --- Day-by-day grid --------------------------------------------------------
for date_str, day_games in upcoming.groupby("date", sort=True):
    pretty = pd.to_datetime(date_str).strftime("%A, %B %-d")
    style.colored_header(pretty, "batting")
    for _, g in day_games.sort_values("game_time_utc").iterrows():
        pred = db.predict_game(g, mtime)
        away_color = teams.color_for_abbr(g["away_abbr"])
        home_color = teams.color_for_abbr(g["home_abbr"])
        odds_bit = ""
        if pred:
            fav_abbr = g["home_abbr"] if pred["home_prob"] >= 0.5 else g["away_abbr"]
            fav_prob = max(pred["home_prob"], pred["away_prob"])
            odds_bit = (
                f"<span style='color:var(--dm-dim);font-size:0.85rem;white-space:nowrap'>"
                f"{fav_abbr} {fav_prob * 100:.0f}%</span>"
            )
        st.markdown(
            f"<div style='background-color:var(--dm-surface-mute);padding:8px 14px;border-radius:6px;margin:4px 0;"
            f"display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap'>"
            f"<div style='min-width:0'>"
            f"{_logo_img(g['away_abbr'])}"
            f"<span style='background-color:{away_color}66;color:var(--dm-text);padding:2px 8px;border-radius:6px;"
            f"font-weight:700'>{g['away_abbr']}</span>"
            f" <span style='color:var(--dm-dim)'>@</span> "
            f"{_logo_img(g['home_abbr'])}"
            f"<span style='background-color:{home_color}66;color:var(--dm-text);padding:2px 8px;border-radius:6px;"
            f"font-weight:700'>{g['home_abbr']}</span>"
            f" <span class='game-time-local' data-utc='{g['game_time_utc']}' "
            f"style='color:var(--dm-dim);font-size:0.85rem'></span>"
            f"<div style='color:var(--dm-text);font-size:0.88rem;margin-top:2px'>"
            f"{_sp_line(g['away_pitcher_name'], g['away_pitcher_mlbID'])} "
            f"<span style='color:var(--dm-dim)'>vs</span> "
            f"{_sp_line(g['home_pitcher_name'], g['home_pitcher_mlbID'])}</div>"
            f"</div>"
            f"{odds_bit}"
            f"</div>",
            unsafe_allow_html=True,
        )

# Localize game times to the viewer's clock — same data-utc pattern as the
# Team page's schedule table (the server can't know the browser's timezone).
components.html(
    """
    <script>
    (function() {
        const els = window.parent.document.querySelectorAll('.game-time-local[data-utc]');
        els.forEach(function(el) {
            const d = new Date(el.dataset.utc);
            if (isNaN(d.getTime())) return;
            el.textContent = '· ' + d.toLocaleTimeString([], {weekday: undefined, hour: 'numeric', minute: '2-digit'});
        });
    })();
    </script>
    """,
    height=0,
)
