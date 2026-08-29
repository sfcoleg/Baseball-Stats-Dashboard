"""Site-wide preferences — reached via the small "Settings" link at the
bottom of the sidebar (see main.py), separate from the "Glossary" link
next to it. Saved to this browser's localStorage only (see prefs.py) — same
no-accounts, per-browser model as following.py/predictions.py."""
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import following
import localstorage_bridge
import predictions
import prefs
import style
import teams

st.set_page_config(page_title="Settings | Diamond Metrics", layout="wide")
st.title("Settings")
st.caption(
    "Saved in this browser only (no account) — these preferences will be here next time you visit on "
    "this device/browser, but won't follow you to another one."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

# Fired here too (not just Home.py) so a visitor who lands directly on this
# page still sees their real saved values rather than the placeholder
# None/None from bootstrap() — see localstorage_bridge.py's docstring for
# why this can't be done from main.py.
localstorage_bridge.register("prefs", prefs.STORAGE_KEY)

style.colored_header("Defaults", "headliners")

seasons = db.get_seasons("batting")
season_options = ["Always most recent"] + [str(s) for s in seasons]
current_pref = st.session_state.get("pref_default_season")
current_index = season_options.index(str(current_pref)) if current_pref in seasons else 0
season_choice = st.selectbox(
    "Default season",
    season_options,
    index=current_index,
    help="Which season the Season dropdown starts on across Batting, Pitching, Fielding, Baserunning, "
         "Team, Compare, Awards Race, and Home — pick a specific year to stop it resetting to the "
         "current season every time.",
)
st.session_state["pref_default_season"] = None if season_choice == "Always most recent" else int(season_choice)

team_options = teams.all_teams()
team_labels = ["None"] + [f"{abbr} — {nickname}" for abbr, nickname in team_options]
current_fav = prefs.get_favorite_team()
fav_index = 0
if current_fav:
    for i, label in enumerate(team_labels):
        if label.startswith(f"{current_fav} —"):
            fav_index = i
            break
team_choice = st.selectbox(
    "Favorite team",
    team_labels,
    index=fav_index,
    help="Preselected on the Team page instead of defaulting to whichever team happens to be first "
         "alphabetically.",
)
st.session_state["pref_favorite_team"] = None if team_choice == "None" else team_choice.split(" — ")[0]

style.colored_header("Appearance", "chart")
_theme_labels = {"system": "Match my device", "light": "Light", "dark": "Dark"}
_current = prefs.theme_preference()
theme_choice = st.radio(
    "Theme", list(prefs.THEME_CHOICES), horizontal=True,
    index=list(prefs.THEME_CHOICES).index(_current),
    format_func=lambda v: _theme_labels[v],
    label_visibility="collapsed",
)
if theme_choice != _current:
    st.session_state["pref_theme"] = theme_choice
    prefs.save()
    st.rerun()
st.session_state["pref_theme"] = theme_choice
st.caption(
    "Light and Dark stay put on every page. Match my device follows your "
    "system setting, which can change as you move between pages."
)

# Persists whatever's currently in session_state to this browser's
# localStorage — cheap and safe to call unconditionally on every render
# (see prefs.py / following.py).
prefs.save()
st.caption("Saved automatically.")

style.colored_header("Following", "batting")
followed_teams = st.session_state.get("followed_teams", [])
followed_players = st.session_state.get("followed_players", [])
if followed_teams or followed_players:
    st.caption(
        f"Following {len(followed_teams)} team{'s' if len(followed_teams) != 1 else ''} and "
        f"{len(followed_players)} player{'s' if len(followed_players) != 1 else ''}."
    )
else:
    st.caption("Not following any teams or players yet.")
st.page_link("views/13_Following.py", label="Manage who you follow →")

# --- Data freshness ---------------------------------------------------------
# Tucked away on Settings rather than shown in the banner: this is a
# diagnostic you go and look at when something feels wrong, not a number
# every visitor needs on every page. It exists because the site has twice
# gone days without updating while every scheduled job still reported
# success — once because a guard crashed and the crash was misread as
# "nothing to do". This turns that from something noticed by feel into
# something checkable in a second.
style.colored_header("Data", "chart")
_freshness = db.data_freshness()
_stale = [f for f in _freshness if f.get("stale")]
_cols = st.columns(len(_freshness))
for _col, _entry in zip(_cols, _freshness):
    with _col:
        if not _entry["present"]:
            st.metric(_entry["sport"], "—")
            st.caption("No database file.")
            continue
        if _entry["refreshed"] is None:
            st.metric(_entry["sport"], "—")
            st.caption("No refresh recorded yet.")
            continue
        _days = _entry["days_ago"]
        _when = "Today" if _days == 0 else ("Yesterday" if _days == 1 else f"{_days} days ago")
        st.metric(_entry["sport"], _when)
        st.caption(_entry["refreshed"].strftime("%b %-d, %Y"))

if _stale:
    # Only ever fires for a sport judged against a daily cadence — an
    # offseason NHL or NFL database being months old is normal, not broken.
    _names = ", ".join(f["sport"] for f in _stale)
    st.warning(
        f"{_names} data hasn't refreshed in more than a day. The nightly job may have "
        f"failed — check the Actions tab on GitHub."
    )
else:
    st.caption(
        "Each sport refreshes on its own nightly schedule. NHL and NFL sit idle "
        "between seasons, so an older date there is expected rather than a problem."
    )

style.colored_header("Reset", "chart")
st.caption(
    "Clears everything saved in this browser for Diamond Metrics — followed teams/players, prediction "
    "game picks, and the defaults above. Doesn't affect anyone else or any other device."
)
if st.button("Clear all saved data on this browser", type="secondary"):
    st.session_state["followed_teams"] = []
    st.session_state["followed_players"] = []
    st.session_state["prediction_picks"] = []
    st.session_state["pref_default_season"] = None
    st.session_state["pref_favorite_team"] = None
    following.save()
    predictions.save()
    prefs.save()
    components.html(
        f"""
        <script>
        localStorage.removeItem('{following.STORAGE_KEY}');
        localStorage.removeItem('{predictions.STORAGE_KEY}');
        localStorage.removeItem('{prefs.STORAGE_KEY}');
        </script>
        """,
        height=0,
    )
    st.success("Cleared. Followed teams/players, prediction picks, and defaults are all reset.")
