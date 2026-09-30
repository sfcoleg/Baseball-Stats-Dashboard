"""NHL game-odds model, v2 — a logistic regression that blends the fitted
Elo rating (ingest/nhl_elo.py) with situational features Elo ignores by
construction: rest/fatigue and short-term form. Same role as MLB's
train_win_model.py: an offline trainer that writes a small JSON artifact
(app/nhl/win_model_params.json) the live app applies with a dot product
and a sigmoid — no ML dependency at request time, and it replaces
game_win_prob()'s Elo-only formula rather than running alongside it.

Why add features on top of Elo instead of just re-tuning Elo: Elo's own
holdout Brier (0.2507, see elo_model.json) is statistically indistinguishable
from always guessing 50% — a pure rating-diff signal isn't enough. Rest and
recent form are both public pre-game information Elo has no way to encode
(it only sees final scores, not schedule density or which way a team is
trending), so folding them into a second-stage regression is the standard
next step, same idea as adding starter ERA on top of raw record for MLB.

Run manually: venv/bin/python ingest/nhl_win_model.py 2021 2025
(same season range nhl_elo.py uses; requires elo_model.json already fit
through at least the same end season — run nhl_elo.py first if needed).

Leakage discipline (why each feature is knowable BEFORE the game):
  - d_elo: the Elo rating difference (home rating + home-ice bonus, minus
    away rating) ENTERING the game — same walk nhl_elo.py does, just
    captured before the update instead of after. Uses the already-tuned
    (k_factor, home_advantage) from elo_model.json rather than re-fitting
    Elo itself; this script only fits how much weight to put on Elo
    relative to the new features.
  - d_rest: (home rest days) - (away rest days), each the number of days
    since that team's last game, capped at REST_CAP so a rare 10-day
    All-Star break doesn't dominate. A team's first game in the dataset
    gets the average (DEFAULT_REST) rest, not a leakage-free zero.
  - d_win10 / d_gd10: shrunk win% and goal-differential-per-game over each
    team's last WINDOW games STRICTLY before this one (state updates only
    after the row is recorded, identical ordering discipline to MLB's
    d_win/d_rundiff). Shrunk toward .500 / 0 with K_SHRINK pseudo-games so
    a team's first few games of a season don't scream.

Evaluation is walk-forward: validate on 2024-2025, test on 2025-2026 (the
two most recently completed seasons as of this writing), same discipline
as train_win_model.py. Baselines reported on the identical rows: the Elo
model alone, and always-picking-home.

Training itself is plain-numpy full-batch gradient descent on
L2-regularized logistic loss over standardized features — 4 features and
a few thousand rows need nothing fancier.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nhl_elo import (  # noqa: E402
    RELOCATIONS, REGRESSION, START_RATING, _get_rating, expected_home_win, season_results,
)

ELO_PATH = Path(__file__).resolve().parent.parent / "app" / "nhl" / "elo_model.json"
OUT_PATH = Path(__file__).resolve().parent.parent / "app" / "nhl" / "win_model_params.json"

VALIDATE_SEASON = 2024
TEST_SEASON = 2025

WINDOW = 10          # games of recent form
K_SHRINK = 5         # pseudo-games of .500/0 blended into the form window
REST_CAP = 5         # days
DEFAULT_REST = 2      # rest assumed for a team's first game in the dataset

FEATURES = ["d_elo", "d_rest", "d_win10", "d_gd10"]
L2_LAMBDA = 1e-4
LEARNING_RATE = 0.5
ITERATIONS = 4000


def _rest_days(last_date: str | None, this_date: str) -> float:
    if last_date is None:
        return DEFAULT_REST
    from datetime import date as _date
    d0 = _date.fromisoformat(last_date)
    d1 = _date.fromisoformat(this_date)
    return min((d1 - d0).days, REST_CAP)


def shrunk_pct(wins: float, games: float, k: float) -> float:
    return (wins + 0.5 * k) / (games + k)


def build_feature_rows(all_season_games: list[list[dict]], k: float, home_adv: float) -> list[dict]:
    """Single chronological pass across every season, carrying Elo ratings
    and each team's rolling game log forward — the same walk-forward
    ordering nhl_elo.py uses for ratings, extended to also capture rest
    and recent form entering each game."""
    ratings: dict[str, float] = {}
    logs: dict[str, list[tuple]] = {}  # abbr -> [(date, win, goal_diff), ...]
    rows = []
    for season_idx, games in enumerate(all_season_games):
        if season_idx > 0:
            for team in list(ratings):
                ratings[team] = START_RATING + REGRESSION * (ratings[team] - START_RATING)
        for g in games:
            elo_home, elo_away = _get_rating(ratings, g["home"]), _get_rating(ratings, g["away"])
            p_elo = expected_home_win(elo_home, elo_away, home_adv)
            d_elo = (elo_home + home_adv) - elo_away

            h_log = logs.setdefault(g["home"], [])
            a_log = logs.setdefault(g["away"], [])
            d_rest = _rest_days(h_log[-1][0] if h_log else None, g["date"]) - \
                _rest_days(a_log[-1][0] if a_log else None, g["date"])

            def _form(log: list[tuple]) -> tuple[float, float]:
                window = log[-WINDOW:]
                if not window:
                    return 0.5, 0.0
                wins = sum(1 for _, w, _ in window if w)
                gd = sum(gd for _, _, gd in window)
                return shrunk_pct(wins, len(window), K_SHRINK), gd / (len(window) + K_SHRINK)

            h_win10, h_gd10 = _form(h_log)
            a_win10, a_gd10 = _form(a_log)

            home_won = g["home_score"] > g["away_score"]
            rows.append({
                "d_elo": d_elo, "d_rest": d_rest,
                "d_win10": h_win10 - a_win10, "d_gd10": h_gd10 - a_gd10,
                "y": 1.0 if home_won else 0.0,
                "p_elo": p_elo, "season_idx": season_idx,
            })

            goal_diff = abs(g["home_score"] - g["away_score"])
            mov = (goal_diff + 1) ** 0.6
            delta = k * mov * ((1.0 if home_won else 0.0) - p_elo)
            ratings[g["home"]] = elo_home + delta
            ratings[g["away"]] = elo_away - delta

            h_log.append((g["date"], home_won, g["home_score"] - g["away_score"]))
            a_log.append((g["date"], not home_won, g["away_score"] - g["home_score"]))
    return rows


def to_matrix(rows: list[dict], features: list[str] = FEATURES) -> tuple[np.ndarray, np.ndarray]:
    X = np.array([[r[f] for f in features] for r in rows], dtype=float)
    y = np.array([r["y"] for r in rows], dtype=float)
    return X, y


def train_logistic(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float, np.ndarray, np.ndarray]:
    mean, std = X.mean(axis=0), X.std(axis=0)
    std[std == 0] = 1.0
    Z = (X - mean) / std
    n = len(y)
    w, b = np.zeros(Z.shape[1]), 0.0
    for _ in range(ITERATIONS):
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


def main():
    start_year = int(sys.argv[1]) if len(sys.argv) > 1 else 2021
    end_year = int(sys.argv[2]) if len(sys.argv) > 2 else 2025

    if not ELO_PATH.exists():
        print("app/nhl/elo_model.json not found — run ingest/nhl_elo.py first.")
        return
    elo_model = json.loads(ELO_PATH.read_text())
    k, home_adv = elo_model["k_factor"], elo_model["home_advantage"]
    print(f"Using tuned Elo (k={k}, home_advantage={home_adv}) from elo_model.json")

    print(f"Fetching results for {start_year}-{end_year}...")
    all_games = []
    for yr in range(start_year, end_year + 1):
        games = season_results(yr)
        print(f"  {yr}-{yr + 1}: {len(games)} games")
        all_games.append(games)

    rows = build_feature_rows(all_games, k, home_adv)
    season_years = list(range(start_year, end_year + 1))
    rows_by_season = {}
    for season_idx, yr in enumerate(season_years):
        rows_by_season[yr] = [r for r in rows if r["season_idx"] == season_idx]

    def gather(lo, hi):
        out = []
        for yr in range(lo, hi + 1):
            out.extend(rows_by_season.get(yr, []))
        return out

    report = {}
    evals = [
        ("validate", VALIDATE_SEASON, start_year, VALIDATE_SEASON - 1),
        ("test", TEST_SEASON, start_year, TEST_SEASON - 1),
    ]
    for label, eval_season, tr_lo, tr_hi in evals:
        eval_rows = rows_by_season.get(eval_season, [])
        train_rows = gather(tr_lo, tr_hi)
        if not eval_rows or not train_rows:
            continue
        Xt, yt = to_matrix(train_rows)
        w, b, mean, std = train_logistic(Xt, yt)
        Xe, ye = to_matrix(eval_rows)
        pe = predict(Xe, w, b, mean, std)
        p_elo_only = np.array([r["p_elo"] for r in eval_rows])
        report[label] = {
            "season": eval_season,
            "trained_on": f"{tr_lo}-{tr_hi}",
            "model": metrics(ye, pe),
            "elo_only": metrics(ye, p_elo_only),
            "always_home": metrics(ye, np.full(len(ye), 0.55)),
        }
        m = report[label]
        print(f"\n=== {label}: {eval_season}-{eval_season + 1} (trained {m['trained_on']}) ===")
        print(f"  model:      acc {m['model']['accuracy']:.4f}  logloss {m['model']['log_loss']:.4f}  brier {m['model']['brier']:.4f}  (n={m['model']['n']})")
        print(f"  elo only:   acc {m['elo_only']['accuracy']:.4f}  logloss {m['elo_only']['log_loss']:.4f}  brier {m['elo_only']['brier']:.4f}")
        print(f"  always-home:acc {m['always_home']['accuracy']:.4f}  logloss {m['always_home']['log_loss']:.4f}  brier {m['always_home']['brier']:.4f}")

    # Final artifact fit through TEST_SEASON, same "never train on the
    # number you report" discipline as MLB — the test-season metrics above
    # already describe out-of-sample performance for a model trained
    # without that season; THIS fit additionally folds test-season games
    # in so the shipped coefficients use every completed season available.
    final_rows = gather(start_year, end_year)
    Xf, yf = to_matrix(final_rows)
    w, b, mean, std = train_logistic(Xf, yf)
    print(f"\nFinal fit on {start_year}-{end_year}: {len(yf)} games")
    for f, wi in zip(FEATURES, w):
        print(f"  {f}: {wi:+.4f} (standardized)")
    print(f"  intercept: {b:+.4f} -> baseline home win prob {1 / (1 + np.exp(-b)):.3f}")

    params = {
        "version": 1,
        "trained_through": f"{end_year}-{end_year + 1}",
        "train_seasons": f"{start_year}-{end_year}",
        "features": FEATURES,
        "coef": [float(v) for v in w],
        "intercept": float(b),
        "mean": [float(v) for v in mean],
        "std": [float(v) for v in std],
        "window": WINDOW, "k_shrink": K_SHRINK, "rest_cap": REST_CAP, "default_rest": DEFAULT_REST,
        "elo_k_factor": k, "elo_home_advantage": home_adv,
        "metrics": report,
    }
    OUT_PATH.write_text(json.dumps(params, indent=2))
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    sys.exit(main())
