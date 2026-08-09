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
import notifications
import sidebar
import style

st.set_page_config(page_title="Diamond Metrics", layout="wide")

# Seeds st.session_state's follow lists from the browser's own localStorage
# (see following.py) — must run before any page can read them.
following.bootstrap()

# "Recent activity for players you follow" — reuses the same yesterday's-
# performances/milestones data as the Following page, just condensed for
# the header bell. Computed on every rerun (cheap: a handful of already-
# cached dataframe filters), not a persistent read/unread tracker.
notif_items = notifications.get_notifications(db.db_mtime()) if db.DB_PATH.exists() else []

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
    "}"
    f"[data-testid='stHeader'] {{ height: {HEADER_HEIGHT}; }}"
    f"[data-testid='stMainBlockContainer'] {{ padding-top: {HEADER_HEIGHT} !important; }}"
    # Mobile: Streamlit's sidebar becomes an off-canvas overlay below this
    # width rather than a permanent 230px column, so the desktop offset
    # above (left: 230px, padding-left: 4.5rem — pushing the header clear
    # of the sidebar AND its own collapse arrow) leaves nothing but empty
    # space on a phone and shoves the logo/title towards the right edge.
    # Anchor to the left edge instead and shrink both down to fit.
    "@media (max-width: 640px) {"
    "  .diamond-header { left: 0 !important; padding-left: 0.75rem !important; gap: 6px !important; }"
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
    "</style>",
    unsafe_allow_html=True,
)

# Notification bell — lives in the same fixed header strip as the logo.
# The badge count and dropdown panel are pure HTML/CSS built from
# notif_items (computed above); the click-to-toggle and once-per-session
# auto-show behavior are wired up by the script block further down, since
# Streamlit's unsafe_allow_html never executes inline <script> tags.
_notif_badge = f"<span class='notif-badge'>{len(notif_items)}</span>" if notif_items else ""
_notif_items_html = "".join(
    f"<div class='notif-item'><b>{n['name']}</b> — {n['text']}</div>" for n in notif_items
) or "<div class='notif-item notif-empty'>Nothing new for your followed players.</div>"
st.markdown(
    "<style>"
    ".notif-bell { position: relative; cursor: pointer; font-size: 1.05rem; margin-left: 4px; user-select: none; }"
    ".notif-badge { position: absolute; top: -6px; right: -9px; background: #D32F2F; color: #fff;"
    "  border-radius: 999px; font-size: 0.6rem; font-weight: 700; min-width: 15px; height: 15px;"
    "  display: flex; align-items: center; justify-content: center; padding: 0 3px; line-height: 1; }"
    ".notif-panel { position: absolute; top: 30px; left: 0; width: 270px; max-height: 300px; overflow-y: auto;"
    "  background: #1B2438; border: 1px solid #3B4A82; border-radius: 10px; padding: 8px;"
    "  box-shadow: 0 8px 24px rgba(0,0,0,0.45); z-index: 2000000;"
    "  opacity: 0; transform: translateY(-8px); pointer-events: none;"
    "  transition: opacity 0.25s ease, transform 0.25s ease; }"
    ".notif-panel.show { opacity: 1; transform: translateY(0); pointer-events: auto; }"
    ".notif-item { padding: 7px 6px; border-bottom: 1px solid #2A3454; font-size: 0.8rem; color: #DCE1EA; }"
    ".notif-item:last-child { border-bottom: none; }"
    ".notif-empty { color: #9AA3B5; }"
    "</style>",
    unsafe_allow_html=True,
)
st.markdown(
    f"<div class='diamond-header'><span class='diamond-logo'>{style.diamond_logo(26)}</span>"
    f"<h1 class='diamond-title'>Diamond Metrics</h1>"
    f"<span id='notif-bell' class='notif-bell' title='Recent activity for players you follow'>"
    f"\U0001F514{_notif_badge}"
    f"<div id='notif-panel' class='notif-panel'>{_notif_items_html}</div>"
    f"</span></div>",
    unsafe_allow_html=True,
)
components.html(
    """
    <script>
    (function() {
        function setup() {
            const bell = window.parent.document.getElementById('notif-bell');
            const panel = window.parent.document.getElementById('notif-panel');
            if (!bell || !panel || bell.dataset.wired) return;
            bell.dataset.wired = '1';
            bell.addEventListener('click', function(e) {
                e.stopPropagation();
                panel.classList.toggle('show');
            });
            window.parent.document.addEventListener('click', function() {
                panel.classList.remove('show');
            });
            try {
                if (!window.parent.sessionStorage.getItem('diamond_notif_toast_shown')) {
                    window.parent.sessionStorage.setItem('diamond_notif_toast_shown', '1');
                    panel.classList.add('show');
                    setTimeout(function() { panel.classList.remove('show'); }, 3000);
                }
            } catch (e) {}
        }
        setup();
        new MutationObserver(setup).observe(window.parent.document.body, {childList: true, subtree: true});
    })();
    </script>
    """,
    height=0,
)

# Shrink the sidebar's built-in header bar (which only holds the collapse
# arrow) so the search box sits higher, closer to the top of the sidebar.
# Also narrows the sidebar itself (min/max-width pinned to override its
# default draggable-resize width). No border/divider — the sidebar shares
# the same background color as the rest of the site (see config.toml), so
# there's nothing to visually separate it from the main content anymore.
st.markdown(
    "<style>"
    "[data-testid='stSidebarHeader'] { height: 1.5rem; }"
    "[data-testid='stSidebar'] { min-width: 230px; max-width: 230px; }"
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
    st.Page("pages/10_Injury_Report.py", title="Injury Report"),
    st.Page("pages/11_Transactions.py", title="Transactions"),
    st.Page("pages/14_Milestone_Watch.py", title="Milestone Watch"),
    st.Page("pages/15_Mini_Games.py", title="Mini Games"),
    st.Page("pages/16_Awards_Race.py", title="Awards Race"),
    st.Page("pages/17_Research.py", title="Research"),
    st.Page("pages/_Player.py", title="Player"),  # deliberately no page_link below -> not shown in nav
]

pg = st.navigation(PAGES, position="hidden")

for p in PAGES:
    if p.title != "Player":
        st.sidebar.page_link(p, label=p.title)

pg.run()
