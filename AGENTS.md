# Sabermetrics Dashboard — Agent Guide

A Streamlit dashboard for MLB batting/pitching/fielding stats and sabermetrics, backed by a local SQLite cache populated from Baseball-Reference and Statcast (via `pybaseball`), plus today's schedule from the MLB Stats API.

## Running the app

```bash
cd "Sabermetrics Dashboard"
./venv/bin/streamlit run app/main.py
```

Opens at `http://localhost:8501`. **`app/main.py` is the entry point, not `Home.py`.** It uses `st.navigation()`/`st.Page()` (not Streamlit's classic `pages/`-folder auto-discovery) so it can render the sidebar search box above the page nav and hide the `_Player.py` page from the nav entirely — see "Navigation (`app/main.py`)" below. The Streamlit Community Cloud "Main file path" setting must also point at `app/main.py`.

**Refresh data manually:**
```bash
./venv/bin/python ingest/refresh_data.py
```
This also runs automatically every day at 6am via a `launchd` job (`~/Library/LaunchAgents/com.sabermetrics.dailyrefresh.plist`). Logs to `data/refresh.log`.

## Environment

- Python **3.13** (not 3.14 — see "Known issues" below). Venv at `venv/`.
- Install deps: `./venv/bin/pip install -r requirements.txt`
- Config: `.streamlit/config.toml` sets theme (colors, `baseRadius`) and disables the file watcher (`fileWatcherType = "none"`) and usage stats.

**The file watcher is disabled**, so Streamlit does NOT auto-reload on code changes. After editing any `app/*.py` file, you must manually restart the server:
```bash
pkill -f "streamlit run"
cd "Sabermetrics Dashboard" && ./venv/bin/streamlit run app/main.py --server.headless true --server.port 8501 > /tmp/streamlit.log 2>&1 &
```

## Project structure

```
app/
  main.py           # ACTUAL entry point (run via `streamlit run app/main.py`) — see "Navigation" below
  Home.py           # Landing page: milestones, headliner cards, HR chart, team snapshot, leaderboards
  db.py             # All SQLite reads, caching (st.cache_data), search, percentile helpers, prediction model
  sidebar.py         # Persistent player-search box shown in the sidebar on every page (see below)
  style.py          # pandas Styler helpers: color-graded tables, team/milestone/radar-chart widgets, colored section headers
  teams.py          # Team abbreviation/color lookup (disambiguates shared cities like NY/Chicago/LA via the Lev column)
  pages/
    1_Batting.py    # Filterable batting leaderboard (Standard/Advanced/Statcast/Chart Explorer tabs)
    2_Pitching.py   # Filterable pitching leaderboard (same tab structure)
    3_Fielding.py   # Outs Above Average (OAA) leaderboard
    4_Team.py       # Full batting/pitching/fielding roster for one team+season
    5_Compare.py    # Side-by-side two-player comparison with winner highlighting + percentile radar chart
    6_Signals.py    # Breakout/regression flags (xwOBA-wOBA gap for batters, ERA-FIP gap for pitchers)
    7_Custom_Rankings.py  # Slider-weighted z-score composite leaderboard
    8_Todays_Games.py     # Today's schedule: live scores, venue, our own Log5-based win predictions/odds, on-demand box scores
    9_Standings.py        # Current MLB division standings (MLB Stats API)
    _Player.py      # Player profile view — NOT reached via its own nav tab; driven by st.session_state
                     # ("selected_mlbID"/"selected_name"/"selected_season") set by sidebar.render_search(),
                     # navigated to via st.switch_page("pages/_Player.py"). Excluded from the visible sidebar
                     # nav (see "Navigation" below) — it's registered as a valid destination but has no
                     # page_link, so it's reachable only via the search box. Visiting it directly with no
                     # prior search shows a "use the sidebar search" prompt instead of erroring.
ingest/
  refresh_data.py   # Pulls all data from pybaseball + MLB Stats API, computes sabermetrics, writes to data/stats.db
data/
  stats.db          # SQLite cache: batting, pitching, fielding (multi-season, keyed by `season`),
                     # recent_batting, recent_pitching, todays_games, standings (current-day only, replaced daily),
                     # player_history (append-only)
  refresh.log        # launchd job output
```

## Navigation (`app/main.py`)

`app/main.py` is the real entry point (`streamlit run app/main.py`), not the classic `pages/`-folder auto-discovery. It uses `st.navigation()`/`st.Page()` with `position="hidden"` (suppresses Streamlit's own auto-rendered nav menu) and then hand-builds the sidebar with `st.sidebar.page_link()` calls, in this order: `sidebar.render_search()` first, then a divider, then one `page_link` per page. This was the only way to get both of these at once — Streamlit's auto-rendered menu (classic system or `st.navigation(position="sidebar")`) always claims the top of the sidebar regardless of script call order:
1. **Search box above the page nav.**
2. **`_Player.py` hidden from the nav.** It's still included in the `PAGES` list passed to `st.navigation()` (so it's a valid, routable destination for `st.switch_page`), but the `page_link` loop skips it, so no clickable link is ever rendered for it.

Each individual page script (`Home.py`, everything in `pages/`) still calls its own `st.set_page_config(...)` for its browser-tab title — this doesn't conflict with the one `main.py` also calls. If you add a new page, add it to the `PAGES` list in `main.py` (plus a `page_link` line unless you want it hidden like `_Player.py`) — adding a file to `app/pages/` alone does nothing now, since auto-discovery is off.

## Sidebar search (`app/sidebar.py`)

Player search is NOT a dedicated page — `sidebar.render_search()` is called once, in `app/main.py`, before the nav links are built (see above), so the persistent search box renders at the very top of the sidebar on every page. Typing a query shows up to 8 matching players as buttons; clicking one sets `st.session_state["selected_mlbID"]`/`["selected_name"]`/`["selected_season"]` and calls `st.switch_page("pages/_Player.py")` to show the profile. Individual page scripts do NOT call `render_search()` themselves anymore — only `main.py` does.

## Data pipeline (`ingest/refresh_data.py`)

- **Base batting/pitching stats**: Baseball-Reference via `pybaseball.batting_stats_bref` / `pitching_stats_bref`. **Not** FanGraphs — FanGraphs blocks pybaseball's requests (403s from bot protection).
- **Statcast enrichment**: exit velocity, barrel%, xwOBA/xBA/xSLG, merged in by `mlbID`.
- **Fielding**: `statcast_outs_above_average` (OAA/FRP), keyed by `player_id`.
- **Recent-performance windows** (`recent_batting` / `recent_pitching` tables): date-range pulls via `batting_stats_range` / `pitching_stats_range` for yesterday / last 7 days / last 30 days, feeding the Home page's "Headliners" cards. Day-window batting ranks by **Total Bases**, not OPS (single-game OPS is noise); week/month rank by OPS. Day-window pitching ranks by **Game Score**; week/month by ERA with a minimum-IP bar.
- **`player_history`**: the only **append-only** table (all others use `if_exists="replace"` each run). One row per player per day: season-to-date OPS/ERA (powers the Search page's trend chart) plus `day_PA`/`day_H`/`day_IP`/`day_ER` — that single day's line, reused from the recent-performance fetch rather than a new network call (powers hit-streak / scoreless-streak tracking; a day with no game has these as null, which streak logic treats as "skip," not "streak broken"). Today's rows are deleted-then-reinserted first so re-running the script same-day doesn't duplicate. Only has data from whenever each feature shipped onward — no historical backfill. If you add columns to this table later, add a schema-migration check in `fetch_and_store()` (drop-and-recreate if an old copy lacks the new column) since `to_sql(if_exists="append")` requires an exact column match. When querying it with a raw SQL param, always cast `mlbID` to `int()` first — pandas hands back `numpy.int32`, and sqlite3 silently returns zero rows (no error) if you bind that directly instead of a native Python int.
- **`todays_games`**: fetched from the free public **MLB Stats API** (`statsapi.mlb.com`, no key needed) — the only data source in this app that isn't pybaseball/Baseball-Reference/Statcast. Full replace every run (today's schedule only, not historical); an off day correctly produces an empty table rather than stale games from a prior day. Includes `venue` (game location) alongside team records and probable pitchers. Powers the Today's Games page: `db.predict_game()` computes a win probability via the Log5 method on team win% + a home-field-advantage constant + a starting-pitcher ERA adjustment (using the same cached `pitching` table everything else uses). These are estimates calculated by this app, not real sportsbook odds — no betting-odds API is involved.
- **`standings`**: also MLB Stats API, current division standings, full replace every run. Division IDs aren't returned as plain strings by the API — `DIVISION_NAMES` in `refresh_data.py` hardcodes the id->name mapping.
- **Live scores and box scores are NOT part of the daily ingest** — both are fetched live, on-demand, from the app itself (not `refresh_data.py`), since scores change constantly through the day and pre-fetching them once at 6am would be instantly stale. `db.load_live_scores(date_str)` does one schedule API call (`hydrate=linescore`) covering every game at once, short TTL (~20s) cache, used for the score shown on every game card. `db.load_linescore(game_pk)` is a per-game detailed box score (inning-by-inning), fetched only when a user clicks "Show box score" for that specific game — button-gated so it doesn't fire for all games on every page load.
- There used to be a `prediction_history` table + Prediction Accuracy page tracking this app's predictions against real outcomes — removed per user request. If resurrecting it, the previous implementation's git history has the resolve/lock-in logic (and a real bug it's worth not repeating: never delete-and-reinsert a whole date's rows when storing new predictions, since that wipes out `actual_winner`/scores already resolved for other games sharing that date — only insert genuinely new `game_pk`s).
- **Multi-season data**: `batting`/`pitching`/`fielding` are keyed by `season` and written via DELETE-then-append per season (`_store_season_table()`), not a full-table replace — so backfilling historical seasons doesn't wipe the current one. Daily refresh only ever touches `CURRENT_SEASON`; add a historical year with `./venv/bin/python ingest/refresh_data.py --backfill <year>`, one year per invocation (deliberately not batched, to keep peak memory the same as a normal daily run on a memory-constrained machine — see "Known issues"). `recent_batting`/`recent_pitching`/`player_history`/`todays_games` are current-day/current-season concepts only and aren't backfilled.
- **Known data quirks handled in ingest**: Baseball-Reference leaves W/L/SV blank (not 0) for pitchers with none — filled to 0. Accented names (Acuña, Hernández) and escaped apostrophes (d'Arnaud) sometimes arrive as literal escape text from bref's scraper — fixed via `fix_mojibake_names`. MLB Stats API uses team abbreviation `AZ`; every other source in this app (including `teams.py`) uses `ARI` — remap before doing a color/abbreviation lookup (see `_ABBR_FIX` in `8_Todays_Games.py`).

## Conventions

- Every page loads data through `db.py` functions, which are all `st.cache_data`-cached keyed on `(season, db_mtime)` — never query `stats.db` directly from a page.
- Team badges: use `teams.add_team_abbr()` (city+league, for bref-sourced tables) or `teams.add_team_abbr_from_nickname()` (for Statcast-sourced tables like fielding) before styling with `teams.color_for_abbr`.
- Table styling goes through `style.style_stats_table()` (leaderboards) or `style.style_comparison()` (Compare page) — don't hand-roll pandas Styler calls in page code.
- Section headers use `style.colored_header(text, category)` for the colored left-accent bars, not `st.subheader`.
- No emojis in UI text (explicit user preference).
- No custom fonts (explicit user preference, as of the last styling pass) — theme customization is limited to colors and `baseRadius`.
- SQLite boolean-ish expressions (e.g. a computed `x = (a = b)` column) come back through pandas as a **string** dtype, not numeric — `.mean()`/aggregation silently breaks. Coerce with `pd.to_numeric(..., errors="coerce")` after reading if you add anything like this again.
- Plotly on the pinned version here rejects 8-digit hex colors (hex + alpha suffix, e.g. `"#4C9F7033"`) — valid CSS, invalid Plotly `fillcolor`/`gridcolor`. Use `style._hex_to_rgba()` instead of string-concatenating an alpha suffix onto a hex color for any Plotly chart.

## Known issues

- **This machine has chronic memory pressure** (8GB RAM often near-exhausted). Streamlit's Python process segfaults intermittently inside PyArrow's `mimalloc` allocator when serializing dataframes under memory pressure — a resource-exhaustion crash, not an app bug. Was worse under Python 3.14; the venv was switched to **Python 3.13** to test whether this reduces crash frequency. If the server dies, just restart it with the command above.
- Two background processes (`qproxy`, `webfilterproxyd` — Qustodio parental-control/content-filtering software) were observed consuming large amounts of RAM/CPU and contributing to the pressure. Not addressed by this project; user manages separately.
