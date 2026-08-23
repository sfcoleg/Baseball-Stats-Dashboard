"""SLOT — Shot Location & Outcome Threat: Diamond Metrics' own expected-goals
model for the NHL.

Given an unblocked shot attempt, SLOT estimates the probability it becomes a
goal from where it was taken (distance and angle to the net), how it was taken
(shot type), the game state it was taken in (skater strength, empty net), and
whether it came off a rebound. It is deliberately shooter-agnostic — no player
identity is a feature — so that a skater's goals ABOVE SLOT measures finishing
talent, and a goalie's goals-saved-below is save talent (GSAx).

Why we train our own instead of using MoneyPuck's xG: owning the model means
we can score any shot on demand (danger-zone surfaces, per-player signatures,
what-if grids) rather than only the shots someone else has published, and the
methodology is ours to document and defend.

Sample: unblocked shot attempts only (Fenwick — goals, shots on goal, and
missed shots). Blocked shots are excluded because the NHL records them from
the BLOCKING team's perspective: `eventOwnerTeamId` is the defending team and
the coordinates are where the puck was blocked, not where it was shot from, so
they'd enter the model mirrored to the wrong end of the ice. Shootout attempts
(period 5) are excluded too — a penalty-shot-style breakaway is a different
process from an in-play shot.

Validation is a temporal holdout: train on the earliest ~80% of the season's
games, score the last ~20% the model never saw, and report against two
baselines (a constant league shooting rate and a distance-only logistic). The
shipped model is then refit on all games.

Usage:
    python ingest/nhl_xg.py            # train, validate, score every shot
    python ingest/nhl_xg.py --no-score # train and report only
"""
import argparse
import json
import math
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

ROOT = Path(__file__).resolve().parent.parent
NHL_DB_PATH = ROOT / "data" / "nhl.db"
MODEL_DIR = ROOT / "app" / "nhl"
METRICS_PATH = MODEL_DIR / "slot_model.json"
MODEL_PATH = MODEL_DIR / "slot_model.joblib"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# Regulation: goal line 89 ft from center ice, net centered on y=0. Coordinates
# in `shots` are already normalized to attack the right-hand goal (see
# nhl_shots.py::_normalize_side), so the target is always (89, 0).
GOAL_X, GOAL_Y = 89.0, 0.0

UNBLOCKED = ("goal", "shot-on-goal", "missed-shot")
SHOOTOUT_PERIOD = 5
REBOUND_SECONDS = 3.0     # a shot within 3s of the same team's last attempt
MAX_GAP_SECONDS = 60.0    # cap on "time since last attempt" — beyond a minute
                          # the previous shot tells us nothing

NUMERIC_FEATURES = [
    "dist", "angle", "x", "abs_y",
    "skater_diff", "shooter_skaters", "defender_skaters",
    "empty_net", "is_rebound", "secs_since_last", "period", "is_ot",
]
CATEGORICAL_FEATURES = ["shot_type_code"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# No "unknown" bucket on purpose. In this sample every unblocked attempt with
# a missing shotType (30 of them) is a GOAL — the NHL just didn't record a type
# on those — so a missing-type category is perfect target leakage: the model
# learned "type absent" => goal and handed those shots ~0.46 xG against a 0.072
# base rate. Missing and unrecognized types are imputed to the modal type
# instead, which makes missingness carry no signal at all.
SHOT_TYPES = [
    "wrist", "snap", "slap", "tip-in", "backhand", "deflected",
    "wrap-around", "bat", "poke", "between-legs", "cradle",
]
DEFAULT_SHOT_TYPE = "wrist"


# --- games table (home/away, needed to read situationCode) --------------------

def _get_json(url: str, attempts: int = 3):
    for i in range(attempts):
        try:
            r = requests.get(url, timeout=20, headers=HEADERS)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                print(f"  {url} failed ({e!r})", flush=True)
                return None
            time.sleep(3 * (i + 1))


def build_games_table(seasons: list[int]) -> pd.DataFrame:
    """gamePk -> date, home/away team ids, for every regular-season game in
    the given seasons. Needed because `situationCode` is written from the
    home team's point of view ([awayGoalie][awaySkaters][homeSkaters]
    [homeGoalie]) — without knowing which side the shooter is on, a "1451"
    could be either a power play or a penalty kill.

    Walks the schedule week by week (each call returns 7 days plus a
    nextStartDate), so a full season is ~30 requests rather than one per game.
    """
    rows = []
    for start_year in seasons:
        cursor, stop, seen = f"{start_year}-10-01", f"{start_year + 1}-07-01", set()
        while cursor < stop:
            payload = _get_json(f"https://api-web.nhle.com/v1/schedule/{cursor}")
            if not payload:
                break
            for day in payload.get("gameWeek", []):
                if day["date"] in seen:
                    continue
                seen.add(day["date"])
                for g in day.get("games", []):
                    if g.get("gameType") != 2 or g.get("gameState") not in ("OFF", "FINAL"):
                        continue
                    rows.append({
                        "gamePk": g["id"], "season": start_year, "date": day["date"],
                        "homeTeamId": g["homeTeam"]["id"], "awayTeamId": g["awayTeam"]["id"],
                    })
            nxt = payload.get("nextStartDate")
            if not nxt or nxt <= cursor:
                break
            cursor = nxt
        print(f"  {start_year}-{start_year + 1}: {sum(r['season'] == start_year for r in rows)} games", flush=True)
    df = pd.DataFrame(rows).drop_duplicates("gamePk")
    if not df.empty:
        with sqlite3.connect(NHL_DB_PATH) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS games "
                         "(gamePk INTEGER PRIMARY KEY, season INTEGER, date TEXT, "
                         "homeTeamId INTEGER, awayTeamId INTEGER)")
            conn.executemany(
                "INSERT OR REPLACE INTO games VALUES (?,?,?,?,?)",
                df[["gamePk", "season", "date", "homeTeamId", "awayTeamId"]].itertuples(index=False, name=None),
            )
            conn.commit()
    return df


def ensure_games_table() -> pd.DataFrame:
    with sqlite3.connect(NHL_DB_PATH) as conn:
        shot_seasons = [r[0] for r in conn.execute("SELECT DISTINCT season FROM shots ORDER BY season")]
        try:
            have = pd.read_sql("SELECT * FROM games", conn)
        except Exception:  # noqa: BLE001
            have = pd.DataFrame()
    missing = [s for s in shot_seasons if have.empty or s not in set(have.get("season", []))]
    if missing:
        print(f"Building games table for seasons {missing}...", flush=True)
        build_games_table(missing)
        with sqlite3.connect(NHL_DB_PATH) as conn:
            have = pd.read_sql("SELECT * FROM games", conn)
    return have


# --- features ----------------------------------------------------------------

def _seconds(t) -> float:
    """'MM:SS' within a period -> seconds."""
    try:
        m, s = str(t).split(":")
        return int(m) * 60 + int(s)
    except Exception:  # noqa: BLE001
        return np.nan


def _parse_situation(code, is_home: bool):
    """situationCode -> (shooter skaters, defending skaters, defending net empty).

    The code is 4 digits from the home team's perspective:
    [away goalie on ice][away skaters][home skaters][home goalie on ice].
    """
    s = str(code).zfill(4)
    if len(s) != 4 or not s.isdigit():
        return np.nan, np.nan, np.nan
    away_goalie, away_skaters, home_skaters, home_goalie = (int(c) for c in s)
    if is_home:
        return home_skaters, away_skaters, int(away_goalie == 0)
    return away_skaters, home_skaters, int(home_goalie == 0)


def load_attempts() -> pd.DataFrame:
    """Unblocked, non-shootout shot attempts joined to home/away, with every
    model feature derived."""
    games = ensure_games_table()
    with sqlite3.connect(NHL_DB_PATH) as conn:
        shots = pd.read_sql("SELECT * FROM shots", conn)

    df = shots[shots["result"].isin(UNBLOCKED) & (shots["period"] != SHOOTOUT_PERIOD)].copy()
    df = df.merge(games[["gamePk", "date", "homeTeamId"]], on="gamePk", how="left")
    before = len(df)
    df = df.dropna(subset=["x", "y", "homeTeamId"])
    if len(df) < before:
        print(f"  dropped {before - len(df)} attempts with no coords or unknown home team", flush=True)

    df["is_goal"] = (df["result"] == "goal").astype(int)
    df["is_home"] = df["teamId"] == df["homeTeamId"]

    # Geometry. Shots from behind the goal line get angle > 90 degrees, which
    # is exactly the signal we want for wrap-arounds and bad-angle attempts.
    dx = GOAL_X - df["x"]
    dy = df["y"] - GOAL_Y
    df["dist"] = np.sqrt(dx ** 2 + dy ** 2)
    df["angle"] = np.degrees(np.arctan2(dy.abs(), dx))
    df["abs_y"] = df["y"].abs()

    # Game state.
    parsed = [_parse_situation(c, h) for c, h in zip(df["situationCode"], df["is_home"])]
    df["shooter_skaters"] = [p[0] for p in parsed]
    df["defender_skaters"] = [p[1] for p in parsed]
    df["empty_net"] = [p[2] for p in parsed]
    df["skater_diff"] = df["shooter_skaters"] - df["defender_skaters"]
    df["is_ot"] = (df["period"] >= 4).astype(int)

    # Sequence: rebounds and time since the previous attempt, within a period.
    df["secs"] = df["timeInPeriod"].map(_seconds)
    df = df.sort_values(["gamePk", "period", "secs", "eventId"]).reset_index(drop=True)
    grp = df.groupby(["gamePk", "period"], sort=False)
    df["secs_since_last"] = (df["secs"] - grp["secs"].shift(1)).clip(0, MAX_GAP_SECONDS)
    same_team = df["teamId"] == grp["teamId"].shift(1)
    df["is_rebound"] = ((df["secs_since_last"] <= REBOUND_SECONDS) & same_team).fillna(False).astype(int)
    df["secs_since_last"] = df["secs_since_last"].fillna(MAX_GAP_SECONDS)

    shot_type = df["shotType"].fillna(DEFAULT_SHOT_TYPE)
    df["shot_type"] = np.where(shot_type.isin(SHOT_TYPES), shot_type, DEFAULT_SHOT_TYPE)
    df["shot_type_code"] = pd.Categorical(df["shot_type"], categories=SHOT_TYPES).codes

    df = df.dropna(subset=["shooter_skaters", "defender_skaters", "empty_net"])
    return df


# --- training ----------------------------------------------------------------

def _report(name: str, y, p) -> dict:
    """AUC/log-loss/Brier for one model's predictions."""
    p = np.clip(p, 1e-6, 1 - 1e-6)
    out = {
        "model": name,
        "auc": float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else float("nan"),
        "log_loss": float(log_loss(y, p)),
        "brier": float(brier_score_loss(y, p)),
    }
    print(f"    {name:<24} AUC {out['auc']:.4f}   logloss {out['log_loss']:.4f}   Brier {out['brier']:.5f}", flush=True)
    return out


def _calibration(y, p, bins: int = 10) -> list[dict]:
    """Reliability table: within each predicted-probability decile, does the
    average prediction match the observed goal rate?"""
    q = pd.qcut(pd.Series(p), bins, labels=False, duplicates="drop")
    rows = []
    for b in sorted(pd.Series(q).dropna().unique()):
        m = q == b
        rows.append({
            "bin": int(b) + 1, "n": int(m.sum()),
            "predicted": float(np.mean(np.asarray(p)[m])),
            "actual": float(np.mean(np.asarray(y)[m])),
        })
    return rows


def _fit(X: pd.DataFrame, y) -> HistGradientBoostingClassifier:
    cat_mask = [f in CATEGORICAL_FEATURES for f in FEATURES]
    model = HistGradientBoostingClassifier(
        loss="log_loss", learning_rate=0.06, max_iter=400, max_leaf_nodes=31,
        min_samples_leaf=60, l2_regularization=1.0, early_stopping=True,
        validation_fraction=0.12, n_iter_no_change=25, random_state=17,
        categorical_features=cat_mask,
    )
    model.fit(X[FEATURES], y)
    return model


def train(df: pd.DataFrame) -> dict:
    df = df.sort_values(["date", "gamePk"]).reset_index(drop=True)
    game_order = df["gamePk"].drop_duplicates().tolist()
    cut = game_order[int(len(game_order) * 0.8)]
    train_mask = df["gamePk"].isin(set(game_order[:int(len(game_order) * 0.8)]))
    tr, te = df[train_mask], df[~train_mask]
    print(f"\n  train {len(tr):,} attempts / {tr['is_goal'].sum():,} goals "
          f"({tr['is_goal'].mean() * 100:.2f}%)  |  holdout {len(te):,} / {te['is_goal'].sum():,} "
          f"({te['is_goal'].mean() * 100:.2f}%)", flush=True)
    print(f"  holdout starts at game {cut} ({te['date'].min()})\n  temporal holdout results:", flush=True)

    results = []
    # Baseline 1: everyone shoots at the league's training-set rate.
    base_rate = float(tr["is_goal"].mean())
    results.append(_report("constant league rate", te["is_goal"], np.full(len(te), base_rate)))

    # Baseline 2: distance alone (the single strongest signal in any xG model).
    dist_lr = LogisticRegression(max_iter=1000).fit(tr[["dist"]], tr["is_goal"])
    results.append(_report("distance-only logistic", te["is_goal"], dist_lr.predict_proba(te[["dist"]])[:, 1]))

    # SLOT.
    model = _fit(tr, tr["is_goal"])
    p_te = model.predict_proba(te[FEATURES])[:, 1]
    results.append(_report("SLOT", te["is_goal"], p_te))

    calib = _calibration(te["is_goal"], p_te)
    print("\n  calibration on holdout (predicted vs actual by decile):", flush=True)
    for r in calib:
        print(f"    bin {r['bin']:>2}  n={r['n']:>6,}  predicted {r['predicted']:.4f}   actual {r['actual']:.4f}", flush=True)

    return {
        "name": "SLOT",
        "full_name": "Shot Location & Outcome Threat",
        "trained_at": pd.Timestamp.now("UTC").isoformat(timespec="seconds"),
        "seasons": sorted(int(s) for s in df["season"].unique()),
        "n_attempts": int(len(df)),
        "n_goals": int(df["is_goal"].sum()),
        "features": FEATURES,
        "holdout": {
            "first_game": int(cut),
            "first_date": str(te["date"].min()),
            "n": int(len(te)),
            "n_goals": int(te["is_goal"].sum()),
            "results": results,
            "calibration": calib,
        },
    }


def score_all(df: pd.DataFrame, model) -> None:
    """Write per-shot SLOT values to a `shot_xg` table.

    Kept separate from `shots` so re-running the shot backfill (which drops
    and rebuilds that table on a schema change) never silently invalidates
    scores, and so the Streamlit app only ever reads numbers from SQLite —
    it never has to load a pickled sklearn model, which would make the
    deployed site fragile across library versions.
    """
    xg = model.predict_proba(df[FEATURES])[:, 1]
    out = df[["gamePk", "eventId", "season"]].copy()
    out["xg"] = xg
    with sqlite3.connect(NHL_DB_PATH) as conn:
        conn.execute("DROP TABLE IF EXISTS shot_xg")
        conn.execute("CREATE TABLE shot_xg (gamePk INTEGER, eventId INTEGER, season INTEGER, xg REAL, "
                     "PRIMARY KEY (gamePk, eventId))")
        conn.executemany("INSERT OR REPLACE INTO shot_xg VALUES (?,?,?,?)",
                         out.itertuples(index=False, name=None))
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shot_xg_season ON shot_xg(season)")
        conn.commit()
    print(f"\n  scored {len(out):,} attempts into shot_xg "
          f"(total {xg.sum():.1f} xG vs {int(df['is_goal'].sum()):,} actual goals)", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-score", action="store_true", help="train and report only")
    args = ap.parse_args()

    print("=== SLOT (Shot Location & Outcome Threat) ===", flush=True)
    df = load_attempts()
    print(f"  {len(df):,} unblocked attempts, {df['is_goal'].sum():,} goals "
          f"({df['is_goal'].mean() * 100:.2f}%)", flush=True)

    metrics = train(df)

    # Ship a model refit on everything — the holdout above is what tells us
    # how it generalizes; there's no reason to throw away 20% of the data
    # in the version that actually scores shots.
    print("\n  refitting on all games for the shipped model...", flush=True)
    model = _fit(df, df["is_goal"])
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        import joblib
        joblib.dump(model, MODEL_PATH)
        print(f"  wrote {MODEL_PATH}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  (model artifact not saved: {e!r})", flush=True)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    print(f"  wrote {METRICS_PATH}", flush=True)

    if not args.no_score:
        score_all(df, model)
    print("done", flush=True)


if __name__ == "__main__":
    main()
