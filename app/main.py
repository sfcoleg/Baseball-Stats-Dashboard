"""Real entry point for the app (run via `streamlit run app/main.py`, not
Home.py directly).

The page scripts live in app/views/, NOT app/pages/, and the name matters:
Streamlit's classic multi-page auto-discovery triggers on a folder literally
named `pages/` next to the entrypoint. While it was named that, EVERY page
had a second URL (/Settings, /Batting, /Player, ...) that served the page
script directly and never ran this file — so none of the design system below
(theme tokens, component CSS, the Light/Dark override) applied, and those
routes silently fell back to Streamlit's own OS-driven theme. That was the
"dropdowns are dark in light mode" bug: any full-page navigation (a refresh,
a bookmark, a ?team= badge link, a localstorage_bridge redirect) landed on
one of those bypass routes. Renaming the folder removes the duplicate router
entirely, so every URL goes through st.navigation() here.

Uses st.navigation()/st.Page() rather than that classic system, specifically so:
  1. The sidebar search box can render ABOVE the page nav. Neither the
     classic system nor st.navigation()'s own auto-rendered menu (position=
     "sidebar") support this — both always claim the very top of the
     sidebar regardless of script call order. The fix is position="hidden"
     (suppresses the automatic menu entirely) plus building the nav links
     ourselves with st.sidebar.page_link(), placed after the search box.
  2. The hidden player-profile page (views/_Player.py) can be fully
     excluded from the visible menu simply by not creating a page_link for
     it — it's still registered as a valid destination (it's in the list
     passed to st.navigation()), just not listed as a clickable link, so
     st.switch_page() still works. The classic system has no equivalent
     control (an underscore-prefixed filename does NOT hide a page from
     nav there, despite old docs/folklore suggesting it does).
"""
import json
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

st.set_page_config(page_title="Diamond Metrics", layout="wide")

# Seeds st.session_state's follow lists from the browser's own localStorage
# (see following.py) — must run before any page can read them. Each
# bootstrap() only reads whatever ?param= is already in the URL; it does
# NOT fire the actual localStorage->query-param redirect itself (see
# localstorage_bridge.py's register()/redirect()) — that happens ONCE, at
# the very bottom of this file, after pg.run().
#
# It used to have to be called from within each routed page's own script:
# a components.html() issued by main.py reportedly never executed in the
# browser. That is no longer true — verified on Streamlit 1.59 by deep-
# linking to /Batting and confirming ?prefs= arrives and the saved Light
# theme applies. Firing it once centrally is what the bridge wants anyway
# (see its docstring: there must only ever be ONE navigation), and it
# means a deep link to any page keeps the visitor's theme instead of
# falling back to the OS scheme.
following.bootstrap()
localstorage_bridge.register("following", following.STORAGE_KEY)
# Same localStorage pattern for the prediction game's picks (see
# predictions.py) — must also run before Today's Games can read them.
predictions.bootstrap()
localstorage_bridge.register("predictions", predictions.STORAGE_KEY)
# Same pattern again for site-wide preferences (default season, favorite
# team, Light/Dark — see prefs.py).
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
        "--dm-surface:#FBFCFE; --dm-surface-mute:#DFE3E9; --dm-card:#F2F7FD;"
        "--dm-banner:#D8E7F7; --dm-field:#EEF1F5;"
        "--dm-blue:#2E86DE; --dm-blue-text:#1B5FA8; --dm-blue-soft:#E7F1FC;"
        "--dm-amber:#B7791F; --dm-amber-soft:#FBF0DA;"
        "--dm-red:#C0453F; --dm-red-soft:#FBE9E8;"
        "--dm-green:#2E7D32; --dm-green-soft:#E6F4E7;"
    ),
    "dark": (
        "--dm-text:#EFF3F9; --dm-dim:#9AA8BD; --dm-line:#2E3B4E;"
        "--dm-surface:#1E2735; --dm-surface-mute:#151C28; --dm-card:#1E2735;"
        "--dm-banner:#1B2740; --dm-field:#26314A;"
        "--dm-blue:#6FAFE8; --dm-blue-text:#9BCAF3; --dm-blue-soft:#22334A;"
        "--dm-amber:#F5B942; --dm-amber-soft:#3A2F16;"
        "--dm-red:#F87171; --dm-red-soft:#3A1F1F;"
        "--dm-green:#7CFC9A; --dm-green-soft:#16301C;"
    ),
}
_theme_obj = getattr(getattr(st, "context", None), "theme", None)
_detected = getattr(_theme_obj, "type", None)
_theme_type = prefs.resolve_theme(_detected)
style.apply_theme(_theme_type)

# Streamlit's own chrome follows the system scheme, which is what made the
# page appear to flip on navigation: its inference could land on a different
# answer than ours between runs. With an explicit Light/Dark choice we paint
# the app surfaces ourselves so the two can never disagree.
_FORCE_BG = {"light": ("#DFE3E9", "#0C1725", "#F4F7FB"),
             "dark": ("#151C28", "#EFF3F9", "#1E2735")}
if prefs.theme_preference() in ("light", "dark"):
    _bg, _fg, _side = _FORCE_BG[_theme_type]
    st.markdown(
        "<style>"
        f"[data-testid='stApp'],[data-testid='stMain']{{background:{_bg} !important;}}"
        f"[data-testid='stAppViewContainer']{{background:{_bg} !important;}}"
        f"[data-testid='stSidebar']{{background:{_side} !important;}}"
        f"[data-testid='stMain'],[data-testid='stMain'] p,[data-testid='stMain'] "
        f"li,[data-testid='stMain'] label{{color:{_fg};}}"
        "</style>",
        unsafe_allow_html=True,
    )
st.markdown(
    f"<style>:root{{{_THEME_TOKENS.get(_theme_type, _THEME_TOKENS['light'])}}}</style>",
    unsafe_allow_html=True,
)

# Component styling — the visual language from the design studies, applied
# once here so every page inherits it rather than each re-inventing a card.
# Streamlit's own containers/metrics are restyled in place; anything we hand-
# write (section headings, game cards) gets a dm-* class. The raised-card
# shadow is light-theme only — on a dark ground it just muddies the edge; a
# hairline border stands in instead, since dark-mode card vs. page background
# is too close in value on its own for a bubble edge to read clearly.
_CARD_SHADOW = (
    "box-shadow:0 1px 2px rgba(12,23,37,0.06);" if _theme_type == "light"
    else "border:1px solid rgba(255,255,255,0.06);"
)
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
    # Explicit padding, not just Streamlit's own default gap — without it,
    # content (e.g. Game Center's on-the-mound/due-up cards) sits flush
    # against the card edge instead of inside it.
    "[data-testid='stMain'] [data-testid='stLayoutWrapper'] > [data-testid='stVerticalBlock']{"
    f"  background:var(--dm-surface);border-radius:14px;padding:16px 18px;{_CARD_SHADOW}}}"
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
    # --- two-row header: blue banner over the tab strip --------------------
    ".dm-banner{position:fixed;top:0;left:0;right:0;height:3.05rem;z-index:999990;"
    "  background:var(--dm-banner);display:flex;align-items:center;padding:0 16px;"
    "  border-bottom:1px solid var(--dm-line);}"
    ".dm-brand{display:flex;align-items:center;gap:9px;text-decoration:none;}"
    ".dm-brand .diamond-title{font-size:1.15rem !important;line-height:1 !important;}"
    # The tab strip. .st-key-dm_nav IS Streamlit's vertical block, so the row
    # direction goes on the element itself, not a descendant.
    ".st-key-dm_nav{position:fixed;top:3.05rem;left:0;right:0;z-index:999989;"
    "  background:var(--dm-surface);padding:0 14px;height:2.85rem;"
    "  flex-direction:row !important;align-items:center;gap:2px !important;"
    "  flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;box-shadow:none !important;}"
    ".st-key-dm_nav::-webkit-scrollbar{display:none;}"
    ".st-key-dm_nav [data-testid='stElementContainer']{width:auto !important;flex:0 0 auto;}"
    ".st-key-dm_nav [data-testid='stPageLink'] a{padding:5px 9px;border-radius:7px;}"
    ".st-key-dm_nav [data-testid='stPageLink'] p{font-family:'Archivo Narrow',sans-serif;"
    "  font-weight:600;font-size:0.92rem;letter-spacing:0.4px;text-transform:uppercase;"
    "  color:var(--dm-dim);margin:0;white-space:nowrap;}"
    ".st-key-dm_nav [data-testid='stPageLink'] a:hover p{color:var(--dm-text);}"
    # Search sits permanently in the banner's right end. It's a
    # st.container() like any other, so the bordered-container bubble rule
    # above would otherwise wrap it in a full padded card — override that
    # back to a bare, compact box that just holds the input.
    ".st-key-dm_search{position:fixed;top:0.5rem;right:14px;width:200px;z-index:999995;"
    "  background:transparent !important;padding:0 !important;border:none !important;"
    "  box-shadow:none !important;max-height:85vh;overflow-y:auto;}"
    ".st-key-dm_search [data-testid='stTextInput'] input{height:1.9rem;font-size:0.8rem;"
    "  padding:2px 10px;background:var(--dm-surface) !important;color:var(--dm-text) !important;"
    "  border-color:var(--dm-line) !important;}"
    ".st-key-dm_search [data-testid='stTextInput'] input::placeholder{color:var(--dm-dim);opacity:1;}"
    # Search RESULTS (buttons + captions) render below the input, still
    # inside this same fixed box — Streamlit's own button/caption styling
    # is theme-agnostic (a plain light control), which read as a stray
    # white panel dropped onto a dark page. Recolor them to match.
    ".st-key-dm_search [data-testid='stButton'] button{font-size:0.75rem;padding:4px 8px;"
    "  background:var(--dm-surface) !important;color:var(--dm-text) !important;"
    "  border-color:var(--dm-line) !important;text-align:left;justify-content:flex-start;}"
    ".st-key-dm_search [data-testid='stButton'] button:hover{background:var(--dm-surface-mute) !important;}"
    ".st-key-dm_search [data-testid='stCaptionContainer']{color:var(--dm-dim) !important;}"
    # --- content sits on a panel, with the grey page visible around it ------
    # The page itself is grey; content sits on it as separate bubbles rather
    # than one long sheet. Section headings stay bare on the grey so each
    # heading reads as a label ABOVE its card, not another card.
    "[data-testid='stMainBlockContainer']{background:transparent;"
    "  padding:4px 0 34px !important;margin:6.4rem auto 0 !important;"
    "  max-width:calc(100% - 44px) !important;}"
    # Substantial blocks — tables, charts, hand-written HTML tables — each get
    # their own bubble. Captions, inputs and headings are left bare: bubbling
    # every element turns the page into confetti.
    "[data-testid='stMainBlockContainer'] [data-testid='stElementContainer']:has("
    "  [data-testid='stDataFrame']),"
    "[data-testid='stMainBlockContainer'] [data-testid='stElementContainer']:has("
    "  [data-testid='stPlotlyChart']),"
    "[data-testid='stMainBlockContainer'] [data-testid='stElementContainer']:has(table),"
    # Hand-written HTML cards (Daily Digest's transactions, On This Day,
    # biggest plays) go out through st.markdown rather than a container, so
    # they need bubbling too. Our card helpers emit a div carrying inline
    # styles; plain markdown text emits <p>, and section headings put their
    # inline style on a span, so neither is caught by this.
    "[data-testid='stMainBlockContainer'] [data-testid='stElementContainer']:has("
    "  [data-testid='stMarkdown'] div[style]){"
    f"  background:var(--dm-surface);border-radius:14px;padding:20px 22px;{_CARD_SHADOW}}}"
    # Rows that are already their own card (Injury Report, Transactions) opt
    # out of the generic HTML-card bubble above — a bubble around a row that's
    # already got its own background just draws a box around a box, one per
    # row, which reads as clutter rather than structure.
    "[data-testid='stMainBlockContainer'] [data-testid='stElementContainer']:has("
    "  .dm-flat-card){background:transparent !important;border:none !important;"
    "  box-shadow:none !important;padding:0 !important;}"
    # A bubble inside a bubble just draws a box around a box. This has to
    # reach EVERY depth inside a card, not just its direct children —
    # Today's Games (and Game Center, Following) lay a card's contents out
    # in st.columns, which buries them a few levels down and left them
    # still bubbled.
    #
    # The "> stVerticalBlock" is what keeps this from over-reaching: a
    # bordered st.container renders as stLayoutWrapper > stVerticalBlock,
    # whereas st.columns renders as stLayoutWrapper > stHorizontalBlock. So
    # this matches only things genuinely inside a card, and top-level
    # columns (Home's Team Snapshot and Standings) keep their own bubbles.
    "[data-testid='stLayoutWrapper'] > [data-testid='stVerticalBlock'] "
    "  [data-testid='stElementContainer']{background:transparent !important;"
    "  box-shadow:none !important;border:none !important;padding:0 !important;}"

    # Every st.markdown("<style>") and every localStorage-bridge component
    # renders nothing, but Streamlit still gives each one a slot in the
    # vertical block's 1rem gap — six of them stack up into ~100px of dead
    # space above the real content on every page.
    "[data-testid='stElementContainer']:has("
    "  [data-testid='stMarkdown'] div > style:only-child){display:none !important;}"
    "[data-testid='stElementContainer']:has(> [data-testid='stCustomComponentV1']){"
    "  display:none !important;}"
    "@media (min-width:641px){[data-testid='stSidebar']{display:none !important;}"
    "  [data-testid='stSidebarCollapsedControl']{display:none !important;}}"
    "@media (max-width:640px){.st-key-dm_nav,.st-key-dm_search,.dm-banner{display:none !important;}"
    "  [data-testid='stMainBlockContainer']{margin:0 !important;padding-top:2.5rem !important;"
    "    border-radius:0;}}"
    # Streamlit's own header bar sits between our banner and the tab row and
    # paints its own background there — a dark band across the top with
    # nothing in it. Its toolbar still needs to be reachable, so hide the bar
    # itself rather than the controls.
    "[data-testid='stHeader']{background:transparent !important;height:0 !important;}"
    "[data-testid='stToolbar']{z-index:999999;}"
    # --- inputs: light grey fields rather than stark white or dark ---------
    # Streamlit 1.59 moved its widgets off BaseWeb and onto React Aria: a
    # selectbox now renders as .react-aria-ComboBox with NO data-baseweb
    # attribute anywhere in it. Every [data-baseweb='...'] selector here
    # therefore matches nothing on this version, which is why closed
    # dropdowns and text fields kept Streamlit's own theme — and that theme
    # follows the OS, not our resolved one, so on a dark-OS machine they
    # stayed dark on a light page no matter what the Light setting said.
    #
    # The selectors doing the actual work now are Streamlit's own stable
    # data-testids plus React Aria's semantic class names. The baseweb ones
    # are kept alongside purely as a fallback in case a Streamlit version
    # renders BaseWeb again; a selector that matches nothing costs nothing.
    #
    # NB: the painted surface is the input's ROOT wrapper, not the <input>
    # itself — styling only the inner <input> (as this block used to) left
    # the visible box its original colour.
    "[data-testid='stSelectbox'] [role='group'],"
    "[data-testid='stMultiSelect'] [role='group'],"
    "[data-testid='stDateInput'] [role='group'],"
    "[data-testid='stTextInputRootElement'],"
    "[data-testid='stNumberInputContainer'],"
    ".react-aria-ComboBox [role='group'],"
    "[data-baseweb='select'] > div,[data-baseweb='input'],"
    "[data-testid='stTextInput'] input,[data-testid='stNumberInput'] input,"
    "[data-testid='stDateInput'] input{"
    "  background:var(--dm-field) !important;border-color:var(--dm-line) !important;"
    "  color:var(--dm-text) !important;}"
    # The inner <input> sits on top of that wrapper and carries its own
    # colour, so it needs the text colour too or it stays light-on-light.
    "[data-testid='stSelectbox'] input,[data-testid='stMultiSelect'] input,"
    "[data-testid='stTextInputRootElement'] input{"
    "  background:transparent !important;color:var(--dm-text) !important;}"
    # Secondary buttons are the last widget still painting itself from
    # Streamlit's own (OS-driven) theme rather than ours. Primary buttons
    # are left alone — they carry the accent colour on purpose.
    "[data-testid='stBaseButton-secondary']{background:var(--dm-field) !important;"
    "  color:var(--dm-text) !important;border-color:var(--dm-line) !important;}"
    "[data-testid='stBaseButton-secondary']:hover{"
    "  background:var(--dm-surface-mute) !important;}"
    # The open dropdown panel. Streamlit 1.59 renders selectbox menus as
    # [data-testid='stSelectboxVirtualDropdown'], NOT the data-baseweb
    # popover/menu the older selectors assumed — those matched nothing, so
    # the panel fell through to the page's own grey and read as a dark
    # block sitting on a light page.
    "[data-testid='stSelectboxVirtualDropdown'],"
    "[data-baseweb='popover'] [role='listbox'],[data-baseweb='menu']{"
    "  background:var(--dm-field) !important;}"
    "[data-testid='stSelectboxVirtualDropdown'] [role='option'],"
    "[data-baseweb='menu'] li{color:var(--dm-text) !important;}"
    "[data-testid='stSelectboxVirtualDropdown'] [role='option']:hover{"
    "  background:var(--dm-surface-mute) !important;}"
    # Multiselect chips (the "Transaction type" filter, Custom Leaderboard's
    # stat picker) are their own baseweb tag element, missed the same way.
    "[data-baseweb='tag']{background:var(--dm-blue-soft) !important;"
    "  color:var(--dm-text) !important;}"
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
    st.Page("views/12_Daily_Digest.py", title="Clubhouse Report"),
    st.Page("views/13_Following.py", title="Following"),
    st.Page("views/1_Batting.py", title="Batting"),
    st.Page("views/2_Pitching.py", title="Pitching"),
    st.Page("views/3_Fielding.py", title="Fielding"),
    st.Page("views/6_Baserunning.py", title="Baserunning"),
    st.Page("views/4_Team.py", title="Team"),
    st.Page("views/5_Compare.py", title="Compare"),
    st.Page("views/8_Todays_Games.py", title="Today's Games"),
    st.Page("views/31_Schedule.py", title="Schedule"),
    st.Page("views/9_Standings.py", title="Standings"),
    st.Page("views/17_Playoffs.py", title="Playoffs"),
    st.Page("views/34_Other.py", title="Other"),
    # Everything below is reached through the Other hub page above, not its
    # own sidebar slot — still registered here (so their URLs/page_links
    # resolve), just excluded from the main nav loop below.
    st.Page("views/30_League_Trends.py", title="League Trends"),
    st.Page("views/33_Ballparks.py", title="Ballparks"),
    st.Page("views/23_Umpires.py", title="Umpires"),
    st.Page("views/29_Around_the_League.py", title="Around the League"),
    st.Page("views/18_Minor_Leagues.py", title="Minor Leagues"),
    st.Page("views/22_Box_Score_Search.py", title="Box Score Search"),
    st.Page("views/25_Glossary.py", title="Glossary"),  # linked separately below, not in the main nav loop
    st.Page("views/26_Settings.py", title="Settings"),  # same — its own small button, not in the main nav loop
    st.Page("views/_Player.py", title="Player"),  # deliberately no page_link below -> not shown in nav
    st.Page("views/_Game_Detail.py", title="Game Center"),  # same — reached only via Today's Games' button
]
if SHOW_FREE_AGENCY:
    PAGES.insert(-1, st.Page("views/21_Free_Agency.py", title="Free Agency"))

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

# Navigation renders twice, and CSS picks one: a full-width bar across the top
# on desktop, and the original sidebar on mobile, where a horizontal strip of a
# dozen links would be unusable. Only one is ever visible.
#
# These are st.page_link, NOT hand-written <a> tags. A plain anchor triggers a
# full page load, and because app/pages/ sits next to this script Streamlit
# also runs its classic file-based router — so a full load of e.g. /Batting
# renders that file on its own, without main.py, losing the bar and the theme
# entirely. page_link navigates through Streamlit's own router instead, which
# keeps main.py in charge, and it marks the current page for free.
if active_sport == "mlb":
    _nav_pages = [pg_ for pg_ in PAGES if pg_.title not in _MLB_NAV_HIDDEN]
else:
    _nav_pages = [pg_ for pg_ in NHL_PAGES if pg_.title not in _NHL_NAV_HIDDEN]

# Row one is the banner — identity on the left, search on the right, always
# present. Row two is the tabs. Two rows rather than one so a long nav never
# competes with the brand or the search box for the same strip of pixels.
st.markdown(
    f"<div class='dm-banner'><a class='dm-brand' href='/' target='_self'>"
    f"{style.diamond_logo(24)}<span class='diamond-title'>Diamond Metrics</span></a></div>",
    unsafe_allow_html=True,
)

_bar = st.container(key="dm_nav")
with _bar:
    for pg_ in _nav_pages:
        st.page_link(pg_, label=pg_.title.replace("NHL ", ""))
    # Sport switch and Settings ride at the right-hand end of the tab row.
    other_home = NHL_PAGES[0] if active_sport == "mlb" else PAGES[0]
    st.page_link(other_home, label="\U0001F3D2 NHL" if active_sport == "mlb" else "\u26be MLB")
    st.page_link(next(p_ for p_ in PAGES if p_.title == "Settings"), label="Settings")

# The bar can't host a widget, so search renders as its own container that CSS
# lifts into the slot reserved at the bar's right edge.
_search_box = st.container(key="dm_search")
sidebar.render_search(active_sport, target=_search_box, key_suffix="_top")

# --- mobile: the sidebar exactly as it was before the top bar existed --------
sidebar.render_sport_switcher(active_sport, {"mlb": PAGES[0], "nhl": NHL_PAGES[0]})
sidebar.render_search(active_sport)
if active_sport == "mlb":
    for p_ in PAGES:
        if p_.title not in _MLB_NAV_HIDDEN:
            st.sidebar.page_link(p_, label=p_.title)
else:
    for p_ in NHL_PAGES:
        if p_.title not in _NHL_NAV_HIDDEN:
            st.sidebar.page_link(p_, label=p_.title.replace("NHL ", ""))
st.sidebar.markdown(
    "<style>"
    "[data-testid='stSidebar'] a[href*='Settings'] { font-size: 0.8rem !important; opacity: 0.6; }"
    "[data-testid='stSidebar'] a[href*='Settings']:hover { opacity: 1; }"
    "</style>",
    unsafe_allow_html=True,
)
settings_page = next(p_ for p_ in PAGES if p_.title == "Settings")
st.sidebar.page_link(settings_page, label="Settings", use_container_width=False)

pg.run()

# --- keep STREAMLIT'S OWN theme in step with the visitor's choice ---------
# Everything above only *paints over* Streamlit's theme; it never changes it.
# That's enough for HTML we control, but not for anything Streamlit renders
# itself — most visibly st.dataframe, which draws to a <canvas> that no CSS
# can reach. With Streamlit left on "System" it follows the OS, so a
# dark-OS visitor who picked Light got light pages with dark TABLES on them.
#
# Streamlit persists its active theme in localStorage under
# stActiveTheme-<path>-v2 ("Light" / "Dark" / "System"), read once per page
# load. Writing it for every route makes Streamlit itself switch, which
# fixes the tables at the source. On "Match my device" we write "System"
# back, so clearing the preference genuinely hands control to the OS.
#
# These are handed to localstorage_bridge.redirect() rather than written by
# a script of our own ON PURPOSE: they need a reload to take effect, and the
# bridge is already the page's one and only navigator. Giving the page a
# second one raced this against the query-param hydration — whichever won,
# the other's work was lost, which showed up as the page randomly reloading
# and coming back in the wrong colours.
#
# This is Streamlit-internal storage, not a public API — if a future version
# renames the key this silently stops working (tables would go back to
# following the OS), so it's deliberately additive: nothing depends on it.
_ST_THEME = {"light": "Light", "dark": "Dark"}.get(prefs.theme_preference(), "System")
_theme_keys = {
    f"stActiveTheme-{path}-v2": json.dumps(_ST_THEME)
    for path in {"/"} | {f"/{p.url_path}" for p in PAGES + NHL_PAGES if getattr(p, "url_path", "")}
}

# One localStorage -> query-param redirect for every registered key, fired
# once, after the routed page has rendered. See the note beside the
# bootstrap() calls at the top for why this lives here rather than in each
# page, and localstorage_bridge.py for why there must only ever be one.
localstorage_bridge.redirect(also_set=_theme_keys)
