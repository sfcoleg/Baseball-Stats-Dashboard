"""
Fetches current-season MLB stats from Baseball-Reference and Baseball Savant
(Statcast) via pybaseball, computes additional sabermetrics, and saves
everything into a local SQLite database (data/stats.db).

Note: we use Baseball-Reference (*_bref) rather than FanGraphs for base
batting/pitching stats, because FanGraphs currently blocks pybaseball's
requests (403 errors from their bot protection). Baseball-Reference and
Baseball Savant (Statcast) both work reliably.

Run this once a day to keep the dashboard up to date:
    ./venv/bin/python ingest/refresh_data.py
"""
import codecs
import io
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
from pybaseball import (
    batting_stats_bref,
    pitching_stats_bref,
    batting_stats_range,
    pitching_stats_range,
    bwar_bat,
    bwar_pitch,
    statcast_batter_exitvelo_barrels,
    statcast_batter_expected_stats,
    statcast_batter_percentile_ranks,
    statcast_pitcher_exitvelo_barrels,
    statcast_pitcher_expected_stats,
    statcast_pitcher_percentile_ranks,
    statcast_outs_above_average,
    statcast_sprint_speed,
)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "stats.db"
CURRENT_SEASON = date.today().year

# app/teams.py's nickname->abbreviation lookup, reused here so standings
# rows get a team_abbr without duplicating the mapping.
sys.path.append(str(Path(__file__).resolve().parent.parent / "app"))
import teams as app_teams  # noqa: E402

# MLB Stats API division IDs -> readable names (not included as a plain
# string in the standings payload, only as a numeric id).
DIVISION_NAMES = {
    200: "AL West", 201: "AL East", 202: "AL Central",
    203: "NL West", 204: "NL East", 205: "NL Central",
}

# Minimum plate appearances / innings pitched required to qualify as a
# "headliner" for each recent-performance window (keeps tiny-sample noise
# out of the day window in particular).
RECENT_MIN_PA = {"day": 3, "week": 15, "month": 50}
RECENT_MIN_IP = {"day": 1, "week": 8, "month": 20}

# wOBA linear weights (~2023-2024 era constants); used only as a fallback
# where Statcast's actual wOBA isn't available for a player.
WOBA_WEIGHTS = dict(bb=0.696, hbp=0.726, single=0.883, double=1.244, triple=1.569, hr=2.004)

_MOJIBAKE_RE = re.compile(r"(?:\\x[0-9a-fA-F]{2})+")


def fix_mojibake_names(series):
    """Baseball-Reference's scraped tables sometimes render accented names
    (Acuña, Hernández, ...) as literal '\\xNN' escape text instead of the
    actual character. Decode those runs back to real UTF-8 text."""

    def fix_one(name):
        if not isinstance(name, str):
            return name
        name = name.replace("\\'", "'")
        if not _MOJIBAKE_RE.search(name):
            return name
        try:
            return codecs.decode(name, "unicode_escape").encode("latin1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return name

    return series.map(fix_one)


def add_batting_sabermetrics(df):
    singles = df["H"] - df["2B"] - df["3B"] - df["HR"]
    ab_bb_sf_hbp = df["AB"] + df["BB"] - df["IBB"] + df["SF"] + df["HBP"]

    df["ISO"] = df["SLG"] - df["BA"]
    babip_denom = (df["AB"] - df["SO"] - df["HR"] + df["SF"]).replace(0, float("nan"))
    df["BABIP"] = ((df["H"] - df["HR"]) / babip_denom).round(3)
    df["K_PCT"] = (df["SO"] / df["PA"] * 100).round(1)
    df["BB_PCT"] = (df["BB"] / df["PA"] * 100).round(1)
    woba_denom = ab_bb_sf_hbp.replace(0, float("nan"))
    df["wOBA_calc"] = (
        (
            WOBA_WEIGHTS["bb"] * (df["BB"] - df["IBB"])
            + WOBA_WEIGHTS["hbp"] * df["HBP"]
            + WOBA_WEIGHTS["single"] * singles
            + WOBA_WEIGHTS["double"] * df["2B"]
            + WOBA_WEIGHTS["triple"] * df["3B"]
            + WOBA_WEIGHTS["hr"] * df["HR"]
        )
        / woba_denom
    ).round(3)
    return df


def add_pitching_sabermetrics(df):
    fip_constant = 3.10
    df["K_9"] = (df["SO"] * 9 / df["IP"]).round(2)
    df["BB_9"] = (df["BB"] * 9 / df["IP"]).round(2)
    df["K_BB"] = (df["SO"] / df["BB"].replace(0, float("nan"))).round(2)
    df["FIP"] = (
        (13 * df["HR"] + 3 * (df["BB"] + df["HBP"]) - 2 * df["SO"]) / df["IP"] + fip_constant
    ).round(2)
    return df


def add_batting_plus_stats(df):
    """OPS+ and wRC+ (100 = league average, higher is better), computed from
    this same season's field rather than fetched from anywhere else, so they
    stay consistent with our own OBP/SLG/wOBA_calc numbers. Simplification:
    no park-factor adjustment (we don't have a park-factors source wired up),
    unlike FanGraphs/Baseball-Reference's published versions."""
    total_pa = df["PA"].sum()
    lg_obp = (df["OBP"] * df["PA"]).sum() / total_pa
    lg_slg = (df["SLG"] * df["PA"]).sum() / total_pa
    df["OPS_plus"] = (100 * (df["OBP"] / lg_obp + df["SLG"] / lg_slg - 1)).round(0)

    # wRC+: standard "runs created per PA, relative to league average" plus
    # stat. wOBA_scale converts wOBA points to runs; FanGraphs publishes an
    # exact value per season (recently ~1.20-1.25) — we use a fixed 1.20
    # approximation since we don't have their guts-constants feed.
    woba_scale = 1.20
    lg_woba = (df["wOBA_calc"] * df["PA"]).sum() / total_pa
    lg_r_pa = df["R"].sum() / total_pa
    wrc_per_pa = (df["wOBA_calc"] - lg_woba) / woba_scale + lg_r_pa
    df["wRC_plus"] = (100 * wrc_per_pa / lg_r_pa).round(0)
    return df


def add_pitching_plus_stats(df):
    """ERA+ (100 = league average, higher is better). Same no-park-factor
    simplification as OPS+/wRC+ above."""
    lg_era = df["ER"].sum() * 9 / df["IP"].sum()
    df["ERA_plus"] = (100 * lg_era / df["ERA"].replace(0, float("nan"))).round(0)
    return df


def fetch_war(is_pitcher, season):
    """Baseball-Reference's WAR (bwar_bat/bwar_pitch), keyed by mlb_ID. A
    player traded mid-season has one row per stint, so sum WAR across stints
    to get a season total — min_count=1 so a player with no numeric rows at
    all (older/legacy players lacking a WAR calc) stays NaN instead of 0."""
    raw = bwar_pitch() if is_pitcher else bwar_bat()
    raw = raw[raw["year_ID"] == season]
    war = raw.groupby("mlb_ID", as_index=False)["WAR"].sum(min_count=1)
    return war.rename(columns={"mlb_ID": "player_id"})


def fetch_savant_leaderboard_csv(path, year):
    """Fetch a Baseball Savant leaderboard CSV directly — some leaderboards
    (e.g. baserunning run value) aren't wrapped by pybaseball, but follow
    the same csv=true convention as the ones that are."""
    url = f"https://baseballsavant.mlb.com/leaderboard/{path}?year={year}&csv=true"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.content.decode("utf-8")))


def fetch_savant_custom_leaderboard(year, player_type, selections):
    """Fetch Baseball Savant's "custom leaderboard" builder as a CSV — one
    bulk call for the whole league (not per-player), whole-league RAW rates
    (unlike statcast_batter_percentile_ranks above, which returns each
    stat as a percentile rank vs. that season's league, not the literal
    rate). `selections` is a list of Savant's internal stat names (e.g.
    "whiff_percent"); confirmed against a known player (Arraez, 2025:
    5.3% whiff — matches his real elite contact skill) that this endpoint
    really does return raw percentages, not percentiles."""
    url = (
        f"https://baseballsavant.mlb.com/leaderboard/custom?year={year}&type={player_type}"
        f"&filter=&min=1&selections={','.join(selections)}&csv=true"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.content.decode("utf-8")))


def resolve_traded_player_current_teams(mlb_ids):
    """For players whose Baseball-Reference Tm is a comma-joined multi-team
    string (traded mid-season), resolve their TRUE current team via the MLB
    Stats API's currentTeam hydrate — BRef's comma order looks
    alphabetical-by-city rather than chronological, so trusting "the last
    entry is the most recent team" (the old behavior) is wrong as often as
    it's right. Returns {mlbID: bref-style city string}, one entry per id
    that resolved successfully; an id that fails at any step (network error,
    unexpected payload shape, unmappable team) is simply omitted so the
    caller can leave that row's original (possibly-stale) Tm alone rather
    than crash the whole ingest.

    A player currently optioned to a minor-league affiliate has a
    currentTeam that isn't one of the 30 MLB teams; in that case this
    resolves the affiliate's parent MLB organization instead (one extra
    request per distinct affiliate, cached across players within this call
    so the same affiliate is never looked up twice in one run)."""
    mlb_ids = sorted({int(i) for i in mlb_ids})
    if not mlb_ids:
        return {}

    current_team_id = {}
    CHUNK = 300
    for i in range(0, len(mlb_ids), CHUNK):
        chunk = mlb_ids[i:i + CHUNK]
        try:
            resp = requests.get(
                "https://statsapi.mlb.com/api/v1/people",
                params={
                    "personIds": ",".join(str(pid) for pid in chunk),
                    "hydrate": "currentTeam",
                },
                timeout=30,
            )
            resp.raise_for_status()
            people = resp.json().get("people", [])
        except Exception as e:
            print(f"  skipped a batch of {len(chunk)} traded-player team lookups ({e})")
            continue
        for p in people:
            team_id = p.get("currentTeam", {}).get("id")
            if team_id is not None:
                current_team_id[p["id"]] = team_id

    mlb_team_ids = set(app_teams._TEAM_IDS.values())
    parent_org_cache = {}
    resolved = {}
    for mlb_id, team_id in current_team_id.items():
        final_team_id = team_id
        if final_team_id not in mlb_team_ids:
            if team_id not in parent_org_cache:
                try:
                    resp = requests.get(
                        f"https://statsapi.mlb.com/api/v1/teams/{team_id}", timeout=30,
                    )
                    resp.raise_for_status()
                    affiliate_teams = resp.json().get("teams", [])
                    parent_org_cache[team_id] = affiliate_teams[0].get("parentOrgId") if affiliate_teams else None
                except Exception as e:
                    print(f"  skipped parent-org lookup for affiliate team {team_id} ({e})")
                    parent_org_cache[team_id] = None
            final_team_id = parent_org_cache[team_id]
        if final_team_id not in mlb_team_ids:
            continue
        abbr = app_teams.abbr_for_team_id(final_team_id)
        if abbr:
            # Tm and Lev must be resolved from the SAME abbreviation and
            # written back together — see correct_traded_player_teams for
            # why leaving Lev on its old (possibly comma-joined, possibly
            # wrong-league) value silently breaks the city->team lookup for
            # any shared city (New York, Chicago, Los Angeles).
            resolved[mlb_id] = (app_teams.city_for_abbr(abbr), f"Maj-{app_teams.league_for_abbr(abbr)}")
    return resolved


def correct_traded_player_teams(df):
    """Overwrite Tm/Lev for rows where Baseball-Reference reports a
    comma-joined multi-team string (a mid-season trade) with the player's
    true CURRENT team, resolved via resolve_traded_player_current_teams.

    Both columns are overwritten together, not just Tm: team_meta_from_city
    disambiguates a shared city (New York, Chicago, Los Angeles) using Lev,
    so if Lev were left as Baseball-Reference's original value — which for
    a traded player is itself comma-joined, e.g. "Maj-NL,Maj-AL" for a
    Giants-to-Yankees trade — _league_code's simple .endswith("AL") check
    can land on the WRONG league and silently resolve a Yankee to the Mets
    (or an Angel to the Dodgers, etc.). This is what caused Heliot Ramos and
    Luis García Jr. to show up as Mets after their trade to the Yankees.

    Best-effort: any row that fails to resolve keeps its original
    comma-joined Tm/Lev, which team_meta_from_city still handles (if
    imperfectly) via its last-comma-entry heuristic."""
    multi_team = df["Tm"].astype(str).str.contains(",", na=False)
    if not multi_team.any():
        return df
    ids = df.loc[multi_team, "mlbID"].dropna().astype(int).unique()
    print(f"  resolving current team for {len(ids)} traded player(s)...")
    resolved = resolve_traded_player_current_teams(ids)
    if resolved:
        mask = multi_team & df["mlbID"].isin(resolved.keys())
        resolved_tm = {mlb_id: tm for mlb_id, (tm, lev) in resolved.items()}
        resolved_lev = {mlb_id: lev for mlb_id, (tm, lev) in resolved.items()}
        df.loc[mask, "Tm"] = df.loc[mask, "mlbID"].map(resolved_tm)
        df.loc[mask, "Lev"] = df.loc[mask, "mlbID"].map(resolved_lev)
    return df


def fetch_batting(season=CURRENT_SEASON):
    print(f"Fetching {season} batting stats (Baseball-Reference)...")
    batting = batting_stats_bref(season)
    batting["Name"] = fix_mojibake_names(batting["Name"])
    batting = add_batting_sabermetrics(batting)

    print(f"Fetching {season} Statcast batted-ball data (batters)...")
    exitvelo = statcast_batter_exitvelo_barrels(season, minBBE=1)[
        ["player_id", "avg_hit_speed", "max_hit_speed", "ev95percent", "brl_percent"]
    ].rename(columns={
        "avg_hit_speed": "avg_exit_velo",
        "max_hit_speed": "max_exit_velo",
        "ev95percent": "hard_hit_pct",
        "brl_percent": "barrel_pct",
    })

    print(f"Fetching {season} Statcast expected stats (batters)...")
    expected = statcast_batter_expected_stats(season, minPA=1)[
        ["player_id", "woba", "est_woba", "est_ba", "est_slg",
         "est_ba_minus_ba_diff", "est_slg_minus_slg_diff", "est_woba_minus_woba_diff"]
    ].rename(columns={
        "woba": "wOBA",
        "est_woba": "xwOBA",
        "est_ba": "xBA",
        "est_slg": "xSLG",
        "est_ba_minus_ba_diff": "xBA_diff",
        "est_slg_minus_slg_diff": "xSLG_diff",
        "est_woba_minus_woba_diff": "xwOBA_diff",
    })

    print(f"Fetching {season} Statcast contact rate (batters)...")
    # statcast_batter_percentile_ranks returns PERCENTILE RANKS (0-100 vs.
    # that season's league), not raw rates — confirmed directly: Arraez
    # (an elite-contact hitter) came back with whiff_percent=100, a high-K
    # hitter came back near 0. Savant's own convention inverts "bad-when-
    # high" stats so 100 always means "best in the league" regardless of
    # stat direction — so this whiff_percent column already IS a contact
    # percentile (100 = least swing-and-miss) with no further inversion
    # needed; renamed to contact_pctile (not contact_pct) to make clear
    # it's a percentile rank, not a literal contact-rate percentage.
    # Confirmed (unlike baserunning-run-value below) that this endpoint
    # actually varies by the `season` argument rather than silently always
    # returning the current season.
    # chase_percent, bat_speed, xiso, xobp all ride along on the same call
    # as whiff_percent — one fetch, five percentile columns, not five
    # separate requests.
    contact = statcast_batter_percentile_ranks(season)[
        ["player_id", "whiff_percent", "chase_percent", "bat_speed", "xiso", "xobp"]
    ]
    contact = contact.rename(columns={
        "whiff_percent": "contact_pctile",
        "chase_percent": "chase_pctile",
        "bat_speed": "bat_speed_pctile",
        "xiso": "xISO_pctile",
        "xobp": "xOBP_pctile",
    })

    print(f"Fetching {season} Statcast raw contact/chase/bat-speed/xISO/xOBP rate (batters)...")
    # Literal numbers this time, not percentiles — see
    # fetch_savant_custom_leaderboard's docstring for how this differs from
    # the _pctile columns above. Both kept: the _pctile columns answer "how
    # does this compare to the league," these answer "what's the actual
    # number." oz_swing_percent (not "chase_percent") is this endpoint's
    # actual selection name for raw chase rate — confirmed by testing
    # several candidate names directly against the live endpoint. xiso/xobp
    # (lowercase, unlike est_ba/est_slg/est_woba used for xBA/xSLG/xwOBA
    # above) are this endpoint's actual raw-rate selection names —
    # confirmed real values (e.g. Judge .409 xISO, Arraez .076) against the
    # est_iso/est_obp names, which return empty.
    contact_raw = fetch_savant_custom_leaderboard(
        season, "batter", ["whiff_percent", "oz_swing_percent", "avg_swing_speed", "xiso", "xobp"]
    )[["player_id", "whiff_percent", "oz_swing_percent", "avg_swing_speed", "xiso", "xobp"]]
    contact_raw["contact_pct"] = 100 - contact_raw["whiff_percent"]
    contact_raw = contact_raw.drop(columns="whiff_percent").rename(columns={
        "oz_swing_percent": "chase_pct",
        "avg_swing_speed": "bat_speed",
        "xiso": "xISO",
        "xobp": "xOBP",
    })

    print(f"Fetching {season} WAR (Baseball-Reference)...")
    war = fetch_war(is_pitcher=False, season=season)

    print(f"Fetching {season} Statcast sprint speed...")
    sprint = statcast_sprint_speed(season, min_opp=1)[
        ["player_id", "sprint_speed", "hp_to_1b"]
    ]

    # Unlike sprint_speed, Baseball Savant's baserunning-run-value leaderboard
    # ignores the year param entirely and always returns the CURRENT season
    # (verified: requesting year=2022 and year=2026 return identical rows,
    # both stamped start_year/end_year=2026) — there's no historical query
    # available through this endpoint. Only fetch it when actually backfilling
    # the current season; a historical season gets an all-NaN column instead
    # of silently-wrong current-season values.
    if season == CURRENT_SEASON:
        print(f"Fetching {season} Statcast baserunning run value...")
        baserunning_value = fetch_savant_leaderboard_csv("baserunning-run-value", season)[
            ["player_id", "runner_runs_tot"]
        ].rename(columns={"runner_runs_tot": "baserunning_runs"})
    else:
        baserunning_value = pd.DataFrame({"player_id": pd.Series(dtype="float64"), "baserunning_runs": pd.Series(dtype="float64")})

    batting["mlbID"] = pd.to_numeric(batting["mlbID"], errors="coerce")
    for stats_df in (exitvelo, expected, contact, contact_raw, sprint, baserunning_value, war):
        batting = batting.merge(stats_df, left_on="mlbID", right_on="player_id", how="left")
        batting = batting.drop(columns="player_id")

    batting = correct_traded_player_teams(batting)
    batting = add_batting_plus_stats(batting)
    batting["season"] = season
    return batting


def fetch_pitching(season=CURRENT_SEASON):
    print(f"Fetching {season} pitching stats (Baseball-Reference)...")
    pitching = pitching_stats_bref(season)
    pitching["Name"] = fix_mojibake_names(pitching["Name"])
    # Baseball-Reference leaves W/L/SV blank instead of 0 when a pitcher has
    # no decisions/saves, which pandas reads in as NaN ("None" in the UI).
    pitching[["W", "L", "SV"]] = pitching[["W", "L", "SV"]].fillna(0).astype(int)
    # "GB/FB" has a slash, which is awkward as a bare column name elsewhere
    # (SQL, dict keys, URLs) — rename now rather than special-case it later.
    pitching = pitching.rename(columns={"GB/FB": "GB_FB"})
    pitching = add_pitching_sabermetrics(pitching)

    print(f"Fetching {season} Statcast batted-ball data (pitchers)...")
    exitvelo = statcast_pitcher_exitvelo_barrels(season, minBBE=1)[
        ["player_id", "avg_hit_speed", "ev95percent", "brl_percent"]
    ].rename(columns={
        "avg_hit_speed": "avg_exit_velo_against",
        "ev95percent": "hard_hit_pct_against",
        "brl_percent": "barrel_pct_against",
    })

    # xERA: Statcast's contact-quality-based expected ERA — the closest
    # equivalent this data source has to xFIP/SIERA. True xFIP needs a raw
    # fly-ball count and league HR/FB rate that neither Baseball-Reference
    # nor Statcast expose here (bref only gives a GB/FB *ratio*), so xERA is
    # used instead of trying to approximate xFIP from incomplete inputs. This
    # same leaderboard also has expected-contact-quality equivalents of
    # BA/SLG/wOBA against, so we're not limited to just xERA here.
    print(f"Fetching {season} Statcast expected stats (pitchers)...")
    expected = statcast_pitcher_expected_stats(season, minPA=1)[
        ["player_id", "xera", "est_ba", "est_slg", "est_woba", "era_minus_xera_diff"]
    ].rename(columns={
        "xera": "xERA",
        "est_ba": "xBA_against",
        "est_slg": "xSLG_against",
        "est_woba": "xwOBA_against",
        "era_minus_xera_diff": "xERA_diff",
    })

    print(f"Fetching {season} Statcast velocity/chase percentile (pitchers)...")
    # Same percentile-rank convention confirmed for the batter side above —
    # verified directly here too (Chapman/Skenes both came back with high
    # fb_velocity and chase_percent percentiles, matching their real
    # elite velocity/deception reputations), no inversion needed.
    stuff_pctile = statcast_pitcher_percentile_ranks(season)[
        ["player_id", "fb_velocity", "chase_percent"]
    ].rename(columns={"fb_velocity": "fastball_velo_pctile", "chase_percent": "induced_chase_pctile"})

    print(f"Fetching {season} Statcast raw velocity/chase rate (pitchers)...")
    # oz_swing_percent is this endpoint's actual selection name for raw
    # chase rate (same as the batter side) — here it's rate INDUCED by
    # the pitcher, higher is better for them (confirmed: Chapman/Skenes
    # both above league-average).
    stuff_raw = fetch_savant_custom_leaderboard(
        season, "pitcher", ["fastball_avg_speed", "oz_swing_percent"]
    )[["player_id", "fastball_avg_speed", "oz_swing_percent"]].rename(columns={
        "fastball_avg_speed": "fastball_velo",
        "oz_swing_percent": "induced_chase_pct",
    })

    print(f"Fetching {season} WAR (Baseball-Reference)...")
    war = fetch_war(is_pitcher=True, season=season)

    pitching["mlbID"] = pd.to_numeric(pitching["mlbID"], errors="coerce")
    for stats_df in (exitvelo, expected, stuff_pctile, stuff_raw, war):
        pitching = pitching.merge(stats_df, left_on="mlbID", right_on="player_id", how="left", suffixes=("", "_dup"))
        pitching = pitching.drop(columns=[c for c in pitching.columns if c.endswith("_dup") or c == "player_id"])

    pitching = correct_traded_player_teams(pitching)
    pitching = add_pitching_plus_stats(pitching)
    pitching["season"] = season
    return pitching


def fetch_arm_strength(season=CURRENT_SEASON):
    """Statcast's arm-strength leaderboard (average recorded throw velocity,
    mph, across every tracked throw) for every fielder. pybaseball has no
    wrapper for this specific leaderboard, so this hits Baseball Savant's
    CSV export directly — the same approach fetch_all_star_roster uses for
    an endpoint pybaseball doesn't cover."""
    try:
        resp = requests.get(
            "https://baseballsavant.mlb.com/leaderboard/arm-strength",
            params={"type": "Fielder", "year": season, "team": "", "drop": "",
                    "min": 1, "sort": 1, "sortDir": "desc", "csv": "true"},
            timeout=30,
        )
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
    except Exception as e:
        print(f"  skipped arm strength ({e})")
        return pd.DataFrame(columns=["player_id", "arm_strength"])
    return df.rename(columns={"arm_overall": "arm_strength"})[["player_id", "arm_strength"]].dropna(subset=["player_id"])


def fetch_fielding(season=CURRENT_SEASON):
    print(f"Fetching {season} Statcast fielding (Outs Above Average)...")
    fielding = statcast_outs_above_average(season, "all")
    fielding = fielding.rename(columns={
        "last_name, first_name": "Name",
        "display_team_name": "Tm",
        "primary_pos_formatted": "Pos",
        "outs_above_average": "OAA",
        "fielding_runs_prevented": "FRP",
        "actual_success_rate_formatted": "success_rate",
    })
    arm_strength = fetch_arm_strength(season)
    fielding = fielding.merge(arm_strength, on="player_id", how="left")
    fielding["season"] = season
    return fielding


PITCH_TYPES = ["FF", "SI", "FC", "SL", "CH", "CU", "FS", "KN", "ST", "SV"]


def fetch_pitch_arsenal(season=CURRENT_SEASON):
    """Per-pitcher, per-pitch-type breakdown for the season: usage%, whiff%,
    and run value from Baseball Savant's pitch-arsenal-stats leaderboard,
    joined with velocity and movement (induced vertical / horizontal break)
    from its pitch-movement leaderboard. pybaseball has no wrapper for
    either, so both are direct CSV fetches like fetch_arm_strength. Movement
    is only reported per pitch type (not "all" in one call), so this makes
    one request per type in PITCH_TYPES and concatenates the results."""
    print(f"Fetching {season} Statcast pitch arsenal (usage/whiff/run value)...")
    try:
        resp = requests.get(
            "https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats",
            params={"type": "pitcher", "pitchType": "", "year": season, "team": "", "min": 5, "csv": "true"},
            timeout=30,
        )
        resp.raise_for_status()
        stats = pd.read_csv(io.StringIO(resp.text))
    except Exception as e:
        print(f"  skipped pitch arsenal stats ({e})")
        return pd.DataFrame()
    stats = stats.rename(columns={
        "last_name, first_name": "Name", "player_id": "mlbID",
        "pitch_usage": "usage_pct", "whiff_percent": "whiff_pct",
        "team_name_alt": "team",
    })

    print(f"Fetching {season} Statcast pitch movement (velocity/break)...")
    movement_frames = []
    for pt in PITCH_TYPES:
        try:
            resp = requests.get(
                "https://baseballsavant.mlb.com/leaderboard/pitch-movement",
                params={"year": season, "team": "", "min": 5, "pitch_type": pt, "csv": "true"},
                timeout=30,
            )
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))
        except Exception as e:
            print(f"  skipped movement for {pt} ({e})")
            continue
        if df.empty:
            continue
        movement_frames.append(df.rename(columns={
            "pitcher_id": "mlbID", "avg_speed": "velocity",
            "pitcher_break_z_induced": "vert_break", "pitcher_break_x": "horz_break",
        })[["mlbID", "pitch_type", "pitch_hand", "velocity", "vert_break", "horz_break",
            "league_break_z", "league_break_x"]])
    movement = pd.concat(movement_frames, ignore_index=True) if movement_frames else pd.DataFrame(
        columns=["mlbID", "pitch_type", "pitch_hand", "velocity", "vert_break", "horz_break",
                 "league_break_z", "league_break_x"]
    )

    spin = fetch_spin_rate(season)
    arsenal = stats.merge(movement, on=["mlbID", "pitch_type"], how="left")
    arsenal = arsenal.merge(spin, on=["mlbID", "pitch_type"], how="left")
    arsenal["season"] = season
    return arsenal[[
        "mlbID", "Name", "team", "pitch_hand", "pitch_type", "pitch_name", "usage_pct", "whiff_pct",
        "run_value", "run_value_per_100", "velocity", "vert_break", "horz_break",
        "league_break_z", "league_break_x", "spin_rate",
        "pa", "ba", "slg", "woba", "est_woba", "k_percent", "put_away", "hard_hit_percent", "season",
    ]]


SPIN_COL_TO_PITCH_TYPE = {
    "active_spin_fourseam": "FF", "active_spin_sinker": "SI", "active_spin_cutter": "FC",
    "active_spin_changeup": "CH", "active_spin_splitter": "FS", "active_spin_curve": "CU",
    "active_spin_slider": "SL", "active_spin_sweeper": "ST", "active_spin_slurve": "SV",
}


def fetch_spin_rate(season=CURRENT_SEASON):
    """Active spin % per pitch type (how much of a pitch's total spin
    actually contributes to movement, vs. "gyro" spin that doesn't) from
    Statcast's active-spin leaderboard. That leaderboard is wide (one
    column per pitch type) — melted here into the same long (mlbID,
    pitch_type) shape as the rest of the pitch arsenal data so it merges
    straight in. Only supported 2020+ ("spin-based" method); Statcast
    redirects to a plain HTML page for earlier years, which this treats
    the same as any other empty/failed response."""
    try:
        resp = requests.get(
            "https://baseballsavant.mlb.com/leaderboard/active-spin",
            params={"year": f"{season}_spin-based", "min": 5, "hand": "", "csv": "true"},
            timeout=30,
        )
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        if df.empty or "entity_id" not in df.columns:
            raise ValueError("no spin-based data for this season")
    except Exception as e:
        print(f"  skipped spin rate ({e})")
        return pd.DataFrame(columns=["mlbID", "pitch_type", "spin_rate"])

    frames = []
    for col, pitch_type in SPIN_COL_TO_PITCH_TYPE.items():
        if col not in df.columns:
            continue
        sub = df[["entity_id", col]].rename(columns={"entity_id": "mlbID", col: "spin_rate"})
        sub["pitch_type"] = pitch_type
        frames.append(sub.dropna(subset=["spin_rate"]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["mlbID", "pitch_type", "spin_rate"])


def fetch_batted_ball_profile(season=CURRENT_SEASON):
    """Batted-ball direction/type rates (ground ball / fly ball / line
    drive / popup, and pull / straightaway / opposite field) for batters —
    a hitter's approach, distinct from the outcome stats (BA/SLG/etc.)
    already covered elsewhere."""
    print(f"Fetching {season} Statcast batted-ball profile...")
    try:
        resp = requests.get(
            "https://baseballsavant.mlb.com/leaderboard/batted-ball",
            params={"type": "batter", "year": season, "csv": "true"},
            timeout=30,
        )
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
    except Exception as e:
        print(f"  skipped batted-ball profile ({e})")
        return pd.DataFrame(columns=["mlbID", "season"])
    df = df.rename(columns={"id": "mlbID"})
    df["season"] = season
    return df[["mlbID", "gb_rate", "air_rate", "fb_rate", "ld_rate", "pu_rate",
               "pull_rate", "straight_rate", "oppo_rate", "season"]]


def fetch_bat_tracking(season=CURRENT_SEASON):
    """Bat speed / swing length / swing-quality stats from Statcast's bat
    tracking system, which only started recording in the 2023 season —
    empty response for anything earlier is expected, not an error."""
    print(f"Fetching {season} Statcast bat tracking...")
    try:
        resp = requests.get(
            "https://baseballsavant.mlb.com/leaderboard/bat-tracking",
            params={"type": "batter", "year": season, "min": 50, "csv": "true"},
            timeout=30,
        )
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
    except Exception as e:
        print(f"  skipped bat tracking ({e})")
        return pd.DataFrame(columns=["mlbID", "season"])
    if df.empty:
        return pd.DataFrame(columns=["mlbID", "season"])
    df = df.rename(columns={"id": "mlbID"})
    df["season"] = season
    return df[["mlbID", "avg_bat_speed", "swing_length", "hard_swing_rate",
               "squared_up_per_swing", "blast_per_swing", "whiff_per_swing", "season"]]


def fetch_catcher_framing(season=CURRENT_SEASON):
    """Catcher pitch-framing runs saved/cost — a real driver of catcher
    value that plain fielding stats (OAA, errors) don't capture at all."""
    print(f"Fetching {season} Statcast catcher framing...")
    try:
        resp = requests.get(
            "https://baseballsavant.mlb.com/leaderboard/catcher-framing",
            params={"year": season, "team": "", "min": 1, "csv": "true"},
            timeout=30,
        )
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
    except Exception as e:
        print(f"  skipped catcher framing ({e})")
        return pd.DataFrame(columns=["mlbID", "season"])
    df = df.rename(columns={"id": "mlbID", "rv_tot": "framing_runs", "pct_tot": "framing_pct", "name": "Name"})
    df["season"] = season
    return df[["mlbID", "Name", "pitches", "framing_runs", "framing_pct", "season"]]


def fetch_catcher_poptime(season=CURRENT_SEASON):
    """Catcher pop time (glove-to-glove on a stolen-base attempt) — the
    throwing-speed side of catcher defense, separate from framing."""
    print(f"Fetching {season} Statcast catcher pop time...")
    try:
        resp = requests.get(
            "https://baseballsavant.mlb.com/leaderboard/poptime",
            params={"year": season, "team": "", "min2b": 1, "min3b": 0, "csv": "true"},
            timeout=30,
        )
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
    except Exception as e:
        print(f"  skipped catcher pop time ({e})")
        return pd.DataFrame(columns=["mlbID", "season"])
    df = df.rename(columns={
        "entity_id": "mlbID", "entity_name": "Name", "pop_2b_sba": "pop_2b", "pop_3b_sba": "pop_3b",
        "pop_2b_sba_count": "pop_2b_count", "pop_3b_sba_count": "pop_3b_count",
        "maxeff_arm_2b_3b_sba": "arm", "exchange_2b_3b_sba": "exchange_time",
    })
    df["season"] = season
    return df[["mlbID", "Name", "age", "arm", "exchange_time",
               "pop_2b", "pop_2b_count", "pop_3b", "pop_3b_count", "season"]]


def fetch_outfielder_jump(season=CURRENT_SEASON):
    """Outfielder "jump" — reaction, burst, and route-efficiency distance
    (feet gained/lost vs. league average) on two-star-or-harder plays, the
    components that actually make up an outfielder's OAA rather than just
    the final runs number."""
    print(f"Fetching {season} Statcast outfielder jump...")
    try:
        resp = requests.get(
            "https://baseballsavant.mlb.com/leaderboard/outfield_jump",
            params={"year": season, "min": 1, "csv": "true"},
            timeout=30,
        )
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
    except Exception as e:
        print(f"  skipped outfielder jump ({e})")
        return pd.DataFrame(columns=["mlbID", "season"])
    df = df.rename(columns={
        "resp_fielder_id": "mlbID",
        "rel_league_reaction_distance": "reaction",
        "rel_league_burst_distance": "burst",
        "rel_league_routing_distance": "routing",
    })
    df["season"] = season
    return df[["mlbID", "reaction", "burst", "routing", "season"]]


def fetch_recent_batting():
    """Batting stats over the last day/week/month, for 'headliner' cards that
    highlight hot recent performances rather than just season-to-date bests.
    Uses Baseball-Reference's date-range endpoint (games completed through
    yesterday, since today's games are still in progress when this runs)."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    windows = {
        "day": (yesterday, yesterday),
        "week": (today - timedelta(days=7), yesterday),
        "month": (today - timedelta(days=30), yesterday),
    }

    frames = []
    for period, (start, end) in windows.items():
        print(f"Fetching recent batting stats ({period}: {start} to {end})...")
        try:
            df = batting_stats_range(start.isoformat(), end.isoformat())
        except Exception as e:
            print(f"  skipped ({e})")
            continue
        if df.empty:
            continue
        df["Name"] = fix_mojibake_names(df["Name"])
        df["period"] = period
        df["season"] = CURRENT_SEASON
        frames.append(df)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def fetch_recent_pitching():
    """Pitching stats over the last day/week/month, mirroring fetch_recent_batting.
    'day' includes Game Score (GSc), a well-known single-game dominance metric;
    week/month use ERA instead since Game Score isn't meaningful summed across starts."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    windows = {
        "day": (yesterday, yesterday),
        "week": (today - timedelta(days=7), yesterday),
        "month": (today - timedelta(days=30), yesterday),
    }

    frames = []
    for period, (start, end) in windows.items():
        print(f"Fetching recent pitching stats ({period}: {start} to {end})...")
        try:
            df = pitching_stats_range(start.isoformat(), end.isoformat())
        except Exception as e:
            print(f"  skipped ({e})")
            continue
        if df.empty:
            continue
        df["Name"] = fix_mojibake_names(df["Name"])
        # Baseball-Reference leaves SV blank instead of 0 for pitchers with
        # no saves in the window (same quirk as the season pitching table).
        df["SV"] = df["SV"].fillna(0).astype(int)
        df["period"] = period
        df["season"] = CURRENT_SEASON
        frames.append(df)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def fetch_todays_games():
    """Today's MLB schedule, team records, and probable starting pitchers,
    from the free public MLB Stats API (statsapi.mlb.com — no key needed).
    This is a different data source than the rest of the app (which uses
    pybaseball/Baseball-Reference/Statcast), but it's the only place that has
    a live game schedule with probable pitchers. Powers the Today's Games
    page's win predictions."""
    today = date.today().isoformat()
    columns = [
        "date", "game_pk", "game_time", "status", "venue",
        "away_team", "away_abbr", "away_wins", "away_losses", "away_pitcher_name", "away_pitcher_mlbID",
        "home_team", "home_abbr", "home_wins", "home_losses", "home_pitcher_name", "home_pitcher_mlbID",
    ]
    print(f"Fetching today's schedule ({today}) from MLB Stats API...")
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": today, "hydrate": "probablePitcher,team,venue"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  skipped ({e})")
        return pd.DataFrame(columns=columns)

    dates = data.get("dates", [])
    games = dates[0].get("games", []) if dates else []
    if not games:
        return pd.DataFrame(columns=columns)

    rows = []
    for g in games:
        away, home = g["teams"]["away"], g["teams"]["home"]
        away_pitcher = away.get("probablePitcher") or {}
        home_pitcher = home.get("probablePitcher") or {}
        rows.append({
            "date": today,
            "game_pk": g.get("gamePk"),
            "game_time": g.get("gameDate"),
            "status": g.get("status", {}).get("detailedState"),
            "venue": g.get("venue", {}).get("name"),
            "away_team": away["team"]["name"],
            "away_abbr": away["team"]["abbreviation"],
            "away_wins": away.get("leagueRecord", {}).get("wins"),
            "away_losses": away.get("leagueRecord", {}).get("losses"),
            "away_pitcher_name": away_pitcher.get("fullName"),
            "away_pitcher_mlbID": away_pitcher.get("id"),
            "home_team": home["team"]["name"],
            "home_abbr": home["team"]["abbreviation"],
            "home_wins": home.get("leagueRecord", {}).get("wins"),
            "home_losses": home.get("leagueRecord", {}).get("losses"),
            "home_pitcher_name": home_pitcher.get("fullName"),
            "home_pitcher_mlbID": home_pitcher.get("id"),
        })
    return pd.DataFrame(rows)


def fetch_standings():
    """Current division standings from the MLB Stats API. Replaced in full
    every run (current standings only — this isn't a historical table)."""
    print("Fetching standings from MLB Stats API...")
    columns = [
        "season", "league", "division", "team_name", "team_abbr",
        "wins", "losses", "pct", "games_back", "streak", "div_rank",
        "runs_scored", "runs_allowed", "run_diff",
    ]
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/standings",
            params={"leagueId": "103,104", "season": CURRENT_SEASON},
            timeout=15,
        )
        resp.raise_for_status()
        records = resp.json().get("records", [])
    except Exception as e:
        print(f"  skipped ({e})")
        return pd.DataFrame(columns=columns)

    rows = []
    for rec in records:
        league = "AL" if rec["league"]["id"] == 103 else "NL"
        division = DIVISION_NAMES.get(rec["division"]["id"], "Unknown")
        for tr in rec.get("teamRecords", []):
            record = tr.get("leagueRecord", {})
            team_abbr, _ = app_teams.team_meta_from_nickname(tr["team"]["name"])
            rows.append({
                "season": CURRENT_SEASON,
                "league": league,
                "division": division,
                "team_name": tr["team"]["name"],
                "team_abbr": team_abbr,
                "wins": record.get("wins"),
                "losses": record.get("losses"),
                "pct": record.get("pct"),
                "games_back": tr.get("divisionGamesBack"),
                "streak": tr.get("streak", {}).get("streakCode"),
                "div_rank": tr.get("divisionRank"),
                "runs_scored": tr.get("runsScored"),
                "runs_allowed": tr.get("runsAllowed"),
                "run_diff": tr.get("runDifferential"),
            })
    return pd.DataFrame(rows)


def fetch_schedule():
    """Full current-season regular-season schedule (every team, every game)
    from the MLB Stats API — past games carry a final score, future games
    have score columns of None. Replaced in full every run (this is a live
    schedule, not a historical archive across seasons). Powers the Team
    page's full-schedule table and db.compute_playoff_odds()'s Monte Carlo
    simulation of the remaining season."""
    print("Fetching full-season schedule from MLB Stats API...")
    columns = [
        "season", "game_pk", "date", "game_time", "status",
        "away_abbr", "away_score", "home_abbr", "home_score",
    ]
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={
                "sportId": 1, "gameType": "R",
                "startDate": f"{CURRENT_SEASON}-01-01", "endDate": f"{CURRENT_SEASON}-12-31",
            },
            timeout=30,
        )
        resp.raise_for_status()
        dates = resp.json().get("dates", [])
    except Exception as e:
        print(f"  skipped ({e})")
        return pd.DataFrame(columns=columns)

    rows = []
    for d in dates:
        for g in d.get("games", []):
            away, home = g["teams"]["away"], g["teams"]["home"]
            away_abbr = app_teams.abbr_for_team_id(away["team"]["id"])
            home_abbr = app_teams.abbr_for_team_id(home["team"]["id"])
            if not away_abbr or not home_abbr:
                continue  # non-MLB opponent (e.g. an exhibition slipped past the gameType filter)
            rows.append({
                "season": CURRENT_SEASON,
                "game_pk": g.get("gamePk"),
                "date": g.get("officialDate"),
                "game_time": g.get("gameDate"),
                "status": g.get("status", {}).get("abstractGameState"),
                "away_abbr": away_abbr,
                "away_score": away.get("score"),
                "home_abbr": home_abbr,
                "home_score": home.get("score"),
            })
    return pd.DataFrame(rows)


# Round-number career counting-stat milestones worth watching for. Kept
# small/well-known on purpose (this is a "who's about to do something
# historic" list, not an exhaustive stat dump).
CAREER_MILESTONES = {
    "HR": [300, 400, 500, 600, 700, 800],
    "H": [2000, 2500, 3000, 3500, 4000],
    "RBI": [1000, 1500, 2000],
    "SB": [300, 400, 500, 600],
    "W": [150, 200, 250, 300],
    "SO": [2000, 2500, 3000, 3500, 4000],
    "SV": [200, 300, 400, 500],
}


def fetch_career_totals():
    """True career (not just our 2010+ cached seasons) counting stats for
    every player active in the current season, from the MLB Stats API's
    own career totals — a player who debuted in, say, 2005 is still
    tracked accurately, since this doesn't depend on how far back this
    app's own batting/pitching tables go. Feeds the Milestone Watch page.

    Batched: the API 414s (URI too long) past roughly ~300 comma-joined
    personIds in one request, so this chunks the current season's full
    player list into batches rather than fetching one player at a time
    (which would be ~1000+ requests) or all at once (which 414s)."""
    print("Fetching career totals for current-season players...")
    with sqlite3.connect(DB_PATH) as conn:
        bat_df = pd.read_sql(
            "SELECT DISTINCT mlbID, Tm, Lev FROM batting WHERE season = ?", conn, params=(CURRENT_SEASON,),
        )
        pit_df = pd.read_sql(
            "SELECT DISTINCT mlbID, Tm, Lev FROM pitching WHERE season = ?", conn, params=(CURRENT_SEASON,),
        )
    # A player's own row (whichever table it came from) already carries
    # their own Tm/Lev — no cross-table merge needed, just pick one map,
    # preferring batting (a two-way player's "primary" role, matching the
    # precedent set by db.player_primary_role for how ties are resolved
    # elsewhere in the app).
    team_by_id = {row.mlbID: (row.Tm, row.Lev) for row in pit_df.itertuples()}
    team_by_id.update({row.mlbID: (row.Tm, row.Lev) for row in bat_df.itertuples()})
    all_ids = sorted({int(i) for i in pd.concat([bat_df["mlbID"], pit_df["mlbID"]]).dropna().unique()})

    rows = []
    CHUNK = 300
    for i in range(0, len(all_ids), CHUNK):
        chunk = all_ids[i:i + CHUNK]
        try:
            resp = requests.get(
                "https://statsapi.mlb.com/api/v1/people",
                params={
                    "personIds": ",".join(str(pid) for pid in chunk),
                    "hydrate": "stats(group=[hitting,pitching],type=career)",
                },
                timeout=30,
            )
            resp.raise_for_status()
            people = resp.json().get("people", [])
        except Exception as e:
            print(f"  skipped a batch of {len(chunk)} players ({e})")
            continue
        for p in people:
            tm, lev = team_by_id.get(p["id"], (None, None))
            row = {"mlbID": p["id"], "Name": p.get("fullName"), "Tm": tm, "Lev": lev}
            for s in p.get("stats", []):
                if not s.get("splits"):
                    continue
                stat = s["splits"][0]["stat"]
                if s["group"]["displayName"] == "hitting":
                    row["HR"], row["H"] = stat.get("homeRuns"), stat.get("hits")
                    row["RBI"], row["SB"] = stat.get("rbi"), stat.get("stolenBases")
                elif s["group"]["displayName"] == "pitching":
                    row["W"], row["SO"], row["SV"] = stat.get("wins"), stat.get("strikeOuts"), stat.get("saves")
            rows.append(row)
    return pd.DataFrame(rows)


def record_milestone_achievements(conn, career_totals):
    """Log the first day we notice a player's true career total crossing
    one of CAREER_MILESTONES's thresholds — powers the Milestone Watch
    page's "just achieved" callout, which stays up for 5 days after the
    fact (see db.recent_milestone_achievers()).

    Bootstrap case: the very first time this runs, milestone_achievements
    doesn't exist yet, so every threshold a player has ALREADY crossed
    (possibly years ago) would otherwise all get stamped with today's date
    and wrongly show up as "just achieved". Backdated to 1900-01-01
    instead on that one run only — old enough to never fall inside the
    5-day window — so only genuinely new crossings from here on get a
    real date."""
    table_is_new = False
    try:
        existing = pd.read_sql("SELECT mlbID, Stat, Milestone FROM milestone_achievements", conn)
        existing_keys = set(zip(existing["mlbID"], existing["Stat"], existing["Milestone"]))
    except pd.errors.DatabaseError:
        existing_keys = set()
        table_is_new = True

    stamp = "1900-01-01" if table_is_new else date.today().isoformat()
    new_rows = []
    for row in career_totals.itertuples():
        for stat, thresholds in CAREER_MILESTONES.items():
            total = getattr(row, stat, None)
            if total is None or pd.isna(total):
                continue
            for milestone in thresholds:
                if total >= milestone and (row.mlbID, stat, milestone) not in existing_keys:
                    new_rows.append({
                        "mlbID": row.mlbID, "Name": row.Name, "Tm": row.Tm, "Lev": row.Lev,
                        "Stat": stat, "Milestone": milestone, "achieved_date": stamp,
                    })
    if new_rows:
        pd.DataFrame(new_rows).to_sql("milestone_achievements", conn, if_exists="append", index=False)
    return len(new_rows)


def fetch_all_star_roster(season):
    """That season's All-Star Game roster (both leagues) from the MLB Stats
    API. There's no dedicated "All-Star roster" endpoint — instead, the ASG
    itself has real team IDs (159 = AL All-Stars, 160 = NL All-Stars) like
    any other game, so this finds that game via the season's gameType=A
    schedule entry and reads its boxscore. The roster is already final
    (all players+positions listed) as soon as it's announced, well before
    the game is actually played, so this doesn't need to wait for the game
    to finish. Returns an empty DataFrame for a season with no game (2020,
    canceled) or any other lookup failure."""
    print(f"Fetching {season} All-Star Game rosters...")
    columns = ["season", "league", "mlbID", "Name", "Pos", "Tm", "is_starter"]
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "season": season, "gameType": "A"},
            timeout=15,
        )
        resp.raise_for_status()
        games = [g for d in resp.json().get("dates", []) for g in d.get("games", [])]
        if not games:
            print("  skipped (no All-Star Game found for this season)")
            return pd.DataFrame(columns=columns)
        game_pk = games[0]["gamePk"]

        resp = requests.get(f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live", timeout=15)
        resp.raise_for_status()
        box = resp.json()["liveData"]["boxscore"]
    except Exception as e:
        print(f"  skipped ({e})")
        return pd.DataFrame(columns=columns)

    rows = []
    for side in ("away", "home"):
        team = box["teams"][side]
        league = "AL" if "American League" in team["team"]["name"] else "NL"
        # The boxscore's own `battingOrder` list (exactly 9 person IDs, in
        # true batting order) is the authoritative source for "who started
        # the game" — unlike each player's individual battingOrder string
        # (which encodes lineup-SLOT, not starter-vs-sub, and doesn't
        # reliably end in "00" for the actual starter in every season) or
        # their position field (which can reflect a later in-game move, e.g.
        # a player who started in CF but is tagged with the OF spot they
        # ended up playing). Pitchers don't bat, so the starter there is
        # identified separately by gamesStarted == 1.
        starter_ids = set(team.get("battingOrder", []))
        for p in team["players"].values():
            person = p.get("person", {})
            pos = p.get("position", {}).get("abbreviation", "—")
            is_starter = (
                person.get("id") in starter_ids
                if pos != "P"
                else p.get("stats", {}).get("pitching", {}).get("gamesStarted") == 1
            )
            rows.append({
                "season": season,
                "league": league,
                "mlbID": person.get("id"),
                "Name": person.get("fullName"),
                "Pos": pos,
                "Tm": app_teams.abbr_for_team_id(p.get("parentTeamId")) or "—",
                "is_starter": is_starter,
            })
    return pd.DataFrame(rows)


def build_player_history(batting, pitching, recent_batting, recent_pitching):
    """One row per player per day, appended to `player_history` on every run.
    Two purposes: season-to-date OPS/ERA power the Search page's trend line;
    day_PA/day_H and day_IP/day_ER (yesterday's single-game line, reused from
    the recent-performance fetch rather than a new network call) power hit-
    streak / scoreless-streak tracking. Append-only (not replaced) like the
    other tables, so it accumulates real history over time."""
    today = date.today().isoformat()

    bat_hist = batting[["mlbID", "Name", "Tm", "PA", "OPS"]].copy()
    bat_hist["role"] = "Batter"
    bat_hist["ERA"] = float("nan")
    bat_hist["IP"] = float("nan")
    if not recent_batting.empty:
        day_bat = recent_batting[recent_batting["period"] == "day"][["mlbID", "PA", "H"]].copy()
        day_bat["mlbID"] = pd.to_numeric(day_bat["mlbID"], errors="coerce")
        day_bat = day_bat.rename(columns={"PA": "day_PA", "H": "day_H"})
        bat_hist = bat_hist.merge(day_bat, on="mlbID", how="left")
    else:
        bat_hist["day_PA"] = float("nan")
        bat_hist["day_H"] = float("nan")
    bat_hist["day_IP"] = float("nan")
    bat_hist["day_ER"] = float("nan")

    pit_hist = pitching[["mlbID", "Name", "Tm", "IP", "ERA"]].copy()
    pit_hist["role"] = "Pitcher"
    pit_hist["PA"] = float("nan")
    pit_hist["OPS"] = float("nan")
    if not recent_pitching.empty:
        day_pit = recent_pitching[recent_pitching["period"] == "day"][["mlbID", "IP", "ER"]].copy()
        day_pit["mlbID"] = pd.to_numeric(day_pit["mlbID"], errors="coerce")
        day_pit = day_pit.rename(columns={"IP": "day_IP", "ER": "day_ER"})
        pit_hist = pit_hist.merge(day_pit, on="mlbID", how="left")
    else:
        pit_hist["day_IP"] = float("nan")
        pit_hist["day_ER"] = float("nan")
    pit_hist["day_PA"] = float("nan")
    pit_hist["day_H"] = float("nan")

    history = pd.concat([bat_hist, pit_hist], ignore_index=True)
    history["date"] = today
    history["season"] = CURRENT_SEASON
    return history[[
        "date", "season", "mlbID", "Name", "Tm", "role",
        "PA", "OPS", "IP", "ERA", "day_PA", "day_H", "day_IP", "day_ER",
    ]]


def _store_season_table(conn, table_name, df, season):
    """Write one season's worth of a table without touching other seasons'
    rows — DELETE that season, then append. This is what makes multi-season
    data possible: the old approach (`if_exists='replace'`) wiped the whole
    table on every run, so only the current season could ever be cached.

    Schema migration: `to_sql(if_exists="append")` requires the dataframe's
    columns to exactly match the existing table's, so adding/renaming/
    removing a column in a fetch_*() function breaks every other season's
    already-stored rows. Drop and let to_sql recreate the table if the
    incoming columns don't match — this loses other seasons' rows for that
    table, so after a schema change, re-run --backfill for every season
    you care about (batting/pitching/fielding are cheap, network-bound
    re-fetches, not expensive local computation)."""
    try:
        existing_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table_name})")}
        if existing_cols and existing_cols != set(df.columns):
            conn.execute(f"DROP TABLE {table_name}")
        else:
            conn.execute(f"DELETE FROM {table_name} WHERE season = ?", (season,))
    except sqlite3.OperationalError:
        pass  # table doesn't exist yet on first run
    df.to_sql(table_name, conn, if_exists="append", index=False)


def fetch_and_store():
    """Daily refresh: current season's batting/pitching/fielding/recent-performance
    data, plus today's player_history row. Does NOT touch other seasons already
    backfilled — see backfill_season() for adding historical years."""
    batting = fetch_batting(CURRENT_SEASON)
    pitching = fetch_pitching(CURRENT_SEASON)
    fielding = fetch_fielding(CURRENT_SEASON)
    pitch_arsenal = fetch_pitch_arsenal(CURRENT_SEASON)
    batted_ball = fetch_batted_ball_profile(CURRENT_SEASON)
    bat_tracking = fetch_bat_tracking(CURRENT_SEASON)
    catcher_framing = fetch_catcher_framing(CURRENT_SEASON)
    catcher_poptime = fetch_catcher_poptime(CURRENT_SEASON)
    outfield_jump = fetch_outfielder_jump(CURRENT_SEASON)
    recent_batting = fetch_recent_batting()
    recent_pitching = fetch_recent_pitching()
    todays_games = fetch_todays_games()
    standings = fetch_standings()
    schedule = fetch_schedule()
    all_star_roster = fetch_all_star_roster(CURRENT_SEASON)
    career_totals = fetch_career_totals()
    history = build_player_history(batting, pitching, recent_batting, recent_pitching)

    conn = sqlite3.connect(DB_PATH)
    try:
        # one-time schema migration: player_history gained day_PA/day_H/day_IP/day_ER
        # columns after it first shipped; drop and let to_sql recreate it if an
        # older copy of the table is still around (loses only a few days of
        # season-trend history, which is an acceptable cost for a still-new feature)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(player_history)")]
            if cols and "day_H" not in cols:
                conn.execute("DROP TABLE player_history")
        except sqlite3.OperationalError:
            pass

        _store_season_table(conn, "batting", batting, CURRENT_SEASON)
        _store_season_table(conn, "pitching", pitching, CURRENT_SEASON)
        _store_season_table(conn, "fielding", fielding, CURRENT_SEASON)
        if not pitch_arsenal.empty:
            _store_season_table(conn, "pitch_arsenal", pitch_arsenal, CURRENT_SEASON)
        if not batted_ball.empty:
            _store_season_table(conn, "batted_ball", batted_ball, CURRENT_SEASON)
        if not bat_tracking.empty:
            _store_season_table(conn, "bat_tracking", bat_tracking, CURRENT_SEASON)
        if not catcher_framing.empty:
            _store_season_table(conn, "catcher_framing", catcher_framing, CURRENT_SEASON)
        if not catcher_poptime.empty:
            _store_season_table(conn, "catcher_poptime", catcher_poptime, CURRENT_SEASON)
        if not outfield_jump.empty:
            _store_season_table(conn, "outfield_jump", outfield_jump, CURRENT_SEASON)
        if not all_star_roster.empty:
            _store_season_table(conn, "all_star_rosters", all_star_roster, CURRENT_SEASON)
        # career_totals is a "right now" snapshot (not tied to one cached
        # season), so it's fully replaced each run like standings/todays_games
        # rather than appended via _store_season_table.
        if not career_totals.empty:
            career_totals.to_sql("career_totals", conn, if_exists="replace", index=False)
            new_achievements = record_milestone_achievements(conn, career_totals)
        else:
            new_achievements = 0
        if not recent_batting.empty:
            recent_batting.to_sql("recent_batting", conn, if_exists="replace", index=False)
        if not recent_pitching.empty:
            recent_pitching.to_sql("recent_pitching", conn, if_exists="replace", index=False)
        # always replace, even if empty (e.g. an off day with zero games) — an
        # empty table is the correct signal for "nothing scheduled today"
        todays_games.to_sql("todays_games", conn, if_exists="replace", index=False)
        standings.to_sql("standings", conn, if_exists="replace", index=False)
        schedule.to_sql("schedule", conn, if_exists="replace", index=False)

        # player_history is append-only (not replaced) so it builds up real
        # day-over-day history; clear today's rows first so re-running the
        # script the same day doesn't create duplicates.
        try:
            conn.execute(
                "DELETE FROM player_history WHERE date = ? AND season = ?",
                (date.today().isoformat(), CURRENT_SEASON),
            )
        except sqlite3.OperationalError:
            pass  # table doesn't exist yet on first run
        history.to_sql("player_history", conn, if_exists="append", index=False)

        conn.commit()
    finally:
        conn.close()

    print(
        f"Saved {len(batting)} batters, {len(pitching)} pitchers, "
        f"{len(fielding)} fielders, {len(recent_batting)} recent-batting rows, "
        f"{len(recent_pitching)} recent-pitching rows, {len(history)} history rows, "
        f"{len(todays_games)} today's games, {len(standings)} standings rows, "
        f"{len(schedule)} schedule rows, "
        f"{len(all_star_roster)} All-Star roster rows, {len(career_totals)} career-totals rows, "
        f"{new_achievements} new milestone achievements to {DB_PATH}"
    )

    # Umpire scorecards for yesterday's games (see ump_scorecards.py) —
    # guarded so a hiccup in this add-on can never take down the rest of
    # the nightly refresh that the whole site depends on.
    try:
        from ump_scorecards import update_day
        update_day((date.today() - timedelta(days=1)).isoformat())
    except Exception as e:
        print(f"ump scorecard update failed (non-fatal): {e}")


def backfill_season(season):
    """One-time fetch of a single historical season's batting/pitching/fielding
    (no recent-performance or player_history — those are 'right now' concepts
    that don't apply to past seasons). Deliberately does ONE season per call
    and returns immediately after writing to disk, so memory doesn't build up
    across multiple seasons — run this once per season, checking the dashboard
    still behaves between each one, rather than looping over many seasons in
    a single process."""
    batting = fetch_batting(season)
    pitching = fetch_pitching(season)
    fielding = fetch_fielding(season)
    pitch_arsenal = fetch_pitch_arsenal(season)
    batted_ball = fetch_batted_ball_profile(season)
    bat_tracking = fetch_bat_tracking(season)
    catcher_framing = fetch_catcher_framing(season)
    catcher_poptime = fetch_catcher_poptime(season)
    outfield_jump = fetch_outfielder_jump(season)

    conn = sqlite3.connect(DB_PATH)
    try:
        _store_season_table(conn, "batting", batting, season)
        _store_season_table(conn, "pitching", pitching, season)
        _store_season_table(conn, "fielding", fielding, season)
        if not pitch_arsenal.empty:
            _store_season_table(conn, "pitch_arsenal", pitch_arsenal, season)
        if not batted_ball.empty:
            _store_season_table(conn, "batted_ball", batted_ball, season)
        if not bat_tracking.empty:
            _store_season_table(conn, "bat_tracking", bat_tracking, season)
        if not catcher_framing.empty:
            _store_season_table(conn, "catcher_framing", catcher_framing, season)
        if not catcher_poptime.empty:
            _store_season_table(conn, "catcher_poptime", catcher_poptime, season)
        if not outfield_jump.empty:
            _store_season_table(conn, "outfield_jump", outfield_jump, season)
        conn.commit()
    finally:
        conn.close()

    print(f"Backfilled {season}: {len(batting)} batters, {len(pitching)} pitchers, {len(fielding)} fielders to {DB_PATH}")


def backfill_all_star(season):
    """One-time fetch of a single season's All-Star Game roster — separate
    from backfill_season() since it's an independent, much smaller table
    (see fetch_all_star_roster())."""
    roster = fetch_all_star_roster(season)

    conn = sqlite3.connect(DB_PATH)
    try:
        _store_season_table(conn, "all_star_rosters", roster, season)
        conn.commit()
    finally:
        conn.close()

    print(f"Backfilled {season} All-Star rosters: {len(roster)} players to {DB_PATH}")


if __name__ == "__main__":
    import sys

    DB_PATH.parent.mkdir(exist_ok=True)
    if len(sys.argv) > 1 and sys.argv[1] == "--backfill":
        backfill_season(int(sys.argv[2]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--allstar":
        backfill_all_star(int(sys.argv[2]))
    else:
        fetch_and_store()
