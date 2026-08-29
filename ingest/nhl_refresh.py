"""NHL ingest — skater season stats into data/nhl.db (kept separate from
the MLB database: no table-name collisions, independent refresh).

Sources:
  - api.nhle.com/stats/rest skater reports (official, free, no key):
    summary, realtime, percentages, scoringRates, timeonice, powerplay,
    penaltykill, penalties, faceoffpercentages, shottype, bios — merged on
    playerId into ONE wide `skaters` row per player-season.
  - MoneyPuck's published season CSVs for expected goals (the NHL doesn't
    publish xG). Their data page offers these downloads on purpose; the
    columns are labeled MoneyPuck-sourced in the app.

Usage:
    python ingest/nhl_refresh.py 2021 2025     # backfill (season start years)
    python ingest/nhl_refresh.py               # current/latest season only
"""
import io
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

NHL_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "nhl.db"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# Report -> columns to keep (everything else in the report is dropped so the
# merged table stays readable). Keys are the API's camelCase names.
REPORTS = {
    "summary": [
        "playerId", "skaterFullName", "teamAbbrevs", "positionCode", "shootsCatches",
        "gamesPlayed", "goals", "assists", "points", "pointsPerGame", "plusMinus",
        "penaltyMinutes", "evGoals", "evPoints", "ppGoals", "ppPoints", "shGoals", "shPoints",
        "gameWinningGoals", "otGoals", "shots", "shootingPct", "timeOnIcePerGame", "faceoffWinPct",
    ],
    "realtime": [
        "playerId", "hits", "hitsPer60", "blockedShots", "blockedShotsPer60", "giveaways",
        "giveawaysPer60", "takeaways", "takeawaysPer60", "totalShotAttempts", "missedShots",
    ],
    "percentages": [
        "playerId", "satPercentage", "satRelative", "usatPercentage", "usatRelative",
        "shootingPct5v5", "skaterSavePct5v5", "skaterShootingPlusSavePct5v5", "zoneStartPct5v5",
        "timeOnIcePerGame5v5",
    ],
    "scoringRates": [
        "playerId", "goals5v5", "assists5v5", "points5v5", "goalsPer605v5", "assistsPer605v5",
        "pointsPer605v5", "primaryAssistsPer605v5", "secondaryAssistsPer605v5", "onIceShootingPct5v5",
    ],
    "timeonice": [
        "playerId", "timeOnIce", "evTimeOnIcePerGame", "ppTimeOnIcePerGame", "shTimeOnIcePerGame",
        "shifts", "shiftsPerGame", "timeOnIcePerShift",
    ],
    "powerplay": [
        "playerId", "ppAssists", "ppShots", "ppShootingPct", "ppGoalsPer60", "ppPointsPer60",
        "ppTimeOnIce", "ppTimeOnIcePctPerGame", "ppPrimaryAssists",
    ],
    "penaltykill": [
        "playerId", "shAssists", "shShots", "shGoalsPer60", "shPointsPer60", "shTimeOnIce",
        "shTimeOnIcePctPerGame", "ppGoalsAgainstPer60",
    ],
    "penalties": [
        "playerId", "minorPenalties", "majorPenalties", "penaltiesDrawn", "penaltiesDrawnPer60",
        "penaltiesTakenPer60", "netPenalties", "netPenaltiesPer60",
    ],
    "faceoffpercentages": [
        "playerId", "totalFaceoffs", "evFaceoffPct", "ppFaceoffPct", "shFaceoffPct",
        "offensiveZoneFaceoffPct", "defensiveZoneFaceoffPct", "neutralZoneFaceoffPct",
    ],
    "shottype": [
        "playerId", "goalsWrist", "goalsSnap", "goalsSlap", "goalsBackhand", "goalsTipIn",
        "goalsDeflected", "goalsWrapAround", "shotsOnNetWrist", "shotsOnNetSnap", "shotsOnNetSlap",
        "shotsOnNetBackhand", "shotsOnNetTipIn", "shotsOnNetDeflected", "shotsOnNetWrapAround",
        "shootingPctWrist", "shootingPctSnap", "shootingPctSlap", "shootingPctBackhand",
        "shootingPctTipIn",
    ],
    "bios": [
        "playerId", "birthDate", "birthCity", "birthStateProvinceCode", "birthCountryCode",
        "nationalityCode", "height", "weight", "draftYear", "draftRound", "draftOverall",
    ],
}

# Goalie reports — same API family, different endpoint (api.nhle.com/stats/rest/en/goalie/<report>).
GOALIE_REPORTS = {
    "summary": [
        "playerId", "goalieFullName", "teamAbbrevs", "shootsCatches", "gamesPlayed", "gamesStarted",
        "wins", "losses", "otLosses", "goalsAgainst", "goalsAgainstAverage", "shotsAgainst", "saves",
        "savePct", "shutouts", "timeOnIce",
    ],
    "advanced": [
        "playerId", "completeGames", "completeGamePct", "incompleteGames", "qualityStart",
        "qualityStartsPct", "regulationWins", "regulationLosses", "goalsFor", "goalsForAverage",
        "shotsAgainstPer60",
    ],
    "bios": [
        "playerId", "birthDate", "birthCity", "birthStateProvinceCode", "birthCountryCode",
        "nationalityCode", "height", "weight", "draftYear", "draftRound", "draftOverall",
    ],
}

# MoneyPuck column -> our column. Pulled for situation == "all" except the
# 5v5 on-ice share, which is the possession-quality stat people mean by xGF%.
MONEYPUCK_ALL = {
    "I_F_xGoals": "ixG",
    "I_F_highDangerxGoals": "ixG_high_danger",
    "I_F_highDangerShots": "high_danger_shots",
    "OnIce_F_xGoals": "onice_xGF",
    "OnIce_A_xGoals": "onice_xGA",
    "onIce_xGoalsPercentage": "xGF_pct_all",
    "offIce_xGoalsPercentage": "office_xGF_pct",
}
MONEYPUCK_5V5 = {
    "onIce_xGoalsPercentage": "xGF_pct_5v5",
    "I_F_xGoals": "ixG_5v5",
}

# Goalies: MoneyPuck's per-goalie CSV has actual xGoals-against (not a
# per-skater on-ice share), so GSAx = xGA - goalsAgainst is computed in the
# app layer from these two raw columns, same pattern as skaters' finishing
# (goals - ixG).
GOALIE_MONEYPUCK_ALL = {
    "xGoals": "xGA",
    "highDangerxGoals": "xGA_high_danger",
}
GOALIE_MONEYPUCK_5V5 = {
    "xGoals": "xGA_5v5",
}


def _with_retries(fn, label, attempts=3):
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                raise
            print(f"  {label} failed ({e!r}), retrying...", flush=True)
            time.sleep(5 * (i + 1))


def fetch_report(report: str, season_id: int) -> pd.DataFrame:
    def _get():
        resp = requests.get(
            f"https://api.nhle.com/stats/rest/en/skater/{report}",
            params={"cayenneExp": f"seasonId={season_id} and gameTypeId=2", "limit": -1},
            timeout=30, headers=HEADERS,
        )
        resp.raise_for_status()
        return pd.DataFrame(resp.json().get("data", []))

    df = _with_retries(_get, f"{report} {season_id}")
    keep = [c for c in REPORTS[report] if c in df.columns]
    return df[keep] if not df.empty else pd.DataFrame(columns=REPORTS[report])


def fetch_moneypuck(start_year: int) -> pd.DataFrame:
    def _get():
        resp = requests.get(
            f"https://moneypuck.com/moneypuck/playerData/seasonSummary/{start_year}/regular/skaters.csv",
            timeout=60, headers=HEADERS,
        )
        resp.raise_for_status()
        return pd.read_csv(io.StringIO(resp.text))

    df = _with_retries(_get, f"moneypuck {start_year}")
    if df.empty or "playerId" not in df.columns:
        return pd.DataFrame(columns=["playerId"])
    all_sit = df[df["situation"] == "all"][["playerId"] + list(MONEYPUCK_ALL)].rename(columns=MONEYPUCK_ALL)
    five = df[df["situation"] == "5on5"][["playerId"] + list(MONEYPUCK_5V5)].rename(columns=MONEYPUCK_5V5)
    out = all_sit.merge(five, on="playerId", how="left")
    # MoneyPuck's percentages are 0-1 fractions; store as 0-100 like the NHL API's.
    for c in ("xGF_pct_all", "office_xGF_pct", "xGF_pct_5v5"):
        if c in out.columns:
            out[c] = out[c] * 100
    return out


def fetch_goalie_report(report: str, season_id: int) -> pd.DataFrame:
    def _get():
        resp = requests.get(
            f"https://api.nhle.com/stats/rest/en/goalie/{report}",
            params={"cayenneExp": f"seasonId={season_id} and gameTypeId=2", "limit": -1},
            timeout=30, headers=HEADERS,
        )
        resp.raise_for_status()
        return pd.DataFrame(resp.json().get("data", []))

    df = _with_retries(_get, f"goalie/{report} {season_id}")
    keep = [c for c in GOALIE_REPORTS[report] if c in df.columns]
    return df[keep] if not df.empty else pd.DataFrame(columns=GOALIE_REPORTS[report])


def fetch_goalie_moneypuck(start_year: int) -> pd.DataFrame:
    def _get():
        resp = requests.get(
            f"https://moneypuck.com/moneypuck/playerData/seasonSummary/{start_year}/regular/goalies.csv",
            timeout=60, headers=HEADERS,
        )
        resp.raise_for_status()
        return pd.read_csv(io.StringIO(resp.text))

    df = _with_retries(_get, f"moneypuck goalies {start_year}")
    if df.empty or "playerId" not in df.columns:
        return pd.DataFrame(columns=["playerId"])
    all_sit = df[df["situation"] == "all"][["playerId"] + list(GOALIE_MONEYPUCK_ALL)].rename(columns=GOALIE_MONEYPUCK_ALL)
    five = df[df["situation"] == "5on5"][["playerId"] + list(GOALIE_MONEYPUCK_5V5)].rename(columns=GOALIE_MONEYPUCK_5V5)
    return all_sit.merge(five, on="playerId", how="left")


def build_goalie_season(start_year: int) -> pd.DataFrame:
    season_id = int(f"{start_year}{start_year + 1}")
    merged = None
    for report in GOALIE_REPORTS:
        df = fetch_goalie_report(report, season_id)
        print(f"  goalie/{report}: {len(df)} rows", flush=True)
        merged = df if merged is None else merged.merge(df, on="playerId", how="left")
    mp = fetch_goalie_moneypuck(start_year)
    print(f"  moneypuck goalie xGA: {len(mp)} rows", flush=True)
    merged = merged.merge(mp, on="playerId", how="left")

    for c in ["savePct", "completeGamePct", "qualityStartsPct"]:
        if c in merged.columns:
            merged[c] = pd.to_numeric(merged[c], errors="coerce") * 100
    merged["season"] = start_year
    return merged


def store_goalie_season(df: pd.DataFrame, start_year: int) -> None:
    NHL_DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            existing = {r[1] for r in conn.execute("PRAGMA table_info(goalies)")}
            if existing and existing != set(df.columns):
                conn.execute("DROP TABLE goalies")
            else:
                conn.execute("DELETE FROM goalies WHERE season = ?", (start_year,))
        except sqlite3.OperationalError:
            pass
        df.to_sql("goalies", conn, if_exists="append", index=False)
        conn.commit()


def build_season(start_year: int) -> pd.DataFrame:
    season_id = int(f"{start_year}{start_year + 1}")
    merged = None
    for report in REPORTS:
        df = fetch_report(report, season_id)
        print(f"  {report}: {len(df)} rows", flush=True)
        merged = df if merged is None else merged.merge(df, on="playerId", how="left")
    mp = fetch_moneypuck(start_year)
    print(f"  moneypuck xG: {len(mp)} rows", flush=True)
    merged = merged.merge(mp, on="playerId", how="left")

    # NHL API percentage fields arrive as 0-1 fractions — normalize to 0-100.
    for c in ["shootingPct", "faceoffWinPct", "satPercentage", "usatPercentage", "shootingPct5v5",
              "skaterSavePct5v5", "skaterShootingPlusSavePct5v5", "zoneStartPct5v5",
              "onIceShootingPct5v5", "ppShootingPct", "evFaceoffPct", "ppFaceoffPct", "shFaceoffPct",
              "offensiveZoneFaceoffPct", "defensiveZoneFaceoffPct", "neutralZoneFaceoffPct",
              "shootingPctWrist", "shootingPctSnap", "shootingPctSlap", "shootingPctBackhand",
              "shootingPctTipIn", "ppTimeOnIcePctPerGame", "shTimeOnIcePctPerGame"]:
        if c in merged.columns:
            merged[c] = pd.to_numeric(merged[c], errors="coerce") * 100
    merged["season"] = start_year
    return merged


def store_season(df: pd.DataFrame, start_year: int) -> None:
    NHL_DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            existing = {r[1] for r in conn.execute("PRAGMA table_info(skaters)")}
            if existing and existing != set(df.columns):
                conn.execute("DROP TABLE skaters")
            else:
                conn.execute("DELETE FROM skaters WHERE season = ?", (start_year,))
        except sqlite3.OperationalError:
            pass
        df.to_sql("skaters", conn, if_exists="append", index=False)
        conn.commit()


def record_refresh() -> None:
    """Stamp the Pacific date of a completed refresh, matching what the MLB
    and NFL ingests do.

    This is what the Settings freshness panel reads. Without it NHL showed a
    permanent blank there — indistinguishable from "never ran" — which is
    exactly the kind of silent gap that let the site sit stale for days
    before anyone noticed."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    NHL_DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(NHL_DB_PATH) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS refresh_log "
            "(date TEXT PRIMARY KEY, finished_at TEXT)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO refresh_log VALUES (?, ?)",
            (datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat(),
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        conn.commit()


def latest_season_start_year() -> int:
    """NHL seasons start in October; before October the latest complete
    season is the one that started last year."""
    today = date.today()
    return today.year if today.month >= 10 else today.year - 1


def update_latest() -> None:
    yr = latest_season_start_year()
    print(f"=== NHL skaters {yr}-{yr + 1} ===")
    store_season(build_season(yr), yr)
    print(f"=== NHL goalies {yr}-{yr + 1} ===")
    store_goalie_season(build_goalie_season(yr), yr)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        start = int(sys.argv[1])
        end = int(sys.argv[2]) if len(sys.argv) > 2 else start
        for yr in range(start, end + 1):
            print(f"=== NHL skaters {yr}-{yr + 1} ===")
            df = build_season(yr)
            store_season(df, yr)
            print(f"  stored {len(df)} skaters")
            print(f"=== NHL goalies {yr}-{yr + 1} ===")
            gdf = build_goalie_season(yr)
            store_goalie_season(gdf, yr)
            print(f"  stored {len(gdf)} goalies")
    else:
        update_latest()
    record_refresh()
    print("done")
