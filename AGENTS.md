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
- **`ANTHROPIC_API_KEY`** (optional): needed only for the Daily Digest page's AI-written "Today's Storylines" (see `ingest/refresh_data.py`'s `build_daily_articles()`/`_generate_article()`). Must be set in whatever environment runs `ingest/refresh_data.py` — export it in your shell for a manual run, and add an `EnvironmentVariables` dict to the `launchd` plist for the daily automated run (not present by default; `launchd` jobs don't inherit your shell's exported vars). Missing key = that section of the Daily Digest just stays empty for the day, not an error — nothing else in the app depends on this key.

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
    6_Baserunning.py       # SB/CS (Baseball-Reference) + Statcast sprint speed/home-to-1st/baserunning
                           # runs (BsR) leaderboard, with a computed SB% and a sprint-speed-vs-BsR scatter
                           # chart. Filename number is a leftover from the deleted Signals page's slot —
                           # nav ORDER is controlled by the PAGES list in main.py, not the filename, and
                           # this sits right after Fielding. BsR only has real values for the CURRENT
                           # season — Baseball Savant's baserunning-run-value leaderboard ignores the year
                           # param and always serves the current season's data, so
                           # ingest.fetch_batting() only calls it when season == CURRENT_SEASON and fills
                           # an all-NaN column otherwise (verified: requesting year=2022 vs year=2026
                           # returns byte-identical rows both stamped 2026 — there's no historical query
                           # available through this endpoint at all).
    4_Team.py       # Full batting/pitching/fielding roster for one team+season, plus a starting-
                     # lineup baseball diamond (live MLB Stats API depth chart, see db.load_depth_chart).
                     # "View" selector also offers two stats-driven composite rosters in place of a
                     # real team — All MLB / All Month — see db.build_composite_team()
    5_Compare.py    # Side-by-side two-player comparison with winner highlighting + percentile radar chart
    8_Todays_Games.py     # Today's schedule: live scores, venue, our own Log5-based win predictions/odds, on-demand
                           # box scores, and each pre-game matchup's start time converted to the viewer's own local
                           # timezone client-side (st.components.v1.html() running JS in a real iframe, reaching into
                           # window.parent.document — st.markdown's unsafe_allow_html can't execute <script> tags at
                           # all, since innerHTML-inserted scripts never run per browser spec). The UTC timestamp from
                           # the Stats API sits in each placeholder div's data-utc attribute; a setInterval poll keeps
                           # re-applying the conversion since Streamlit reruns (e.g. "Show box score") recreate those
                           # divs with fresh unconverted text.
    9_Standings.py        # Current MLB division standings (MLB Stats API). Each team's abbreviation is a
                           # clickable colored badge (style.standings_table() — a hand-built HTML table, not
                           # st.dataframe, since st.dataframe's row-selection only offers a checkbox/radio
                           # selector column, not click-the-cell-itself) linking to `?team=ABBR`. The page
                           # checks st.query_params for that on load, stashes it in session_state, and
                           # st.switch_page()s to the Team page, which pre-selects it (then pops the
                           # session_state key so a later manual selectbox change isn't overridden on a
                           # subsequent visit).
    10_Injury_Report.py   # Every player on a major-league IL across all 30 teams (db.load_injury_report()) —
                           # 40-man roster status codes (D7/D10/D15/D60) give the authoritative current list;
                           # cross-referenced against the last 45 days of transactions for the injury detail text.
    11_Transactions.py    # Recent MLB roster moves (trades, signings, DFAs, IL moves, etc.) from the Stats
                           # API's /transactions endpoint (db.load_transactions()), filterable by lookback
                           # window/type/team — built for keeping an eye on trade deadline activity.
    12_Daily_Digest.py     # "Everything that happened yesterday" in one scroll — the differentiator is
                           # bundling data this app already computes separately elsewhere, not new data:
                           # milestones (db.get_milestones), top 5 day-window batting/pitching performances
                           # (db.top_n_recent_batters()/top_n_recent_pitchers(), new — top_recent_performer()/
                           # top_recent_pitcher() only return the single best), yesterday's transactions
                           # (db.load_transactions(2) filtered to date == yesterday), and new injured-list
                           # placements carved out of that same transactions pull (Status Change + "injured
                           # list" in the description, minus "activated" ones). Placed second in nav, right
                           # after Home, in main.py's PAGES list.
                           #
                           # "Today's Storylines" (top of the page) is db.load_daily_articles() reading a
                           # `daily_articles` SQLite table — 3 AI-written multi-paragraph articles (Claude, NO
                           # web search — written purely from this app's own stats, fed to the model as a full
                           # data dump rather than a summarized sentence or two) covering: the day's best
                           # batting line, best pitching line, and either the most notable injury or (if none
                           # clears the bar that day) a third notable performance, so the digest reliably gets
                           # 3 stories rather than however many happened to clear a threshold. Generation
                           # happens once during the DAILY INGEST RUN, not at page-load time — see
                           # build_daily_articles()/_generate_article() in ingest/refresh_data.py — since each
                           # article is a real, billed API call. The page just reads the cached result; if
                           # ANTHROPIC_API_KEY isn't set in the ingest environment (see "Required environment
                           # variables" below), the table ends up empty for that day and the page shows its
                           # "nothing stood out" state, not an error — a missing/failed key should never break
                           # the daily refresh.
                           #
                           # _batting_stat_dump()/_pitching_stat_dump() build that data dump — the player's
                           # full season line (BA/OBP/SLG/HR/RBI/ISO/BABIP/K%/BB%/wOBA/xwOBA/WAR/OPS+/wRC+ for
                           # batting; ERA/WHIP/IP/SO/K9/BB9/FIP/xERA/WAR/ERA+ for pitching) plus a few
                           # percentile ranks, handed to _generate_article() alongside a one-line "trigger"
                           # describing yesterday's specific performance. _generate_article() calls the
                           # Anthropic Messages API and asks for a JSON response
                           # ({"headline","teaser","paragraphs"}), parsed via a `re.search(r"\{.*\}", ...)`
                           # grab of the JSON object out of the response text. Any failure (missing key,
                           # network/API error, bad JSON) returns None for that one candidate rather than
                           # raising, so one flaky call can't take down the rest of the ingest run.
                           # _batting_article()/_pitching_article() wrap a single day-window row into one
                           # article and track a `used_ids` set so the guaranteed-3rd-article fallback (next-
                           # best batting/pitching performance when there's no notable injury) can't write up
                           # the same player twice. The injury path needs its own fetch_il_moves() (a
                           # lightweight duplicate of app/db.py's load_transactions(), since the ingest script
                           # deliberately doesn't import app/db.py's Streamlit-heavy module) to join a
                           # placement's description back to that player's season stats.
                           #
                           # `daily_articles` is replaced wholesale every ingest run (current day's storylines
                           # only, like todays_games/standings) — paragraphs are stored JSON-encoded in a single
                           # TEXT column since SQLite has no array type.
                           #
                           # Each storyline card shows only the "teaser" with a "Read more →" button; clicking
                           # it stashes the full article dict in st.session_state["selected_article"] and
                           # st.switch_page()s to pages/_Article.py (hidden from nav, same pattern as
                           # _Player.py) to render the full multi-paragraph piece.
    13_Following.py        # Follow teams/players, get a personalized feed: today's games for followed teams
                           # (todays_games filtered to rows where either side's normalized abbr is followed,
                           # same predict_game()/live_scores rendering as 8_Todays_Games.py, just simplified)
                           # plus yesterday's day-window performances for followed players (recent_batting/
                           # recent_pitching filtered to followed mlbIDs, rendered via style.milestone_card()
                           # — the same helper the Daily Digest uses). Persisted per-browser in the client's
                           # own localStorage (app/following.py), NOT server-side — there's no login, so a
                           # shared SQLite table would mean every visitor sees and edits the same list.
                           # followed_teams/followed_players live in st.session_state as lists of
                           # {"abbr","nickname"}/{"mlbID","name"} dicts, read/written directly by this page
                           # (`.append()`/`.remove()` on the same list object session_state holds).
                           #
                           # following.bootstrap() seeds those two session_state keys and MUST run before
                           # they're read. It's called both in main.py (the normal path) and again at the top
                           # of this page itself (idempotent — no-ops if already hydrated this session),
                           # because Streamlit's legacy pages/-folder auto-discovery can route a direct URL
                           # hit straight to a page's script via `_mpa_v1`, bypassing main.py's top-level code
                           # entirely. Since there's no built-in two-way JS<->Python channel, persistence uses
                           # two one-way `components.html()` script bridges:
                           #   - LOAD (JS->Python, in bootstrap()): on a fresh session with no `?following=`
                           #     query param, a script checks localStorage; if it finds saved data, it builds
                           #     an `<a href="...?following=...">` element IN THE PARENT DOCUMENT (via
                           #     window.parent.document, allowed since the sandboxed iframe grants
                           #     allow-same-origin) and clicks it there — NOT `window.parent.location.href =`,
                           #     which is silently blocked because components.html()'s iframe sandbox lacks
                           #     allow-top-navigation. One extra page load follows; bootstrap() then reads the
                           #     query param into session_state and never re-reads it (session_state becomes
                           #     authoritative from then on).
                           #   - SAVE (Python->JS, following.save()): called unconditionally near the top of
                           #     this page, writes current session_state into localStorage. Guarded by a
                           #     `_following_safe_to_save` session_state flag that bootstrap() only sets True
                           #     from the SECOND render of a session onward — on the very first render of a
                           #     fresh session, the "no data yet" placeholder empty lists are still pending the
                           #     possible localStorage-redirect above, and saving immediately would clobber real
                           #     saved data with that empty placeholder before the browser gets a chance to run
                           #     the redirect.
                           #
                           # Trade-off: genuinely personal with no auth, but doesn't follow the visitor across
                           # devices/browsers (unlike the earlier SQLite-backed version this replaced, which
                           # was shared across every visitor — wrong for a multi-user public dashboard).
    _Player.py      # Player profile view — NOT reached via its own nav tab; driven by st.session_state
                     # ("selected_mlbID"/"selected_name"/"selected_season") set by sidebar.render_search(),
                     # navigated to via st.switch_page("pages/_Player.py"). Excluded from the visible sidebar
                     # nav (see "Navigation" below) — it's registered as a valid destination but has no
                     # page_link, so it's reachable only via the search box. Visiting it directly with no
                     # prior search shows a "use the sidebar search" prompt instead of erroring.
    _Article.py      # Full-article view for one Daily Digest storyline — same hidden-page pattern as
                     # _Player.py. Reads st.session_state["selected_article"] (the whole article dict, not
                     # just an id — nothing to re-fetch/re-generate) and renders headline/photo/team badge
                     # plus each of the 3 paragraphs. A "← Back to Daily Digest" button switches back.
                     # Visiting it directly with nothing selected shows a prompt instead of erroring.
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
- **Statcast enrichment**: exit velocity, barrel%, xwOBA/xBA/xSLG (batting) and xERA/xBA_against/xSLG_against/xwOBA_against (pitching), merged in by `mlbID`. Each expected-stat leaderboard also ships an actual-minus-expected diff column, which we keep too (`xBA_diff`/`xSLG_diff`/`xwOBA_diff` for batting, `xERA_diff` for pitching) — positive means outperforming the underlying contact quality, negative means better luck than the batted-ball data supports.
- **WAR**: `pybaseball.bwar_bat` / `bwar_pitch` (Baseball-Reference's separate WAR daily file, not part of `*_stats_bref`). Keyed by `mlb_ID`, one row per stint — a player traded mid-season has multiple rows for the same year, so `fetch_war()` sums `WAR` across stints (`groupby(...).sum(min_count=1)`, so a player with zero numeric rows stays `NaN` instead of becoming a false `0`). Covers all historical years in one fetch (unlike the current-season-only baserunning-run-value leaderboard), so no season-specific caveat needed.
- **OPS+/wRC+/ERA+**: computed locally (`add_batting_plus_stats`/`add_pitching_plus_stats` in `ingest/refresh_data.py`), NOT pulled from Baseball-Reference or FanGraphs — 100 is league average, higher is better. League averages are PA-weighted (batting) / IP-and-ER-weighted (pitching) means across that same season's full fetched player pool, not a separate leaderboard call. Deliberate simplification: **no park-factor adjustment**, unlike the "real" published versions of these stats — we don't have a park-factors source wired up. `wRC+` also uses a fixed `wOBA_scale = 1.20` approximation rather than FanGraphs' per-season guts constant.
- **Fielding**: `statcast_outs_above_average` (OAA/FRP), keyed by `player_id`.
- **Recent-performance windows** (`recent_batting` / `recent_pitching` tables): date-range pulls via `batting_stats_range` / `pitching_stats_range` for yesterday / last 7 days / last 30 days, feeding the Home page's "Headliners" cards. Day-window batting ranks by **Total Bases**, not OPS (single-game OPS is noise); week/month rank by OPS. Day-window pitching ranks by **Game Score**; week/month by ERA with a minimum-IP bar.
- **`player_history`**: the only **append-only** table (all others use `if_exists="replace"` each run). One row per player per day: season-to-date OPS/ERA (powers the Search page's trend chart) plus `day_PA`/`day_H`/`day_IP`/`day_ER` — that single day's line, reused from the recent-performance fetch rather than a new network call (powers hit-streak / scoreless-streak tracking; a day with no game has these as null, which streak logic treats as "skip," not "streak broken"). Today's rows are deleted-then-reinserted first so re-running the script same-day doesn't duplicate. Only has data from whenever each feature shipped onward — no historical backfill. If you add columns to this table later, add a schema-migration check in `fetch_and_store()` (drop-and-recreate if an old copy lacks the new column) since `to_sql(if_exists="append")` requires an exact column match. When querying it with a raw SQL param, always cast `mlbID` to `int()` first — pandas hands back `numpy.int32`, and sqlite3 silently returns zero rows (no error) if you bind that directly instead of a native Python int.
- **`todays_games`**: fetched from the free public **MLB Stats API** (`statsapi.mlb.com`, no key needed) — the only data source in this app that isn't pybaseball/Baseball-Reference/Statcast. Full replace every run (today's schedule only, not historical); an off day correctly produces an empty table rather than stale games from a prior day. Includes `venue` (game location) alongside team records and probable pitchers. Powers the Today's Games page: `db.predict_game()` computes a win probability starting from Log5 (team win%) + a home-field-advantage constant, then layers on starting-pitcher ERA, bullpen ERA (`team_bullpen_era`, relievers = `GS==0`), lineup wOBA (`team_lineup_woba`, PA-weighted), and a platoon-split estimate (`_platoon_shift`) — each lineup's handedness mix, from its depth chart's 9 position-player slots (`load_depth_chart` hydrates `batSide` for this), against the opposing starter's throwing hand (`load_pitcher_handedness`, one batched `/api/v1/people?personIds=...` call covering every probable pitcher for the day). The platoon piece deliberately uses the league-average same-handed penalty rather than real per-player vs-LHP/vs-RHP splits — pybaseball's `get_splits()` is one Baseball-Reference scrape *per player*, and doing that for every batter in every lineup, every day, would almost certainly retrigger the rate-limiting bref already hit once this project (see the git history around the xERA/BAbip/GB_FB backfill). `pitching`/`batting` passed into `predict_game()` need `teams.add_team_abbr()` already applied for the bullpen/lineup/platoon factors to run at all; a `todays_games` abbreviation like `"AZ"` needs `teams.normalize_mlb_abbr()` before comparing against a bref-derived one (`"ARI"`). These are all estimates calculated by this app, not real sportsbook odds — no betting-odds API is involved, and there's still no park factors, injuries, or weather.
- **`standings`**: also MLB Stats API, current division standings, full replace every run. Division IDs aren't returned as plain strings by the API — `DIVISION_NAMES` in `refresh_data.py` hardcodes the id->name mapping.
- **Depth chart (starting lineup diamond) is also NOT part of the daily ingest** — `db.load_depth_chart(team_id)` hits `/api/v1/teams/{id}/roster?rosterType=depthChart` live (6-hour TTL cache), returning the current starter at each defensive position plus the rotation's #1 starting pitcher. Team abbreviation -> MLB team id mapping lives in `teams._TEAM_IDS` / `teams.team_id_for_abbr()`. Rendered by `style.baseball_diamond()` on the Team page — a field image (`app/assets/baseballfield.png`, embedded as a base64 data URI since Streamlit has no route to serve a local file into custom HTML) with photo/name cards positioned by x%/y%, measured directly from that image's pixels. Reflects the team's *current* roster, not the season selected on that page.
- **Composite teams (All MLB / All Month, also on the Team page)** are built by `db.build_composite_team(season, mtime, scope)` — best qualified player at each of the 7 non-battery positions (min `db._COMPOSITE_MIN_PA` PA, 150), sourced from the `fielding` table's `Pos` column (Statcast primary position) joined against `batting` (or `recent_batting` "month" rows for the month scope). Catcher has no equivalent stats-based position source (Statcast OAA excludes the battery), so `db.load_league_catchers()` derives it by pulling every team's catcher off their live depth chart instead. DH goes to the best remaining bat by OPS not already used elsewhere on the roster. SP/RP are picked separately (min `db._COMPOSITE_MIN_IP`/`db._COMPOSITE_MIN_RP_IP` IP) using the pitching table's `GS` (games started) column — `GS>0` for SP, `GS==0` for RP — so a low-IP reliever can't win the SP spot; `recent_pitching` has no GS column, so the month scope joins it against the season table's GS just to classify each pitcher. Note `recent_pitching.mlbID` is stored as **text** in SQLite (every other table's `mlbID` is numeric) — cast it before merging on it, or pandas raises. Real teams' RP card comes from `load_depth_chart`'s "CP" (closer) entry, renamed to "RP" — but a team using closer-by-committee (no set closer) has no "CP" entry on the live depth chart at all, so `4_Team.py` falls back to that season's highest-IP reliever (`GS==0`, sorted by `IP` descending) rather than leaving the slot blank.
- **Live scores and box scores are NOT part of the daily ingest** — both are fetched live, on-demand, from the app itself (not `refresh_data.py`), since scores change constantly through the day and pre-fetching them once at 6am would be instantly stale. `db.load_live_scores(date_str)` does one schedule API call (`hydrate=linescore`) covering every game at once, short TTL (~20s) cache, used for the score shown on every game card. `db.load_linescore(game_pk)` is a per-game detailed box score (inning-by-inning), fetched only when a user clicks "Show box score" for that specific game — button-gated so it doesn't fire for all games on every page load.
- There used to be a `prediction_history` table + Prediction Accuracy page tracking this app's predictions against real outcomes — removed per user request. If resurrecting it, the previous implementation's git history has the resolve/lock-in logic (and a real bug it's worth not repeating: never delete-and-reinsert a whole date's rows when storing new predictions, since that wipes out `actual_winner`/scores already resolved for other games sharing that date — only insert genuinely new `game_pk`s).
- **Multi-season data**: `batting`/`pitching`/`fielding` are keyed by `season` and written via DELETE-then-append per season (`_store_season_table()`), not a full-table replace — so backfilling historical seasons doesn't wipe the current one. Daily refresh only ever touches `CURRENT_SEASON`; add a historical year with `./venv/bin/python ingest/refresh_data.py --backfill <year>`, one year per invocation (deliberately not batched, to keep peak memory the same as a normal daily run on a memory-constrained machine — see "Known issues"). `recent_batting`/`recent_pitching`/`player_history`/`todays_games` are current-day/current-season concepts only and aren't backfilled.
- **Known data quirks handled in ingest**: Baseball-Reference leaves W/L/SV blank (not 0) for pitchers with none — filled to 0. Accented names (Acuña, Hernández) and escaped apostrophes (d'Arnaud) sometimes arrive as literal escape text from bref's scraper — fixed via `fix_mojibake_names`. MLB Stats API uses team abbreviation `AZ`; every other source in this app (including `teams.py`) uses `ARI` — remap before doing a color/abbreviation lookup (see `teams.normalize_mlb_abbr()`).

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
