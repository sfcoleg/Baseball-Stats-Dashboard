"""Build data/nfl.db from nflverse (via nflreadpy).

Deliberately a separate database from stats.db and nhl.db: the three sports
share no keys, no schema and no refresh cadence, and keeping them apart means
a bad NFL run can't take the baseball site down with it.

Source note: nflverse publishes static parquet on GitHub releases, so there
is no key, no rate limit and no scraper to break — the same reason the
FanGraphs route was refused. `python ingest/nfl_refresh.py` rebuilds; add
--check to ask whether a refresh is needed (see refresh_data.py, which uses
the same outcome-based guard).
"""
from __future__ import annotations  # see the try/except below for why

import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from _dates import pacific_today

# Same fix, same reason, as refresh_data.py: --check is invoked by the
# workflow BEFORE "Install dependencies" runs, on purpose, so a day that
# needs nothing skips the expensive install. A plain top-level
# `import pandas` crashed that invocation on the bare runner every time —
# confirmed by running this exact command through an interpreter with no
# packages installed, which dies here at exit code 1 — and the workflow's
# `if python ...; then` read that crash as "nothing to do". This is the
# MLB half of the same bug; nflreadpy itself was already made lazy (see
# _nfl() below), but this top-level pandas import was still eager and
# still crashed --check on its own.
try:
    import pandas as pd
except ImportError:
    pd = None

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "nfl.db"

# How far back to build. Every table here is small (a season is ~285 games and
# ~570 team-weeks), so depth is cheap; the limit is really about keeping the
# committed database small enough to move around comfortably.
FIRST_SEASON = 2016


def current_season() -> int:
    """The NFL season year, which is the year it STARTS.

    A season runs September to February, so January and February belong to
    the previous year's season. The league year turns over in March, and the
    schedule for the coming season is published in May — using March as the
    boundary means the new season becomes "current" as soon as it exists as a
    thing to have data about, rather than only once games are played."""
    today = pacific_today()
    return today.year if today.month >= 3 else today.year - 1


def _nfl():
    """Import nflreadpy only when data is actually being fetched.

    --check just reads SQLite to decide whether a refresh is needed, and the
    workflow runs it BEFORE installing this dependency — a module-level
    import would make the guard fail, report "no refresh needed", and quietly
    never update NFL data at all."""
    import nflreadpy
    return nflreadpy


def _frame(loaded) -> pd.DataFrame:
    """nflreadpy returns polars; the rest of this project speaks pandas."""
    return loaded.to_pandas() if hasattr(loaded, "to_pandas") else loaded


def fetch_teams() -> pd.DataFrame:
    """Team identity: abbreviation, name, conference, division, colours and
    logo URLs. Includes historical relocations (36 rows for 32 clubs), which
    is why the app keys on abbreviation rather than assuming 32."""
    teams = _frame(_nfl().load_teams())
    keep = [
        "team_abbr", "team_name", "team_nick", "team_conf", "team_division",
        "team_color", "team_color2", "team_logo_espn", "team_wordmark",
    ]
    return teams[[c for c in keep if c in teams.columns]].copy()


def fetch_games(seasons: list[int]) -> pd.DataFrame:
    """Every scheduled game, played or not. Unplayed games carry null scores,
    which is what separates "hasn't happened" from "0-0" downstream."""
    games = _frame(_nfl().load_schedules(seasons=seasons))
    keep = [
        "game_id", "season", "game_type", "week", "gameday", "weekday", "gametime",
        "away_team", "away_score", "home_team", "home_score", "result", "total",
        "overtime", "div_game", "roof", "surface", "temp", "wind",
        "away_qb_name", "home_qb_name", "away_coach", "home_coach", "stadium",
    ]
    return games[[c for c in keep if c in games.columns]].copy()


def fetch_team_weeks(seasons: list[int]) -> pd.DataFrame:
    """Per-team, per-week box score totals — including EPA and CPOE, which is
    what makes this worth storing rather than deriving from the scoreboard.

    Fetched season by season on purpose. nflverse publishes one parquet per
    season and does not create the file until that season has games, so the
    upcoming season 404s all summer — and a single combined request makes
    that one missing file fail every other season with it. Per season, a gap
    costs only that season."""
    frames = []
    for year in seasons:
        try:
            frames.append(_frame(_nfl().load_team_stats(seasons=[year])))
        except Exception as exc:
            reason = "not published yet" if "404" in str(exc) else type(exc).__name__
            print(f"  team stats {year}: skipped ({reason})")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# The columns worth storing. load_player_stats returns 150; most are
# fantasy-scoring variants and long-tail splits that no page here reads, and
# a decade of weekly rows at full width would make the committed database
# several times larger than the other two sports put together.
PLAYER_COLS = [
    "player_id", "player_display_name", "position", "position_group",
    "headshot_url", "season", "week", "season_type", "team", "opponent_team",
    "completions", "attempts", "passing_yards", "passing_tds",
    "passing_interceptions", "sacks_suffered", "passing_epa", "passing_cpoe",
    "passing_first_downs",
    "carries", "rushing_yards", "rushing_tds", "rushing_fumbles_lost",
    "rushing_epa", "rushing_first_downs",
    "receptions", "targets", "receiving_yards", "receiving_tds",
    "receiving_epa", "receiving_air_yards", "receiving_yards_after_catch",
    "receiving_first_downs", "target_share",
    "fantasy_points_ppr",
    # Kicking. Distance buckets matter more than a raw make percentage here:
    # a kicker who only attempts chip shots and a kicker asked for 50-yarders
    # can post the same fg_pct while being very different kickers.
    "fg_att", "fg_made", "fg_missed", "fg_blocked", "fg_long",
    "fg_made_40_49", "fg_made_50_59", "fg_made_60_",
    "fg_missed_40_49", "fg_missed_50_59", "fg_missed_60_",
    "pat_att", "pat_made", "gwfg_att", "gwfg_made",
]

# Weekly rows are kept only for the newest few seasons. A game log is a
# "what did he do lately" view, while leaderboards and career lines come off
# the season aggregates below — so older weekly detail costs size without
# serving a page.
WEEKLY_SEASONS = 3

# Everything that should be summed when weeks are rolled up into a season.
# Rates (EPA per play, CPOE, target share) are deliberately absent: summing
# them is meaningless, so they are re-derived or averaged instead.
_SUM_COLS = [
    "fg_att", "fg_made", "fg_missed", "fg_blocked",
    "fg_made_40_49", "fg_made_50_59", "fg_made_60_",
    "fg_missed_40_49", "fg_missed_50_59", "fg_missed_60_",
    "pat_att", "pat_made", "gwfg_att", "gwfg_made",
    "completions", "attempts", "passing_yards", "passing_tds",
    "passing_interceptions", "sacks_suffered", "passing_epa", "passing_first_downs",
    "carries", "rushing_yards", "rushing_tds", "rushing_fumbles_lost",
    "rushing_epa", "rushing_first_downs",
    "receptions", "targets", "receiving_yards", "receiving_tds",
    "receiving_epa", "receiving_air_yards", "receiving_yards_after_catch",
    "receiving_first_downs", "fantasy_points_ppr",
]


def fetch_player_weeks(seasons: list[int]) -> pd.DataFrame:
    """Weekly per-player lines. Fetched season by season for the same reason
    team stats are: the upcoming season's file does not exist yet."""
    frames = []
    for year in seasons:
        try:
            df = _frame(_nfl().load_player_stats(seasons=[year]))
        except Exception as exc:
            reason = "not published yet" if "404" in str(exc) else type(exc).__name__
            print(f"  player stats {year}: skipped ({reason})")
            continue
        frames.append(df[[c for c in PLAYER_COLS if c in df.columns]].copy())
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_id_crosswalk() -> pd.DataFrame:
    """gsis_id <-> pfr_id, so Pro-Football-Reference's advanced stats can be
    joined to everything else.

    PFR keys on its own player id and carries no gsis_id, while every other
    table here keys on gsis. nflverse's players table holds both for 22.5k of
    25k players, which is the only reason these two worlds can be joined at
    all — without it the defensive stats would be stranded."""
    players = _frame(_nfl().load_players())
    keep = [c for c in ("gsis_id", "pfr_id", "display_name", "position") if c in players.columns]
    out = players[keep].dropna(subset=["gsis_id", "pfr_id"])
    return out.rename(columns={"gsis_id": "player_id"})


def fetch_nextgen(seasons: list[int]) -> pd.DataFrame:
    """Next Gen Stats season totals for all three offensive stat types.

    NGS ships weekly rows plus a week=0 row that IS the season total, so the
    filter below is what makes these leaderboard-ready rather than a pile of
    weeks to re-aggregate — and re-aggregating would be wrong anyway, since
    averages like separation and time to throw are not summable."""
    frames = []
    for kind in ("passing", "rushing", "receiving"):
        for year in seasons:
            try:
                df = _frame(_nfl().load_nextgen_stats(seasons=[year], stat_type=kind))
            except Exception as exc:
                reason = "not published yet" if "404" in str(exc) else type(exc).__name__
                print(f"  nextgen {kind} {year}: skipped ({reason})")
                continue
            if df.empty or "week" not in df.columns:
                continue
            season_rows = df[df["week"] == 0].copy()
            season_rows["ngs_type"] = kind
            frames.append(season_rows)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    if "player_gsis_id" in combined.columns:
        combined = combined.rename(columns={"player_gsis_id": "player_id"})
    return combined


def fetch_pfr_advanced(seasons: list[int], crosswalk: pd.DataFrame) -> pd.DataFrame:
    """Pro-Football-Reference's advanced season stats, keyed back to gsis.

    "def" is the valuable one: it is the only per-player defensive data here,
    covering coverage (targets, completions and passer rating allowed) and
    pass rush (hurries, knockdowns, sacks) for roughly a thousand players a
    season. Without it the site has no defensive stats at all."""
    frames = []
    for kind in ("pass", "rush", "rec", "def"):
        for year in seasons:
            try:
                df = _frame(_nfl().load_pfr_advstats(
                    seasons=[year], stat_type=kind, summary_level="season"))
            except Exception as exc:
                reason = "not published yet" if "404" in str(exc) else type(exc).__name__
                print(f"  pfr {kind} {year}: skipped ({reason})")
                continue
            if df.empty:
                continue
            df = df.copy()
            df["pfr_type"] = kind
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    if not crosswalk.empty and "pfr_id" in combined.columns:
        combined = combined.merge(
            crosswalk[["player_id", "pfr_id"]].drop_duplicates("pfr_id"),
            on="pfr_id", how="left",
        )
    return combined


def build_player_seasons(weeks: pd.DataFrame) -> pd.DataFrame:
    """Season totals per player, per season type.

    Regular season and playoffs stay separate rows rather than being merged:
    a leaderboard means the regular season, and silently folding in playoff
    games would flatter whoever went deepest."""
    if weeks.empty:
        return pd.DataFrame()
    keys = ["player_id", "player_display_name", "position", "position_group",
            "headshot_url", "season", "season_type"]
    sums = {c: (c, "sum") for c in _SUM_COLS if c in weeks.columns}
    # fg_long is the longest kick of the season, so it maxes rather than sums —
    # summing it would produce a meaningless four-digit "distance".
    extra = {"fg_long": ("fg_long", "max")} if "fg_long" in weeks.columns else {}
    agg = weeks.groupby(keys, as_index=False, dropna=False).agg(
        games=("week", "nunique"),
        **extra,
        # A player's team can change mid-season; the last one he appears for
        # is the one a leaderboard should show him under.
        team=("team", "last"),
        **sums,
    )
    # Rates are re-derived from the totals rather than averaged across weeks,
    # so a one-play game cannot weigh the same as a full one.
    if {"passing_epa", "attempts"} <= set(agg.columns):
        agg["passing_epa_per_att"] = agg["passing_epa"] / agg["attempts"].replace(0, pd.NA)
    if {"rushing_epa", "carries"} <= set(agg.columns):
        agg["rushing_epa_per_carry"] = agg["rushing_epa"] / agg["carries"].replace(0, pd.NA)
    if {"receiving_epa", "targets"} <= set(agg.columns):
        agg["receiving_epa_per_target"] = agg["receiving_epa"] / agg["targets"].replace(0, pd.NA)
    if {"completions", "attempts"} <= set(agg.columns):
        agg["completion_pct"] = 100 * agg["completions"] / agg["attempts"].replace(0, pd.NA)
    if {"passing_yards", "attempts"} <= set(agg.columns):
        agg["yards_per_attempt"] = agg["passing_yards"] / agg["attempts"].replace(0, pd.NA)
    if {"rushing_yards", "carries"} <= set(agg.columns):
        agg["yards_per_carry"] = agg["rushing_yards"] / agg["carries"].replace(0, pd.NA)
    if {"receiving_yards", "receptions"} <= set(agg.columns):
        agg["yards_per_reception"] = agg["receiving_yards"] / agg["receptions"].replace(0, pd.NA)
    # CPOE is a rate already; weight it by attempts rather than by week.
    # Field-goal percentage from the season totals, not averaged across weeks.
    if {"fg_made", "fg_att"} <= set(agg.columns):
        agg["fg_pct"] = 100 * agg["fg_made"] / agg["fg_att"].replace(0, pd.NA)
    # Kicks from 40+ are where kickers actually separate, so this is surfaced
    # as its own rate rather than left buried in the buckets.
    long_made = [c for c in ("fg_made_40_49", "fg_made_50_59", "fg_made_60_") if c in agg.columns]
    long_missed = [c for c in ("fg_missed_40_49", "fg_missed_50_59", "fg_missed_60_") if c in agg.columns]
    if long_made and long_missed:
        made = agg[long_made].fillna(0).sum(axis=1)
        attempted = made + agg[long_missed].fillna(0).sum(axis=1)
        agg["fg_long_made"] = made
        agg["fg_long_att"] = attempted
        agg["fg_long_pct"] = 100 * made / attempted.replace(0, pd.NA)

    if {"passing_cpoe", "attempts"} <= set(weeks.columns):
        weighted = weeks.assign(_w=weeks["passing_cpoe"] * weeks["attempts"])
        cpoe = weighted.groupby(keys, as_index=False, dropna=False).agg(
            _num=("_w", "sum"), _den=("attempts", "sum")
        )
        cpoe["passing_cpoe"] = cpoe["_num"] / cpoe["_den"].replace(0, pd.NA)
        agg = agg.merge(cpoe[keys + ["passing_cpoe"]], on=keys, how="left")
    # Dividing by a pd.NA-masked denominator yields an OBJECT column, which
    # SQLite then stores as TEXT — and a text column formatted as a float
    # raises at render time. Coerce every derived rate back to a real float
    # before it is written.
    derived = [
        "passing_epa_per_att", "rushing_epa_per_carry", "receiving_epa_per_target",
        "completion_pct", "yards_per_attempt", "yards_per_carry",
        "yards_per_reception", "passing_cpoe",
        "fg_pct", "fg_long_pct", "fg_long_made", "fg_long_att",
    ]
    for column in derived:
        if column in agg.columns:
            agg[column] = pd.to_numeric(agg[column], errors="coerce")
    return agg


def build_standings(games: pd.DataFrame, teams: pd.DataFrame, season: int) -> pd.DataFrame:
    """Win/loss/tie records for one season, derived from played games.

    nflverse ships no standings table, so this counts them. Only REGULAR
    season games count toward a record — playoff results are not part of it,
    and preseason never is."""
    played = games[
        (games["season"] == season)
        & (games["game_type"] == "REG")
        & games["home_score"].notna()
        & games["away_score"].notna()
    ]
    rows = []
    for _, g in played.iterrows():
        for side, opp in (("home", "away"), ("away", "home")):
            pf, pa = g[f"{side}_score"], g[f"{opp}_score"]
            rows.append({
                "team": g[f"{side}_team"],
                "win": int(pf > pa), "loss": int(pf < pa), "tie": int(pf == pa),
                "points_for": pf, "points_against": pa,
                "div_game": int(g.get("div_game") or 0),
                "div_win": int(pf > pa) if g.get("div_game") else 0,
                "div_loss": int(pf < pa) if g.get("div_game") else 0,
            })
    if not rows:
        return pd.DataFrame()

    per_game = pd.DataFrame(rows)
    table = per_game.groupby("team", as_index=False).agg(
        wins=("win", "sum"), losses=("loss", "sum"), ties=("tie", "sum"),
        points_for=("points_for", "sum"), points_against=("points_against", "sum"),
        div_wins=("div_win", "sum"), div_losses=("div_loss", "sum"),
    )
    table["games"] = table["wins"] + table["losses"] + table["ties"]
    # A tie counts as half a win, which is how the NFL orders its own tables.
    table["win_pct"] = (table["wins"] + 0.5 * table["ties"]) / table["games"].replace(0, pd.NA)
    table["point_diff"] = table["points_for"] - table["points_against"]
    table["season"] = season

    meta = teams[["team_abbr", "team_name", "team_conf", "team_division"]]
    return table.merge(meta, left_on="team", right_on="team_abbr", how="left").drop(columns=["team_abbr"])


def record_refresh(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS refresh_log (date TEXT PRIMARY KEY, finished_at TEXT)")
    conn.execute(
        "INSERT OR REPLACE INTO refresh_log VALUES (?, ?)",
        (pacific_today().isoformat(),
         datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )


def data_is_current() -> bool:
    """Whether every game that has already kicked off has a score stored.

    Outcome-based, like refresh_data.py's guard, and for the same reason: a
    scheduled run that fires late should still do the work rather than skip
    because the calendar moved. Off-days are the norm in the NFL, so this
    asks about results rather than about dates."""
    if not DB_PATH.exists():
        return False
    try:
        with sqlite3.connect(DB_PATH) as conn:
            missing = conn.execute(
                "SELECT COUNT(*) FROM games WHERE gameday < ? AND home_score IS NULL",
                (pacific_today().isoformat(),),
            ).fetchone()[0]
    except sqlite3.Error:
        return False
    return missing == 0


def fetch_and_store() -> None:
    DB_PATH.parent.mkdir(exist_ok=True)
    season = current_season()
    seasons = list(range(FIRST_SEASON, season + 1))
    print(f"NFL refresh: seasons {seasons[0]}-{seasons[-1]}")

    teams = fetch_teams()
    print(f"  teams: {len(teams)}")
    games = fetch_games(seasons)
    print(f"  games: {len(games)}")
    if games.empty:
        # Without the schedule there is nothing to build standings from, and
        # overwriting good tables with empty ones would be worse than doing
        # nothing at all.
        print("  no schedule data — leaving the database untouched")
        return
    team_weeks = fetch_team_weeks(seasons)
    print(f"  team-weeks: {len(team_weeks)}")

    player_weeks = fetch_player_weeks(seasons)
    print(f"  player-weeks: {len(player_weeks)}")
    player_seasons = build_player_seasons(player_weeks)
    print(f"  player-seasons: {len(player_seasons)}")
    # Only the newest few seasons keep their weekly detail — see WEEKLY_SEASONS.
    recent = seasons[-WEEKLY_SEASONS:]
    player_weeks_recent = (
        player_weeks[player_weeks["season"].isin(recent)] if not player_weeks.empty else player_weeks
    )
    print(f"  player-weeks kept ({recent[0]}-{recent[-1]}): {len(player_weeks_recent)}")

    crosswalk = fetch_id_crosswalk()
    print(f"  id crosswalk: {len(crosswalk)}")
    nextgen = fetch_nextgen(seasons)
    print(f"  next gen stats: {len(nextgen)}")
    pfr_adv = fetch_pfr_advanced(seasons, crosswalk)
    print(f"  pfr advanced: {len(pfr_adv)}"
          + (f" ({int(pfr_adv['player_id'].notna().sum())} matched to gsis)" if not pfr_adv.empty else ""))

    standings = pd.concat(
        [s for s in (build_standings(games, teams, yr) for yr in seasons) if not s.empty],
        ignore_index=True,
    ) if seasons else pd.DataFrame()
    print(f"  standings rows: {len(standings)}")

    with sqlite3.connect(DB_PATH) as conn:
        teams.to_sql("teams", conn, if_exists="replace", index=False)
        games.to_sql("games", conn, if_exists="replace", index=False)
        team_weeks.to_sql("team_week_stats", conn, if_exists="replace", index=False)
        if not player_seasons.empty:
            player_seasons.to_sql("player_season_stats", conn, if_exists="replace", index=False)
        if not player_weeks_recent.empty:
            player_weeks_recent.to_sql("player_week_stats", conn, if_exists="replace", index=False)
        if not nextgen.empty:
            nextgen.to_sql("nextgen_stats", conn, if_exists="replace", index=False)
        if not pfr_adv.empty:
            pfr_adv.to_sql("pfr_advanced", conn, if_exists="replace", index=False)
        if not standings.empty:
            standings.to_sql("standings", conn, if_exists="replace", index=False)
        record_refresh(conn)
        conn.commit()
    print(f"Wrote {DB_PATH}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        current = data_is_current()
        print("data is current" if current else "refresh needed")
        sys.exit(1 if current else 0)
    fetch_and_store()
