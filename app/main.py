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
import sidebar
import style

st.set_page_config(page_title="Diamond Metrics", layout="wide")

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
# The bracket predictor's picks (see bracket_picks.py) are URL-based, not
# localStorage-based, so unlike following.py/predictions.py that module's
# bootstrap() only needs to run on the Playoffs page itself, not globally here.

# Logo + title header — rendered once here (not per-page) so it shows up on
# every page. Streamlit's own toolbar (hamburger menu / Deploy button) is an
# opaque bar pinned to the very top of the viewport; rather than push our
# header below it (leaving it lower than the toolbar's own icons), this
# places the logo/title INSIDE that same top strip via position:fixed, at
# the same height as the Deploy button and the sidebar's Player Search box.
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
    f"  color: {style.DIAMOND_COLOR} !important;"
    "  text-shadow: 1px 1px 0 #1E3A66, 2px 2px 0 #14294D, 4px 4px 8px rgba(0,0,0,0.45);"
    "}"
    ".diamond-header {"
    f"  position: fixed; top: 0; left: 230px; height: {HEADER_HEIGHT}; z-index: 1000000;"
    "  display: flex; align-items: center; gap: 8px; padding-left: 4.5rem;"
    "  transition: left 0.2s ease, padding-left 0.2s ease;"
    "}"
    f"[data-testid='stHeader'] {{ height: {HEADER_HEIGHT}; }}"
    f"[data-testid='stMainBlockContainer'] {{ padding-top: {HEADER_HEIGHT} !important; }}"
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

st.markdown(
    f"<div class='diamond-header'><span class='diamond-logo'>{style.diamond_logo(26)}</span>"
    f"<h1 class='diamond-title'>Diamond Metrics</h1>"
    f"</div>",
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

sidebar.render_search()

# Free agency is an offseason feature — irrelevant (and a little confusing,
# since "unattached" reads oddly for a guy who's mid-season on a roster)
# while the season's actually being played. Flip this to True once the
# regular season wraps up, and back to False again once free agents start
# signing in bulk and pennant races take back over.
SHOW_FREE_AGENCY = False

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
    st.Page("pages/9_Standings.py", title="Standings"),
    st.Page("pages/17_Playoffs.py", title="Playoffs"),
    st.Page("pages/10_Injury_Report.py", title="Injury Report"),
    st.Page("pages/11_Transactions.py", title="Transactions"),
    st.Page("pages/16_Awards_Race.py", title="Awards Race"),
    st.Page("pages/18_Minor_Leagues.py", title="Minor Leagues"),
    st.Page("pages/22_Box_Score_Search.py", title="Box Score Search"),
    st.Page("pages/_Player.py", title="Player"),  # deliberately no page_link below -> not shown in nav
]
if SHOW_FREE_AGENCY:
    PAGES.insert(-1, st.Page("pages/21_Free_Agency.py", title="Free Agency"))

pg = st.navigation(PAGES, position="hidden")

for p in PAGES:
    if p.title != "Player":
        st.sidebar.page_link(p, label=p.title)

pg.run()
