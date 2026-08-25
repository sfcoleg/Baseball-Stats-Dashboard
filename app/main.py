"""Real entry point for the app (run via `streamlit run app/main.py`, not
Home.py directly). Uses st.navigation()/st.Page() instead of Streamlit's
classic pages/-folder auto-discovery, specifically so:
  1. The sidebar search box can render ABOVE the page nav. Neither the
     classic system nor st.navigation()'s own auto-rendered menu (position=
     "sidebar") support this — both always claim the very top of the
     sidebar regardless of script call order. The fix is position="hidden"
     (suppresses the automatic menu entirely) plus building the nav links
     ourselves with st.sidebar.page_link(), placed after the search box.
  2. The hidden player-profile page (pages/_Player.py) can be fully
     excluded from the visible menu simply by not creating a page_link for
     it — it's still registered as a valid destination (it's in the list
     passed to st.navigation()), just not listed as a clickable link, so
     st.switch_page() still works. The classic system has no equivalent
     control (an underscore-prefixed filename does NOT hide a page from
     nav there, despite old docs/folklore suggesting it does).
"""
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

sys.path.append(str(Path(__file__).resolve().parent))
import db
import following
import localstorage_bridge
import predictions
import prefs
import sidebar
import style

st.set_page_config(page_title="Diamond Metrics", layout="wide",
                   initial_sidebar_state="collapsed")

# Seeds st.session_state's follow lists from the browser's own localStorage
# (see following.py) — must run before any page can read them. Each
# bootstrap() only reads whatever ?param= is already in the URL; it does
# NOT fire the actual localStorage->query-param redirect itself (see
# localstorage_bridge.py's register()/redirect()) — that has to be called
# from WITHIN a routed page's own script (see e.g. pages/13_Following.py
# and pages/8_Todays_Games.py), not from here. Empirically, anything
# main.py components.html()'s outside of pg.run()'s execution — before OR
# after it — never actually executes its script in the browser; only
# components.html calls made from inside the routed page itself reliably
# run. register() itself is just plain Python (no rendering), so it's safe
# to call here regardless.
following.bootstrap()
localstorage_bridge.register("following", following.STORAGE_KEY)
# Same localStorage pattern for the prediction game's picks (see
# predictions.py) — must also run before Today's Games can read them.
predictions.bootstrap()
localstorage_bridge.register("predictions", predictions.STORAGE_KEY)
# Same pattern again for site-wide preferences (default season, favorite
# team — see prefs.py). Unlike following/predictions, prefs are read by
# nearly every page, so the actual redirect() fires from Home.py (the
# default landing page) as well as the Settings page itself, rather than
# just one dedicated page.
prefs.bootstrap()
localstorage_bridge.register("prefs", prefs.STORAGE_KEY)
# The bracket predictor's picks (see bracket_picks.py) are URL-based, not
# localStorage-based, so unlike following.py/predictions.py that module's
# bootstrap() only needs to run on the Playoffs page itself, not globally here.

# Logo + title header — rendered once here (not per-page) so it shows up on
# every page. Streamlit's own toolbar (hamburger menu / Deploy button) is an
# opaque bar pinned to the very top of the viewport; rather than push our
# header below it (leaving it lower than the toolbar's own icons), this
# places the logo/title INSIDE that same top strip via position:fixed, at
# the same height as the Deploy button and the sidebar's Player Search box.
# Design tokens. Every hand-written bit of HTML on the site (badges, cards,
# tables, stat lines) used to hardcode dark-theme hexes, which meant the app
# could never be anything but dark. Those are now var(--dm-*) references
# resolved here, so both themes come from one place.
#
# Which set to emit comes from st.context.theme, NOT a prefers-color-scheme
# media query. Streamlit's active theme and the OS preference can disagree —
# a visitor on a dark OS who picks Light in Streamlit's own menu was getting
# a light page with dark cards on it, because the media query still matched.
# st.context.theme.type reports the theme Streamlit actually painted.
_THEME_TOKENS = {
    "light": (
        "--dm-text:#0C1725; --dm-dim:#6B7C94; --dm-line:#D8E1EE;"
        "--dm-surface:#F7FAFD; --dm-surface-mute:#E9EEF6; --dm-card:#F2F7FD;"
        "--dm-blue:#2E86DE; --dm-blue-text:#1B5FA8; --dm-blue-soft:#E7F1FC;"
        "--dm-amber:#B7791F; --dm-amber-soft:#FBF0DA;"
        "--dm-red:#C0453F; --dm-red-soft:#FBE9E8;"
        "--dm-green:#2E7D32; --dm-green-soft:#E6F4E7;"
    ),
    "dark": (
        "--dm-text:#EFF3F9; --dm-dim:#9AA8BD; --dm-line:#2E3B4E;"
        "--dm-surface:#1E2735; --dm-surface-mute:#151C28; --dm-card:#1E2735;"
        "--dm-blue:#6FAFE8; --dm-blue-text:#9BCAF3; --dm-blue-soft:#22334A;"
        "--dm-amber:#F5B942; --dm-amber-soft:#3A2F16;"
        "--dm-red:#F87171; --dm-red-soft:#3A1F1F;"
        "--dm-green:#7CFC9A; --dm-green-soft:#16301C;"
    ),
}
_theme_obj = getattr(getattr(st, "context", None), "theme", None)
_theme_type = getattr(_theme_obj, "type", None) or "light"
st.markdown(
    f"<style>:root{{{_THEME_TOKENS.get(_theme_type, _THEME_TOKENS['light'])}}}</style>",
    unsafe_allow_html=True,
)

# Component styling — the visual language from the design studies, applied
# once here so every page inherits it rather than each re-inventing a card.
# Streamlit's own containers/metrics are restyled in place; anything we hand-
# write (section headings, game cards) gets a dm-* class. The raised-card
# shadow is light-theme only — on a dark ground it just muddies the edge.
_CARD_SHADOW = "box-shadow:0 1px 2px rgba(12,23,37,0.06);" if _theme_type == "light" else ""
st.markdown(
    "<style>"
    # --- section headings: accent kicker + condensed uppercase title -------
    ".dm-shead{display:flex;align-items:center;gap:12px;margin:2.1rem 0 1rem;}"
    ".dm-kick{width:26px;height:4px;border-radius:2px;flex:0 0 auto;}"
    ".dm-stitle{font-family:'Archivo Narrow',sans-serif;font-weight:700;"
    "  font-size:1.5rem;letter-spacing:0.6px;text-transform:uppercase;line-height:1.1;}"
    # --- headings + numerals: condensed, tight, tabular --------------------
    "h1,h2,h3{font-family:'Archivo Narrow',sans-serif !important;letter-spacing:-0.2px;}"
    "h1{text-transform:uppercase;letter-spacing:0.5px;}"
    "[data-testid='stMain']{font-variant-numeric:tabular-nums;}"
    # --- bordered containers read as cards, not outlines -------------------
    "[data-testid='stMain'] [data-testid='stVerticalBlockBorderWrapper']{"
    f"  background:var(--dm-surface);border-radius:12px;{_CARD_SHADOW}}}"
    # --- game cards: left rail, condensed team names, big score ------------
    ".dm-game{flex:0 0 auto;width:176px;background:var(--dm-card);"
    "  border-left:4px solid var(--dm-blue);border-radius:0 10px 10px 0;"
    f"  padding:11px 14px;margin-right:10px;{_CARD_SHADOW}}}"
    ".dm-game .dm-stat{font-size:0.64rem;letter-spacing:1.1px;text-transform:uppercase;"
    "  color:var(--dm-dim);margin-bottom:8px;}"
    ".dm-game .dm-team{font-family:'Archivo Narrow',sans-serif;font-weight:600;"
    "  font-size:0.95rem;color:var(--dm-dim);}"
    ".dm-game .dm-row.win .dm-team{color:var(--dm-text);font-weight:700;}"
    ".dm-game .dm-score{font-family:'Archivo Narrow',sans-serif;font-weight:700;"
    "  font-size:1.35rem;color:var(--dm-dim);}"
    ".dm-game .dm-row.win .dm-score{color:var(--dm-blue);}"
    # --- metrics: the oversized-numeral treatment --------------------------
    "[data-testid='stMetricValue']{font-family:'Archivo Narrow',sans-serif;"
    "  font-weight:700;letter-spacing:-0.5px;}"
    "[data-testid='stMetricLabel']{text-transform:uppercase;letter-spacing:0.9px;"
    "  font-size:0.7rem !important;color:var(--dm-dim);}"
    # --- full-width top navigation ----------------------------------------
    ".dm-topnav{position:fixed;top:0;left:0;right:0;z-index:999990;"
    "  display:flex;align-items:center;gap:16px;height:3.2rem;padding:0 16px;"
    "  background:var(--dm-surface);border-bottom:2px solid var(--dm-blue);"
    "  overflow-x:auto;scrollbar-width:none;}"
    ".dm-topnav::-webkit-scrollbar{display:none;}"
    ".dm-brand{display:flex;align-items:center;gap:8px;flex:0 0 auto;text-decoration:none;}"
    ".dm-brand .diamond-title{font-size:1.05rem !important;line-height:1 !important;}"
    ".dm-sportwrap{display:flex;gap:4px;flex:0 0 auto;}"
    ".dm-sport{font-family:'Archivo Narrow',sans-serif;font-weight:700;font-size:0.82rem;"
    "  letter-spacing:0.5px;padding:4px 10px;border-radius:7px;text-decoration:none;"
    "  color:var(--dm-dim);border:1px solid var(--dm-line);white-space:nowrap;}"
    ".dm-sport.active{background:var(--dm-blue-soft);color:var(--dm-blue-text);"
    "  border-color:var(--dm-blue);}"
    ".dm-navlinks{display:flex;align-items:center;gap:2px;flex:1 1 auto;white-space:nowrap;}"
    ".dm-nav-link{font-family:'Archivo Narrow',sans-serif;font-weight:600;font-size:0.92rem;"
    "  letter-spacing:0.4px;text-transform:uppercase;text-decoration:none;color:var(--dm-dim);"
    "  padding:6px 10px;border-radius:7px;border-bottom:3px solid transparent;}"
    ".dm-nav-link:hover{color:var(--dm-text);background:var(--dm-surface-mute);}"
    ".dm-nav-link.active{color:var(--dm-text);border-bottom-color:var(--dm-blue);}"
    ".dm-nav-util{font-size:0.76rem;color:var(--dm-dim);text-decoration:none;flex:0 0 auto;"
    "  opacity:0.75;}"
    ".dm-nav-util:hover{opacity:1;}"
    # The bar is fixed, so the page needs to start below it.
    "[data-testid='stMainBlockContainer']{padding-top:3.6rem !important;}"
    "@media (max-width:640px){.dm-topnav{height:3rem;}"
    "  .dm-nav-link{font-size:0.85rem;padding:5px 8px;}}"
    # --- tables ------------------------------------------------------------
    "[data-testid='stMain'] table{border-collapse:collapse;}"
    "[data-testid='stMain'] table th{font-family:'Archivo Narrow',sans-serif;"
    "  text-transform:uppercase;letter-spacing:0.8px;font-size:0.7rem;color:var(--dm-dim);}"
    "</style>",
    unsafe_allow_html=True,
)

HEADER_HEIGHT = "2.5rem"
st.markdown(
    "<style>"
    "@import url('https://fonts.googleapis.com/css2?family=Russo+One&display=swap');"
    ".diamond-title {"
    "  font-family: 'Russo One', sans-serif !important;"
    "  font-weight: 400 !important;"
    "  font-size: 1.6rem !important;"
    "  line-height: 1.6rem !important;"
    "  letter-spacing: 1px;"
    "  margin: 0 !important;"
    f"  color: {'#9BCAF3' if _theme_type == 'dark' else style.DIAMOND_COLOR} !important;"
    "  text-shadow: none;"
    "}"
    ".diamond-header {"
    f"  position: fixed; top: 0; left: 0; height: {HEADER_HEIGHT}; z-index: 999995;"
    "  display: flex; align-items: center; gap: 8px; padding-left: 14px;"
    "  transition: left 0.2s ease, padding-left 0.2s ease;"
    "}"
    f"[data-testid='stHeader'] {{ height: {HEADER_HEIGHT}; }}"
    # When the sidebar is collapsed, it stops reserving its 230px column
    # (see the [aria-expanded='true']-scoped width rule below), so the
    # header needs to reclaim that freed space too instead of leaving a
    # 230px dead gap on the left — same idea as the mobile override, just
    # triggered by the collapse state rather than viewport width. The
    # sidebar and header aren't direct siblings in the DOM (a couple of
    # Streamlit's own wrapper divs sit between them), but they do share a
    # common ancestor close enough for a general-sibling-plus-descendant
    # selector to reach across. padding-left has to clear Streamlit's own
    # floating "expand sidebar" arrow (stExpandSidebarButton), which sits at
    # roughly 18-46px from the left edge whenever the sidebar is collapsed —
    # anything smaller than that visually stacks the diamond logo right on
    # top of it.
    "[data-testid='stSidebar'][aria-expanded='false'] ~ div .diamond-header {"
    "  left: 0 !important; padding-left: 3.5rem !important;"
    "}"
    # Mobile: Streamlit's sidebar becomes an off-canvas overlay below this
    # width rather than a permanent 230px column, so the desktop offset
    # above (left: 230px, padding-left: 4.5rem — pushing the header clear
    # of the sidebar AND its own collapse arrow) leaves nothing but empty
    # space on a phone and shoves the logo/title towards the right edge.
    # Anchor to the left edge instead and shrink both down to fit. Still
    # needs the same 3.5rem clearance as the desktop collapsed case above
    # when the sidebar itself is collapsed — a flat 0.75rem here used to
    # override that rule (this media query comes later in the stylesheet)
    # and land the logo right on top of the floating expand arrow.
    "@media (max-width: 640px) {"
    "  .diamond-header { left: 0 !important; gap: 6px !important; }"
    "  [data-testid='stSidebar'][aria-expanded='true'] ~ div .diamond-header { padding-left: 0.75rem !important; }"
    "  [data-testid='stSidebar'][aria-expanded='false'] ~ div .diamond-header { padding-left: 3.5rem !important; }"
    "  .diamond-logo svg { width: 20px !important; height: 20px !important; }"
    "  .diamond-title { font-size: 1.05rem !important; line-height: 1.05rem !important; }"
    "}"
    "</style>",
    unsafe_allow_html=True,
)

# Micro-animations — a subtle entrance for every bordered card/container
# (headliner cards, game cards, milestone cards, etc.) and a pulsing glow
# for the "LIVE" badges on Today's Games/Following, applied globally here
# so individual pages don't need their own animation CSS.
st.markdown(
    "<style>"
    "@keyframes diamondFadeInUp { from { opacity: 0; transform: translateY(8px); } "
    "  to { opacity: 1; transform: translateY(0); } }"
    "[data-testid='stVerticalBlockBorderWrapper'] {"
    "  animation: diamondFadeInUp 0.35s ease-out;"
    "  transition: transform 0.15s ease, box-shadow 0.15s ease;"
    "}"
    "[data-testid='stVerticalBlockBorderWrapper']:hover {"
    "  transform: translateY(-2px); box-shadow: 0 4px 14px rgba(0,0,0,0.25);"
    "}"
    "@keyframes diamondLivePulse {"
    "  0%, 100% { box-shadow: 0 0 0 0 rgba(211,47,47,0.55); }"
    "  50% { box-shadow: 0 0 0 6px rgba(211,47,47,0); }"
    "}"
    ".live-badge { animation: diamondLivePulse 1.6s ease-in-out infinite; }"
    # Today's Games' "+N" run-scored flash (see style.run_scored_badge_html)
    # — pops in next to the score with a little overshoot, holds, then
    # flies sideways by --fly-x (set per-instance, positive = rightward)
    # while shrinking away, landing right as the score digit itself
    # (.score-pop, same duration so their timelines stay in sync) peaks its
    # own scale-up — the two together read as the run "jumping into" the
    # score. forwards keeps the badge at its final (invisible) state
    # rather than snapping back to frame 0 once the animation completes,
    # so it doesn't flicker back into view while sitting in the DOM
    # waiting for the next fragment rerun to either replace or drop it.
    "@keyframes diamondRunFlyIn {"
    "  0% { transform: scale(0.5) translateX(0); opacity: 0; }"
    "  25% { transform: scale(1.2) translateX(0); opacity: 1; }"
    "  55% { transform: scale(1) translateX(0); opacity: 1; }"
    "  100% { transform: scale(0.3) translateX(var(--fly-x)); opacity: 0; }"
    "}"
    ".run-scored-badge {"
    "  display:inline-flex; align-items:center; justify-content:center;"
    "  width:22px; height:22px; border-radius:50%; vertical-align:middle;"
    "  animation: diamondRunFlyIn 0.9s cubic-bezier(.34,1.56,.64,1) forwards;"
    "  font-weight:800; font-size:0.75rem; margin:0 4px;"
    "}"
    "@keyframes diamondScorePop {"
    "  0%, 55% { transform: scale(1); }"
    "  75% { transform: scale(1.3); }"
    "  100% { transform: scale(1); }"
    "}"
    ".score-pop { display:inline-block; animation: diamondScorePop 0.9s ease-out; }"
    "</style>",
    unsafe_allow_html=True,
)



# Shrink the sidebar's built-in header bar (which only holds the collapse
# arrow) so the search box sits higher, closer to the top of the sidebar.
# Also narrows the sidebar itself (min/max-width pinned to override its
# default draggable-resize width) — but ONLY while expanded. Pinning the
# width unconditionally (including while collapsed) fights Streamlit's own
# collapse mechanism: it slides the sidebar off-screen with a translateX
# transform sized to its width, and our forced max-width clamped that
# computation, leaving the transform stuck at -230px even after clicking
# the button to re-expand (aria-expanded correctly flipped back to "true",
# but the sidebar never visually slid back into view). Scoping to
# [aria-expanded="true"] leaves Streamlit's own collapsed-state math alone,
# so the expand button actually works. No border/divider — the sidebar
# shares the same background color as the rest of the site (see
# config.toml), so there's nothing to visually separate it from the main
# content anymore.
st.markdown(
    "<style>"
    "[data-testid='stSidebarHeader'] { height: 1.5rem; }"
    "[data-testid='stSidebar'][aria-expanded='true'] { min-width: 230px; max-width: 230px; }"
    "</style>",
    unsafe_allow_html=True,
)

# Site-wide mobile pass — everything here was sized for a wide desktop
# layout (Streamlit's own default heading sizes, plus this app's custom
# stat badges/cards), which reads as oversized once a phone shrinks
# everything else around it down to a ~375-430px viewport. Scoped to a
# single breakpoint so desktop is untouched.
st.markdown(
    "<style>"
    "@media (max-width: 640px) {"
    "  [data-testid='stMainBlockContainer'] { padding-left: 1rem !important; padding-right: 1rem !important; }"
    "  h1 { font-size: 1.5rem !important; }"
    "  h2 { font-size: 1.25rem !important; }"
    "  h3 { font-size: 1.05rem !important; }"
    "  [data-testid='stMetricValue'] { font-size: 1.3rem !important; }"
    "  [data-testid='stMetricLabel'] { font-size: 0.8rem !important; }"
    "}"
    "</style>",
    unsafe_allow_html=True,
)

# Count-up animation for every st.metric value (percentile badges on the
# Player page, R²/MAE on Research, etc.) — parses the leading number out of
# the rendered text, animates it from 0, and restores the original
# prefix/suffix/decimal precision so formatted values like "3.680 ERA"
# still land on the exact right text, not a rounded/truncated one.
components.html(
    """
    <script>
    (function() {
        function animateValue(el) {
            if (el.dataset.diamondAnimated) return;
            const raw = el.textContent.trim();
            const match = raw.match(/-?[\\d,]+\\.?\\d*/);
            if (!match) return;
            const numStr = match[0];
            const target = parseFloat(numStr.replace(/,/g, ''));
            if (isNaN(target)) return;
            el.dataset.diamondAnimated = '1';
            const prefix = raw.slice(0, match.index);
            const suffix = raw.slice(match.index + numStr.length);
            const decimals = (numStr.split('.')[1] || '').length;
            const duration = 500;
            const start = performance.now();
            function frame(now) {
                const p = Math.min((now - start) / duration, 1);
                const eased = 1 - Math.pow(1 - p, 3);
                const current = (target * eased).toLocaleString(undefined, {
                    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
                });
                el.textContent = prefix + current + suffix;
                if (p < 1) requestAnimationFrame(frame);
                else el.textContent = raw;
            }
            requestAnimationFrame(frame);
        }
        function scan() {
            window.parent.document.querySelectorAll('[data-testid="stMetricValue"]').forEach(animateValue);
        }
        scan();
        new MutationObserver(scan).observe(window.parent.document.body, {childList: true, subtree: true});
    })();
    </script>
    """,
    height=0,
)

# Free agency is an offseason feature — irrelevant (and a little confusing,
# since "unattached" reads oddly for a guy who's mid-season on a roster)
# while the season's actually being played. Flip this to True once the
# regular season wraps up, and back to False again once free agents start
# signing in bulk and pennant races take back over.
SHOW_FREE_AGENCY = False
st.session_state["_show_free_agency"] = SHOW_FREE_AGENCY  # read by pages/34_Other.py

PAGES = [
    st.Page("Home.py", title="Home", default=True),
    st.Page("pages/12_Daily_Digest.py", title="Daily Digest"),
    st.Page("pages/13_Following.py", title="Following"),
    st.Page("pages/1_Batting.py", title="Batting"),
    st.Page("pages/2_Pitching.py", title="Pitching"),
    st.Page("pages/3_Fielding.py", title="Fielding"),
    st.Page("pages/6_Baserunning.py", title="Baserunning"),
    st.Page("pages/4_Team.py", title="Team"),
    st.Page("pages/5_Compare.py", title="Compare"),
    st.Page("pages/8_Todays_Games.py", title="Today's Games"),
    st.Page("pages/31_Schedule.py", title="Schedule"),
    st.Page("pages/9_Standings.py", title="Standings"),
    st.Page("pages/17_Playoffs.py", title="Playoffs"),
    st.Page("pages/34_Other.py", title="Other"),
    # Everything below is reached through the Other hub page above, not its
    # own sidebar slot — still registered here (so their URLs/page_links
    # resolve), just excluded from the main nav loop below.
    st.Page("pages/30_League_Trends.py", title="League Trends"),
    st.Page("pages/33_Ballparks.py", title="Ballparks"),
    st.Page("pages/23_Umpires.py", title="Umpires"),
    st.Page("pages/29_Around_the_League.py", title="Around the League"),
    st.Page("pages/18_Minor_Leagues.py", title="Minor Leagues"),
    st.Page("pages/22_Box_Score_Search.py", title="Box Score Search"),
    st.Page("pages/25_Glossary.py", title="Glossary"),  # linked separately below, not in the main nav loop
    st.Page("pages/26_Settings.py", title="Settings"),  # same — its own small button, not in the main nav loop
    st.Page("pages/_Player.py", title="Player"),  # deliberately no page_link below -> not shown in nav
    st.Page("pages/_Game_Detail.py", title="Game Center"),  # same — reached only via Today's Games' button
]
if SHOW_FREE_AGENCY:
    PAGES.insert(-1, st.Page("pages/21_Free_Agency.py", title="Free Agency"))

# NHL pages live under url_paths starting with "nhl" — that prefix is how
# the active sport is derived (from the URL, so deep links and bookmarks
# always land in the right sport with the right sidebar). Phase 0: just a
# placeholder home; the real page set slots in here as it's built.
NHL_PAGES = [
    st.Page("nhl/pages/home.py", title="NHL Home", url_path="nhl"),
    st.Page("nhl/pages/skaters.py", title="NHL Skaters", url_path="nhl-skaters"),
    st.Page("nhl/pages/goalies.py", title="NHL Goalies", url_path="nhl-goalies"),
    st.Page("nhl/pages/team.py", title="NHL Team", url_path="nhl-team"),
    st.Page("nhl/pages/compare.py", title="NHL Compare", url_path="nhl-compare"),
    st.Page("nhl/pages/today.py", title="NHL Today's Games", url_path="nhl-today"),
    st.Page("nhl/pages/schedule.py", title="NHL Schedule", url_path="nhl-schedule"),
    st.Page("nhl/pages/standings.py", title="NHL Standings", url_path="nhl-standings"),
    st.Page("nhl/pages/shots.py", title="NHL Shot Maps", url_path="nhl-shots"),
    st.Page("nhl/pages/map.py", title="NHL Birthplace Map", url_path="nhl-map"),
    st.Page("nhl/pages/digest.py", title="NHL Daily Digest", url_path="nhl-digest"),
    st.Page("nhl/pages/game.py", title="NHL Game Center", url_path="nhl-game"),  # reached from Today's Games / Digest, not the nav
    st.Page("nhl/pages/player.py", title="NHL Player", url_path="nhl-player"),  # deep-link only, not in nav loop
    st.Page("nhl/pages/glossary.py", title="NHL Glossary", url_path="nhl-glossary"),  # linked from the stat pages, not the nav
]

# Every page from both sports is registered (so every URL resolves), but
# only the active sport's links get rendered below.
pg = st.navigation(PAGES + NHL_PAGES, position="hidden")
active_sport = "nhl" if (pg.url_path or "").startswith("nhl") else "mlb"


_MLB_NAV_HIDDEN = (
    "Player", "Game Center", "Glossary", "Settings",
    "League Trends", "Ballparks", "Umpires", "Around the League", "Minor Leagues",
    "Box Score Search", "Free Agency",
)
# Daily Digest stays registered (so /nhl-digest resolves for previews) but off
# the nav until the season starts — every section is empty over the summer.
SHOW_NHL_DIGEST = False
_NHL_NAV_HIDDEN = {"NHL Player", "NHL Game Center", "NHL Glossary"} | (
    set() if SHOW_NHL_DIGEST else {"NHL Daily Digest"}
)

# Navigation is a full-width bar across the top rather than a sidebar column.
# These are plain anchors, not st.page_link: page_link only renders vertically
# in whatever container it's given, so it can't lay out as a horizontal strip.
if active_sport == "mlb":
    _nav = [(pg_.url_path or "", pg_.title) for pg_ in PAGES if pg_.title not in _MLB_NAV_HIDDEN]
else:
    _nav = [(pg_.url_path, pg_.title.replace("NHL ", "")) for pg_ in NHL_PAGES
            if pg_.title not in _NHL_NAV_HIDDEN]

_here = pg.url_path or ""
_links = "".join(
    f"<a class='dm-nav-link{' active' if path == _here else ''}' href='/{path}' target='_self'>{label}</a>"
    for path, label in _nav
)
_sport = "".join(
    f"<a class='dm-sport{' active' if active_sport == sid else ''}' href='/{home}' target='_self'>{lbl}</a>"
    for sid, home, lbl in (("mlb", "", "\u26be MLB"), ("nhl", "nhl", "\U0001F3D2 NHL"))
)
st.markdown(
    "<div class='dm-topnav'>"
    f"<a class='dm-brand' href='/' target='_self'>{style.diamond_logo(22)}"
    f"<span class='diamond-title'>Diamond Metrics</span></a>"
    f"<div class='dm-sportwrap'>{_sport}</div>"
    f"<nav class='dm-navlinks'>{_links}</nav>"
    "<a class='dm-nav-util' href='/Settings' target='_self'>Settings</a>"
    "</div>",
    unsafe_allow_html=True,
)

# Search stays a real Streamlit widget (it needs reruns and callbacks), so it
# can't live inside the static bar above — it keeps the sidebar, which is
# collapsed by default now that navigation has moved out of it.
sidebar.render_search(active_sport)

pg.run()
