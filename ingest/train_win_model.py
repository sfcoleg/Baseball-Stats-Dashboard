"""Offline trainer for the Today's Games win-probability model — replaces
predict_game()'s old hand-tuned Log5-plus-adjustments formula with a
logistic regression actually fit to (and backtested against) historical
game outcomes.

Run manually (venv/bin/python ingest/train_win_model.py); takes a few
minutes (one schedule API call per season, 2014-present). Writes
app/win_model_params.json — a tiny artifact of coefficients +
standardization stats + serve-time reference data — which predict_game()
applies with nothing but a dot product and a sigmoid, so the app itself
needs no ML dependency and does no training at request time. Re-run once
a season (early in the new season, after the prior season's pitching
stats are backfilled) to refresh the coefficients and the prior-season
reference data; the params file records what it was trained on.

Leakage discipline (why each feature is knowable BEFORE the game):
  - d_win / d_rundiff: cumulative record and run differential from games
    strictly earlier in the season (state is updated only after a game's
    features are recorded), shrunk toward .500 with K_SHRINK pseudo-games
    so April's tiny samples don't scream.
  - d_prior: the PRIOR season's final record, shrunk with K_PRIOR pseudo-
    games — carries real preseason information (opening-day rosters
    resemble last year's team) and automatically discounts 2020's 60-game
    sample by construction.
  - d_starter_era: the announced probable starter's PRIOR-season ERA (our
    own pitching table). The probable pitcher is public pre-game info —
    confirmed the MLB schedule API preserves it for historical games —
    and prior-season ERA is fixed history. Deliberately NOT the current-
    season ERA the old formula used: mid-season ERA in a training row
    partially reflects games from later in that season, which is leakage.
    Starters with < ERA_IP_MIN prior IP (rookies, September call-ups) get
    that prior season's qualified league-average ERA instead; ERAs are
    clipped to ERA_CLIP so a 27.00 two-outing disaster can't swing a row.
  - intercept: LEARNED home-field advantage, replacing the hand-set 0.04.

2020 is excluded from training/eval rows entirely (60 games, no fans —
documented weaker home-field advantage) but still supplies 2021's
d_prior values.

Evaluation is walk-forward (train past -> test future, never the
reverse): validate on 2024, test on 2025, and out-of-time test on the
current season to date. Baselines reported on the identical games: pick-
home-always, and the old Log5 + 0.04 formula replayed on the same
entering-game records (restricted, for fairness, to games where both
teams had played at least once — the old formula punts on opening day;
the model does not need to).

Training itself is plain-numpy full-batch gradient descent on L2-
regularized logistic loss over standardized features — 4 features and
~20k rows need nothing fancier, and keeping it dependency-free means
nothing new in requirements for either this script or the app.
"""
import json
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import requests

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "stats.db"
PARAMS_PATH = Path(__file__).resolve().parent.parent / "app" / "win_model_params.json"

FIRST_PRIOR_SEASON = 2014   # fetched only to provide 2015's d_prior
FIRST_TRAIN_SEASON = 2015
EXCLUDED_SEASONS = {2020}   # COVID season: 60 games, no fans, weaker HFA
VALIDATE_SEASON = 2024
TEST_SEASON = 2025

K_SHRINK = 10   # pseudo-games of .500 blended into in-season record/run diff
K_PRIOR = 20    # pseudo-games of .500 blended into prior-season record
ERA_IP_MIN = 30
ERA_CLIP = (2.5, 6.5)

FEATURES = ["d_win", "d_rundiff", "d_prior", "d_starter_era"]
# The playoff-odds simulator's variant: no starter feature, because the
# simulator plays out games weeks/months ahead, whose starters are
# unknown. Trained and backtested identically so the artifact carries
# honest metrics for BOTH the Today's Games model and the simulator's.
TEAM_FEATURES = ["d_win", "d_rundiff", "d_prior"]

L2_LAMBDA = 1e-4
LEARNING_RATE = 0.5
ITERATIONS = 4000


def fetch_season_games(season: int, end_date: str | None = None) -> list[dict]:
    """One schedule API call for a whole regular season, with probable
    pitchers hydrated (confirmed populated even for long-past games).
    Returns Final games only, deduped by gamePk (a suspended game can
    appear on both its original and resumption dates), in strict
    chronological order (gameDate timestamps sort doubleheaders
    correctly)."""
    resp = requests.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={
            "sportId": 1, "gameType": "R",
            "startDate": f"{season}-02-20",
            "endDate": end_date or f"{season}-11-30",
            "hydrate": "probablePitcher",
        },
        timeout=120,
    )
    resp.raise_for_status()
    seen, games = set(), []
    for d in resp.json().get("dates", []):
        for g in d.get("games", []):
            if g.get("status", {}).get("detailedState") != "Final":
                continue
            pk = g.get("gamePk")
            if pk in seen:
                continue
            away, home = g["teams"]["away"], g["teams"]["home"]
            if away.get("score") is None or home.get("score") is None:
                continue
            if away["score"] == home["score"]:  # rare official ties
                continue
            seen.add(pk)
            games.append({
                "date": g.get("gameDate", ""),
                "away_id": away["team"]["id"], "home_id": home["team"]["id"],
                "away_score": away["score"], "home_score": home["score"],
                "away_sp": (away.get("probablePitcher") or {}).get("id"),
                "home_sp": (home.get("probablePitcher") or {}).get("id"),
            })
    games.sort(key=lambda g: g["date"])
    return games


def load_pitcher_priors() -> tuple[dict, dict]:
    """{(season, mlbID): ERA} for qualified (IP >= ERA_IP_MIN) pitcher-
    seasons from our own pitching table, plus {season: league-average
    qualified ERA} as the fallback for unqualified/unknown starters."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT season, mlbID, ERA, IP FROM pitching "
            "WHERE ERA IS NOT NULL AND IP >= ? AND mlbID IS NOT NULL",
            (ERA_IP_MIN,),
        ).fetchall()
    era_by_key, sums = {}, {}
    for season, mlbID, era, ip in rows:
        era_by_key[(int(season), int(mlbID))] = float(era)
        s = sums.setdefault(int(season), [0.0, 0])
        s[0] += float(era)
        s[1] += 1
    league = {season: total / n for season, (total, n) in sums.items() if n}
    return era_by_key, league


def shrunk_pct(wins: float, games: float, k: float) -> float:
    return (wins + 0.5 * k) / (games + k)


def starter_prior_era(sp_id, prior_season: int, era_by_key: dict, league_era: dict) -> float:
    fallback = league_era.get(prior_season, 4.3)
    era = era_by_key.get((prior_season, sp_id), fallback) if sp_id else fallback
    return min(max(era, ERA_CLIP[0]), ERA_CLIP[1])


def season_final_records(games: list[dict]) -> dict:
    """{team_id: shrunk final win%} for one season's Final games."""
    w, g = {}, {}
    for game in games:
        winner = game["home_id"] if game["home_score"] > game["away_score"] else game["away_id"]
        for tid in (game["home_id"], game["away_id"]):
            g[tid] = g.get(tid, 0) + 1
        w[winner] = w.get(winner, 0) + 1
    return {tid: shrunk_pct(w.get(tid, 0), g[tid], K_PRIOR) for tid in g}


def build_season_rows(games: list[dict], prior_pct: dict, prior_season: int,
                      era_by_key: dict, league_era: dict) -> list[dict]:
    """Walk one season chronologically, emitting each game's features from
    team state ENTERING that game (state updates only after the row is
    recorded — this ordering is the whole leakage guarantee for d_win and
    d_rundiff)."""
    state = {}  # team_id -> [games, wins, runs_for, runs_against]
    rows = []
    for game in games:
        hs = state.setdefault(game["home_id"], [0, 0, 0, 0])
        as_ = state.setdefault(game["away_id"], [0, 0, 0, 0])
        h_win = shrunk_pct(hs[1], hs[0], K_SHRINK)
        a_win = shrunk_pct(as_[1], as_[0], K_SHRINK)
        h_rd = (hs[2] - hs[3]) / (hs[0] + K_SHRINK)
        a_rd = (as_[2] - as_[3]) / (as_[0] + K_SHRINK)
        h_prior = prior_pct.get(game["home_id"], 0.5)
        a_prior = prior_pct.get(game["away_id"], 0.5)
        h_era = starter_prior_era(game["home_sp"], prior_season, era_by_key, league_era)
        a_era = starter_prior_era(game["away_sp"], prior_season, era_by_key, league_era)
        home_won = game["home_score"] > game["away_score"]
        rows.append({
            "d_win": h_win - a_win,
            "d_rundiff": h_rd - a_rd,
            "d_prior": h_prior - a_prior,
            "d_starter_era": a_era - h_era,  # positive when home has the better starter
            "y": 1.0 if home_won else 0.0,
            # raw entering records, for replaying the old Log5 baseline
            "h_g": hs[0], "h_w": hs[1], "a_g": as_[0], "a_w": as_[1],
        })
        for st_, scored, allowed, won in (
            (hs, game["home_score"], game["away_score"], home_won),
            (as_, game["away_score"], game["home_score"], not home_won),
        ):
            st_[0] += 1
            st_[1] += 1 if won else 0
            st_[2] += scored
            st_[3] += allowed
    return rows


def to_matrix(rows: list[dict], features: list[str] = FEATURES) -> tuple[np.ndarray, np.ndarray]:
    X = np.array([[r[f] for f in features] for r in rows], dtype=float)
    y = np.array([r["y"] for r in rows], dtype=float)
    return X, y


def train_logistic(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float, np.ndarray, np.ndarray]:
    """L2-regularized logistic regression by full-batch gradient descent on
    standardized features. Returns (coef, intercept, mean, std) with coef
    in STANDARDIZED space — apply as sigmoid(((x - mean) / std) @ coef + b)."""
    mean, std = X.mean(axis=0), X.std(axis=0)
    std[std == 0] = 1.0
    Z = (X - mean) / std
    n = len(y)
    w, b = np.zeros(Z.shape[1]), 0.0
    for i in range(ITERATIONS):
        p = 1.0 / (1.0 + np.exp(-(Z @ w + b)))
        grad_w = Z.T @ (p - y) / n + 2 * L2_LAMBDA * w
        grad_b = float(np.mean(p - y))
        w -= LEARNING_RATE * grad_w
        b -= LEARNING_RATE * grad_b
    return w, b, mean, std


def predict(X: np.ndarray, w: np.ndarray, b: float, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-(((X - mean) / std) @ w + b)))


def metrics(y: np.ndarray, p: np.ndarray) -> dict:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return {
        "n": int(len(y)),
        "accuracy": float(np.mean((p >= 0.5) == (y == 1.0))),
        "log_loss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
        "brier": float(np.mean((p - y) ** 2)),
    }


def log5_replay(rows: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The OLD formula's core (raw-win%% Log5 + 0.04 flat home edge) replayed
    on the same entering-game records, on the subset where both teams had
    played at least once (the old formula punted otherwise). Returns
    (mask, y, p) so callers can score the model on the identical subset."""
    mask = np.array([r["h_g"] > 0 and r["a_g"] > 0 for r in rows])
    y, p = [], []
    for r in rows:
        if not (r["h_g"] > 0 and r["a_g"] > 0):
            continue
        h, a = r["h_w"] / r["h_g"], r["a_w"] / r["a_g"]
        denom = h + a - 2 * h * a
        base = 0.5 if denom <= 0 else (h - h * a) / denom
        p.append(min(max(base + 0.04, 0.01), 0.99))
        y.append(r["y"])
    return mask, np.array(y), np.array(p)


def main():
    today = date.today()
    current_season = today.year

    print("Loading prior-season pitcher ERAs from stats.db...")
    era_by_key, league_era = load_pitcher_priors()
    print(f"  {len(era_by_key)} qualified pitcher-seasons, league ERA by season for {len(league_era)} seasons")

    print("Fetching season schedules (one API call each)...")
    season_games = {}
    for season in range(FIRST_PRIOR_SEASON, current_season + 1):
        end = today.isoformat() if season == current_season else None
        season_games[season] = fetch_season_games(season, end_date=end)
        print(f"  {season}: {len(season_games[season])} final games")
        time.sleep(0.5)

    prior_pct = {s: season_final_records(g) for s, g in season_games.items()}

    rows_by_season = {}
    for season in range(FIRST_TRAIN_SEASON, current_season + 1):
        rows_by_season[season] = build_season_rows(
            season_games[season], prior_pct[season - 1], season - 1, era_by_key, league_era,
        )

    def gather(lo, hi):
        out = []
        for s in range(lo, hi + 1):
            if s in EXCLUDED_SEASONS:
                continue
            out.extend(rows_by_season.get(s, []))
        return out

    report = {}
    evals = [
        ("validate", VALIDATE_SEASON, FIRST_TRAIN_SEASON, VALIDATE_SEASON - 1),
        ("test", TEST_SEASON, FIRST_TRAIN_SEASON, TEST_SEASON - 1),
        ("current_season_to_date", current_season, FIRST_TRAIN_SEASON, current_season - 1),
    ]
    for label, eval_season, tr_lo, tr_hi in evals:
        eval_rows = rows_by_season.get(eval_season, [])
        if not eval_rows:
            continue
        train_rows = gather(tr_lo, tr_hi)
        Xt, yt = to_matrix(train_rows)
        w, b, mean, std = train_logistic(Xt, yt)
        Xe, ye = to_matrix(eval_rows)
        pe = predict(Xe, w, b, mean, std)
        Xt2, _ = to_matrix(train_rows, TEAM_FEATURES)
        w2, b2, mean2, std2 = train_logistic(Xt2, yt)
        Xe2, _ = to_matrix(eval_rows, TEAM_FEATURES)
        pe2 = predict(Xe2, w2, b2, mean2, std2)
        mask, y5, p5 = log5_replay(eval_rows)
        report[label] = {
            "season": eval_season,
            "trained_on": f"{tr_lo}-{tr_hi} (ex {sorted(EXCLUDED_SEASONS)})",
            "model": metrics(ye, pe),
            "model_on_log5_subset": metrics(ye[mask], pe[mask]),
            "team_only_model": metrics(ye, pe2),
            "log5_plus_hfa": metrics(y5, p5),
            "always_home": metrics(ye, np.full(len(ye), 0.54)),
        }
        m = report[label]
        print(f"\n=== {label}: {eval_season} (trained {m['trained_on']}) ===")
        print(f"  model:          acc {m['model']['accuracy']:.4f}  logloss {m['model']['log_loss']:.4f}  brier {m['model']['brier']:.4f}  (n={m['model']['n']})")
        print(f"  model (subset): acc {m['model_on_log5_subset']['accuracy']:.4f}  logloss {m['model_on_log5_subset']['log_loss']:.4f}")
        print(f"  team-only:      acc {m['team_only_model']['accuracy']:.4f}  logloss {m['team_only_model']['log_loss']:.4f}  brier {m['team_only_model']['brier']:.4f}")
        print(f"  log5 + 0.04:    acc {m['log5_plus_hfa']['accuracy']:.4f}  logloss {m['log5_plus_hfa']['log_loss']:.4f}  brier {m['log5_plus_hfa']['brier']:.4f}  (n={m['log5_plus_hfa']['n']})")
        print(f"  always-home:    acc {m['always_home']['accuracy']:.4f}  logloss {m['always_home']['log_loss']:.4f}")

    # Final artifact: fit through TEST_SEASON (never the current season —
    # it stays a pure holdout so the reported out-of-time metrics always
    # describe the shipped coefficients' genuinely unseen performance).
    final_rows = gather(FIRST_TRAIN_SEASON, TEST_SEASON)
    Xf, yf = to_matrix(final_rows)
    w, b, mean, std = train_logistic(Xf, yf)
    Xf2, _ = to_matrix(final_rows, TEAM_FEATURES)
    w2, b2, mean2, std2 = train_logistic(Xf2, yf)
    print(f"\nFinal fit on {FIRST_TRAIN_SEASON}-{TEST_SEASON} (ex {sorted(EXCLUDED_SEASONS)}): "
          f"{len(yf)} games")
    for f, wi in zip(FEATURES, w):
        print(f"  {f}: {wi:+.4f} (standardized)")
    print(f"  intercept: {b:+.4f}  -> baseline home win prob {1/(1+np.exp(-b)):.3f}")
    print("  team-only variant:")
    for f, wi in zip(TEAM_FEATURES, w2):
        print(f"    {f}: {wi:+.4f} (standardized)")
    print(f"    intercept: {b2:+.4f}")

    params = {
        "version": 1,
        "trained_through": TEST_SEASON,
        "train_seasons": f"{FIRST_TRAIN_SEASON}-{TEST_SEASON} excluding {sorted(EXCLUDED_SEASONS)}",
        "serve_season": current_season,
        "features": FEATURES,
        "coef": [float(v) for v in w],
        "intercept": float(b),
        "mean": [float(v) for v in mean],
        "std": [float(v) for v in std],
        "team_only": {
            "features": TEAM_FEATURES,
            "coef": [float(v) for v in w2],
            "intercept": float(b2),
            "mean": [float(v) for v in mean2],
            "std": [float(v) for v in std2],
        },
        "k_shrink": K_SHRINK,
        "k_prior": K_PRIOR,
        "era_ip_min": ERA_IP_MIN,
        "era_clip": list(ERA_CLIP),
        # Serve-time reference data: the prior (last completed) season's
        # shrunk final win%% per TEAM ID (ids are stable across the odd
        # abbreviation change, e.g. OAK->ATH), and its league-average
        # qualified ERA as the unknown-starter fallback.
        "prior_season": current_season - 1,
        "prior_winpct_by_team_id": {str(k): round(v, 5) for k, v in prior_pct[current_season - 1].items()},
        "prior_league_era": round(league_era.get(current_season - 1, 4.3), 3),
        "metrics": report,
    }
    PARAMS_PATH.write_text(json.dumps(params, indent=2))
    print(f"\nWrote {PARAMS_PATH}")


if __name__ == "__main__":
    sys.exit(main())
