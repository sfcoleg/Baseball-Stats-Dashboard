"""NHL game-odds model — a margin-of-victory-adjusted Elo rating per team,
fit and backtested on 2021-2026 results, replacing nothing (there's no
prior NHL odds model) but filling the same role as train_win_model.py does
for MLB: an offline trainer that writes a small JSON artifact
(app/nhl/elo_model.json) the live app applies with a dot product and a
sigmoid — no ML dependency at request time.

Why Elo over a fit-features logistic regression (MLB's approach): a
season-by-season regression needs a big, clean historical feature set
(starter quality, rest, etc.) we don't have for NHL yet. Elo needs only
final scores, updates itself online, and is the standard, well-understood
choice for a first game-odds model in a new sport — same methodology
public sites (fivethirtyeight, moneypuck) use for exactly this.

Run manually: venv/bin/python ingest/nhl_elo.py 2021 2025
(backfills that season range and fits+writes the model in one pass).

Methodology:
  - Every team starts at 1500. Between seasons, ratings regress 75% of the
    way back to 1500 (roster turnover) rather than resetting outright.
  - Utah's rating inherits Arizona's (regressed) on relocation — same
    franchise, same roster, not a new team.
  - Expected score is the standard logistic Elo curve with a fitted
    home-ice bonus added to the home team's rating before the comparison.
  - The rating UPDATE is scaled by a margin-of-victory multiplier
    (log(goal diff + 1)) so a 6-1 win moves ratings more than a 2-1 win,
    same shape as fivethirtyeight's NFL/NBA Elo.
  - (K, home_advantage) are grid-searched to minimize Brier score on the
    most recent complete season, held out from that search — walk-forward,
    same discipline as train_win_model.py.
"""
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import requests

HEADERS = {"User-Agent": "Mozilla/5.0"}
OUT_PATH = Path(__file__).resolve().parent.parent / "app" / "nhl" / "elo_model.json"
NHL_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "nhl.db"

RELOCATIONS = {"UTA": "ARI"}  # new_abbr -> old_abbr, rating inherited on first appearance
REGRESSION = 0.75
START_RATING = 1500.0


def _with_retries(fn, label, attempts=3):
    import time
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                print(f"  {label} failed, skipping: {e!r}", flush=True)
                return None
            time.sleep(3 * (i + 1))


def season_results(start_year: int) -> list[dict]:
    """Every finished game (regular season + playoffs) for one season, in
    chronological order: {date, home, away, home_score, away_score}."""
    games, seen_dates = [], set()
    cursor = f"{start_year}-10-01"
    stop = f"{start_year + 1}-07-01"
    while cursor < stop:
        def _get():
            resp = requests.get(f"https://api-web.nhle.com/v1/schedule/{cursor}", timeout=20, headers=HEADERS)
            resp.raise_for_status()
            return resp.json()

        payload = _with_retries(_get, f"schedule {cursor}")
        if not payload:
            break
        for day in payload.get("gameWeek", []):
            if day["date"] in seen_dates:
                continue
            seen_dates.add(day["date"])
            for g in day.get("games", []):
                if g.get("gameType") not in (2, 3) or g.get("gameState") not in ("OFF", "FINAL"):
                    continue
                away, home = g["awayTeam"], g["homeTeam"]
                if "score" not in away or "score" not in home:
                    continue
                games.append({
                    "date": day["date"], "home": home["abbrev"], "away": away["abbrev"],
                    "home_score": home["score"], "away_score": away["score"],
                })
        nxt = payload.get("nextStartDate")
        if not nxt or nxt <= cursor:
            break
        cursor = nxt
    games.sort(key=lambda g: g["date"])
    return games


def _get_rating(ratings: dict, abbr: str) -> float:
    if abbr in ratings:
        return ratings[abbr]
    if abbr in RELOCATIONS and RELOCATIONS[abbr] in ratings:
        return ratings[RELOCATIONS[abbr]]
    return START_RATING


def expected_home_win(elo_home: float, elo_away: float, home_adv: float) -> float:
    return 1.0 / (1.0 + 10 ** (((elo_away) - (elo_home + home_adv)) / 400))


def run_elo(all_season_games: list[list[dict]], k: float, home_adv: float, record_history: bool = False):
    """Processes seasons in order; returns (final_ratings, predictions, history)
    where predictions is [(is_home_win, predicted_home_win_prob), ...] for
    every game in the LAST season only (the held-out one), and history (only
    populated if record_history) is [{date, season, team, rating}, ...] — one
    row per team per game, its rating AFTER that result. Walking every game
    to reach final ratings already computes this trajectory for free; the
    only reason it wasn't kept before is that fit_and_write() only cared
    about the endpoint. It's what powers a strength-over-time chart."""
    ratings: dict[str, float] = {}
    predictions, history = [], []
    for season_idx, games in enumerate(all_season_games):
        if season_idx > 0:
            for team in list(ratings):
                ratings[team] = START_RATING + REGRESSION * (ratings[team] - START_RATING)
        is_holdout = season_idx == len(all_season_games) - 1
        season_year = None
        for g in games:
            if season_year is None and g["date"]:
                season_year = int(g["date"][:4]) if g["date"][5:7] >= "07" else int(g["date"][:4]) - 1
            elo_home, elo_away = _get_rating(ratings, g["home"]), _get_rating(ratings, g["away"])
            p_home = expected_home_win(elo_home, elo_away, home_adv)
            home_won = g["home_score"] > g["away_score"]
            if is_holdout:
                predictions.append((home_won, p_home))
            goal_diff = abs(g["home_score"] - g["away_score"])
            mov = (goal_diff + 1) ** 0.6  # softer than log for hockey's low-scoring margins
            actual = 1.0 if home_won else 0.0
            delta = k * mov * (actual - p_home)
            ratings[g["home"]] = elo_home + delta
            ratings[g["away"]] = elo_away - delta
            if record_history:
                history.append({"date": g["date"], "season": season_year, "team": g["home"], "rating": ratings[g["home"]]})
                history.append({"date": g["date"], "season": season_year, "team": g["away"], "rating": ratings[g["away"]]})
    return ratings, predictions, history


def brier_and_accuracy(predictions: list[tuple[bool, float]]) -> tuple[float, float]:
    if not predictions:
        return (float("nan"), float("nan"))
    brier = sum((p - (1.0 if won else 0.0)) ** 2 for won, p in predictions) / len(predictions)
    correct = sum((p >= 0.5) == won for won, p in predictions)
    return brier, correct / len(predictions)


def fit_and_write(start_year: int, end_year: int) -> None:
    """Walk-forward, same discipline as train_win_model.py: (K, home_adv)
    are grid-searched against the second-to-last season as a VALIDATION
    holdout (using only earlier seasons' results to enter it), then final
    ratings and the reported metric come from one more pass through the
    true final season — never tuned on the number we report, so the
    reported accuracy isn't inflated by picking whichever grid cell got
    lucky on the only holdout available."""
    print(f"Fetching results for {start_year}-{end_year}...", flush=True)
    all_games = []
    for yr in range(start_year, end_year + 1):
        games = season_results(yr)
        print(f"  {yr}-{yr + 1}: {len(games)} games", flush=True)
        all_games.append(games)

    if len(all_games) < 3:
        print("Need at least 3 seasons (2 to enter validation + 1 to validate on) — aborting.")
        return

    print("Grid-searching (K, home_advantage) against a validation season...", flush=True)
    validation_games = all_games[:-1]  # everything except the true final season
    best = None
    for k in (3, 5, 7, 10, 15, 20, 25, 30):
        row = []
        for home_adv in (0, 15, 25, 40, 50, 65, 80):
            _, preds, _ = run_elo(validation_games, k, home_adv)
            brier, acc = brier_and_accuracy(preds)
            row.append(f"adv{home_adv}:{brier:.4f}/{acc:.3f}")
            if best is None or brier < best[0]:
                best = (brier, acc, k, home_adv)
        print(f"  K={k}: " + "  ".join(row), flush=True)
    val_brier, val_acc, best_k, best_home_adv = best
    print(f"  picked: K={best_k}, home_adv={best_home_adv} "
          f"(validation Brier={val_brier:.4f}, accuracy={val_acc:.3f})", flush=True)

    final_ratings, test_preds, history = run_elo(all_games, best_k, best_home_adv, record_history=True)
    test_brier, test_acc = brier_and_accuracy(test_preds)
    print(f"  true holdout ({end_year}-{end_year + 1}): Brier={test_brier:.4f}, accuracy={test_acc:.3f}", flush=True)

    # Drop relocated-away teams (ARI once UTA exists) from the served ratings.
    for new_abbr, old_abbr in RELOCATIONS.items():
        if new_abbr in final_ratings:
            final_ratings.pop(old_abbr, None)

    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "ratings": {k_: round(v, 1) for k_, v in sorted(final_ratings.items())},
        "k_factor": best_k, "home_advantage": best_home_adv,
        "trained_from": start_year,
        "trained_through": f"{end_year}-{end_year + 1}",
        "current_through": f"{end_year}-{end_year + 1}",
        "holdout_season": f"{end_year}-{end_year + 1}",
        "holdout_brier": round(test_brier, 4), "holdout_accuracy": round(test_acc, 4),
        "n_holdout_games": len(test_preds),
    }, indent=2))
    print(f"Wrote {OUT_PATH}")
    _store_history(history)


def _store_history(history: list[dict]) -> None:
    """Every {date, season, team, rating} row from the most recent run_elo()
    call, replacing whatever was there — this is a full replay each time
    (see advance_ratings), not an incremental log, so overwrite rather than
    append. Powers a team-strength-over-time chart."""
    if not history:
        return
    NHL_DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(NHL_DB_PATH) as conn:
        conn.execute("DROP TABLE IF EXISTS elo_history")
        conn.execute("CREATE TABLE elo_history (date TEXT, season INTEGER, team TEXT, rating REAL)")
        conn.executemany("INSERT INTO elo_history VALUES (?,?,?,?)",
                         [(h["date"], h["season"], h["team"], round(h["rating"], 1)) for h in history])
        conn.execute("CREATE INDEX idx_elo_history_team ON elo_history(team, date)")
        conn.commit()
    print(f"  wrote {len(history):,} elo_history rows", flush=True)


def latest_season_start_year() -> int:
    today = date.today()
    return today.year if today.month >= 10 else today.year - 1


def advance_ratings() -> None:
    """Nightly step: bring ratings current by replaying results through
    today at the ALREADY-VALIDATED (K, home_advantage) — never retuned here,
    since re-fitting nightly would let the model quietly drift out from
    under its own reported holdout accuracy. A deliberate re-fit (running
    this module directly) is a separate, occasional act.

    This is a full replay from the model's original training start through
    the current season, not an incremental update — season_results() is
    already a handful of requests per season (the season's games, walked
    week by week), so a full replay is cheap and, unlike trying to resume
    from a partial state, can't drift from what fit_and_write() would
    produce from scratch."""
    if not OUT_PATH.exists():
        print("  no elo_model.json — run this module directly to do the initial fit")
        return
    model = json.loads(OUT_PATH.read_text())
    start_year = model.get("trained_from", 2021)
    current = latest_season_start_year()

    all_games = [season_results(yr) for yr in range(start_year, current + 1)]
    n_games = sum(len(g) for g in all_games)
    ratings, _, history = run_elo(all_games, model["k_factor"], model["home_advantage"], record_history=True)
    for new_abbr, old_abbr in RELOCATIONS.items():
        if new_abbr in ratings:
            ratings.pop(old_abbr, None)

    model["ratings"] = {k_: round(v, 1) for k_, v in sorted(ratings.items())}
    model["current_through"] = f"{current}-{current + 1}"
    OUT_PATH.write_text(json.dumps(model, indent=2))
    print(f"  advanced ratings through {n_games:,} games ({start_year}-{current + 1}), "
          f"wrote {OUT_PATH}", flush=True)
    _store_history(history)


if __name__ == "__main__":
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 2021
    end = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
    fit_and_write(start, end)
