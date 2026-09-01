"""Offline trainer for the in-game win probability model (the WPA engine).

Learns P(home team wins | game state) from real historical plate
appearances, where a state is (inning, half, outs, base runners, score
diff). Everything heavy stays local: raw Savant play-by-play caches to
ingest/wp_cache/ (gitignored — millions of rows have no business in the
repo), and only the compact fitted artifact (app/wp_model.json) plus its
backtest metrics get committed, same pattern as train_win_model.py.

Model: empirical win rate per state, shrunk toward a logistic baseline
(pure numpy, no new dependencies) so sparse states (extras, blowouts)
inherit sane behavior from the smooth global surface instead of noise.
Leverage Index per state = mean |ΔWP| of real transitions out of that
state — "how much can this moment swing the game."

Seasons: trains on 2021-2025 (the ghost-runner extra-innings rule arrived
in 2020, so pre-2020 extras behave differently and 2020's 60-game sprint
is weird everywhere else too) and validates on 2026-to-date as a true
holdout.

Usage:
    python ingest/train_wp_model.py download   # fetch + cache all seasons
    python ingest/train_wp_model.py train      # fit + validate + write artifact
    python ingest/train_wp_model.py all
"""
import json
import sys
import time
from datetime import date, timedelta
from _dates import pacific_today
from pathlib import Path

import numpy as np
import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent / "wp_cache"
ARTIFACT_PATH = Path(__file__).resolve().parent.parent / "app" / "wp_model.json"

TRAIN_SEASONS = [2021, 2022, 2023, 2024, 2025]
HOLDOUT_SEASON = 2026

# Regular seasons start late March and end early October (2021's started
# April 1; a couple of padding days on each side are harmless — statcast
# just returns nothing for dates without games).
SEASON_RANGES = {
    2021: ("2021-04-01", "2021-10-03"),
    2022: ("2022-04-07", "2022-10-05"),
    2023: ("2023-03-30", "2023-10-01"),
    2024: ("2024-03-20", "2024-09-30"),
    2025: ("2025-03-18", "2025-09-28"),
    2026: ("2026-03-25", None),  # None = through yesterday
}

EVENT_COLS = [
    "game_pk", "game_date", "at_bat_number", "inning", "inning_topbot",
    "outs_when_up", "on_1b", "on_2b", "on_3b", "home_score", "away_score",
    "post_home_score", "post_away_score", "events", "batter", "pitcher", "des",
]

MAX_INNING = 10   # 10 = "any extra inning" bucket
MAX_DIFF = 8      # score diff clipped to ±8
SHRINK_K = 60.0   # pseudo-observations pulling each state toward the baseline


def _with_retries(fn, label, attempts=3):
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                raise
            wait = 15 * (i + 1)
            print(f"  {label} failed ({e!r}), retrying in {wait}s...", flush=True)
            time.sleep(wait)


def download_season(season: int) -> None:
    """Fetch a season of Savant play-by-play in ~2-week chunks, keep only
    the PA-ending rows and the columns the model needs. Each chunk caches
    to its own file so a killed run resumes where it left off."""
    from pybaseball import statcast

    CACHE_DIR.mkdir(exist_ok=True)
    start_s, end_s = SEASON_RANGES[season]
    end_s = end_s or (pacific_today() - timedelta(days=1)).isoformat()
    start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)

    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=13), end)
        out = CACHE_DIR / f"pa_{season}_{chunk_start.isoformat()}.csv"
        if out.exists():
            chunk_start = chunk_end + timedelta(days=1)
            continue
        label = f"statcast {chunk_start} → {chunk_end}"
        raw = _with_retries(
            lambda s=chunk_start, e=chunk_end: statcast(
                start_dt=s.isoformat(), end_dt=e.isoformat(), verbose=False
            ),
            label,
        )
        if raw is not None and not raw.empty:
            pa = raw[raw["events"].notna() & (raw["events"] != "")]
            keep = [c for c in EVENT_COLS if c in pa.columns]
            pa[keep].to_csv(out, index=False)
            print(f"  {label}: {len(pa)} PA rows", flush=True)
        else:
            out.write_text("")  # mark empty range done
        chunk_start = chunk_end + timedelta(days=1)
    print(f"{season}: download complete", flush=True)


# --- State encoding ---------------------------------------------------------

def encode_states(df: pd.DataFrame) -> pd.DataFrame:
    """Add state columns to a PA dataframe. State is always from the HOME
    team's perspective at the moment the PA begins."""
    df = df.copy()
    df["inning_c"] = df["inning"].clip(upper=MAX_INNING).astype(int)
    df["half"] = (df["inning_topbot"] == "Bot").astype(int)
    df["outs"] = df["outs_when_up"].clip(0, 2).astype(int)
    df["base"] = (
        df["on_1b"].notna().astype(int)
        + 2 * df["on_2b"].notna().astype(int)
        + 4 * df["on_3b"].notna().astype(int)
    )
    df["diff"] = (df["home_score"] - df["away_score"]).clip(-MAX_DIFF, MAX_DIFF).astype(int)
    df["state_key"] = (
        df["inning_c"].astype(str) + "|" + df["half"].astype(str) + "|"
        + df["outs"].astype(str) + "|" + df["base"].astype(str) + "|" + df["diff"].astype(str)
    )
    return df


def load_season_events(season: int) -> pd.DataFrame:
    chunks = sorted(CACHE_DIR.glob(f"pa_{season}_*.csv"))
    if not chunks:
        raise FileNotFoundError(f"no cached chunks for {season} — run download first")
    df = pd.concat(
        [pd.read_csv(c) for c in chunks if c.stat().st_size > 0], ignore_index=True
    )
    df = df.dropna(subset=["inning", "inning_topbot", "outs_when_up", "home_score", "away_score"])
    # Outcome: did the home team win this game?
    finals = df.groupby("game_pk").agg(
        h=("post_home_score", "max"), a=("post_away_score", "max")
    )
    finals = finals[finals["h"] != finals["a"]]  # drop suspended/tied oddities
    df = df[df["game_pk"].isin(finals.index)]
    df = df.merge((finals["h"] > finals["a"]).rename("home_win"), on="game_pk")
    return encode_states(df)


# --- Logistic baseline (pure numpy, same approach as train_win_model.py) ----

# Static run-potential weight for each base state (rough RE24 shape) —
# just a feature for the baseline, the empirical table does the real work.
BASE_RUN_POTENTIAL = {0: 0.0, 1: 0.4, 2: 0.6, 3: 0.9, 4: 0.8, 5: 1.2, 6: 1.4, 7: 1.8}


def baseline_features(df: pd.DataFrame) -> np.ndarray:
    # "Half-innings remaining" for the team currently trailing the clock:
    # a smooth time-left axis that makes score leads matter more later.
    half_innings_left = (9 - df["inning_c"]) * 2 + (1 - df["half"]) + 1
    hil = np.maximum(half_innings_left, 1.0)
    diff = df["diff"].astype(float)
    run_pot = df["base"].map(BASE_RUN_POTENTIAL).astype(float)
    # Run potential helps whichever team is batting.
    batting_sign = np.where(df["half"] == 1, 1.0, -1.0)
    x = np.column_stack([
        diff,
        diff / np.sqrt(hil),          # a lead is worth more with less time left
        batting_sign * run_pot / np.sqrt(hil),
        batting_sign * (2 - df["outs"]) / np.sqrt(hil),
        df["half"].astype(float),      # generic home-half indicator
    ])
    return x


def fit_logistic(x: np.ndarray, y: np.ndarray, iters=400, lr=0.5) -> tuple[np.ndarray, float]:
    mean, std = x.mean(axis=0), x.std(axis=0) + 1e-9
    xs = (x - mean) / std
    w = np.zeros(xs.shape[1])
    b = 0.0
    n = len(y)
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(xs @ w + b)))
        grad_w = xs.T @ (p - y) / n
        grad_b = (p - y).mean()
        w -= lr * grad_w
        b -= lr * grad_b
    return w, b, mean, std


def predict_logistic(x, w, b, mean, std):
    xs = (x - mean) / std
    return 1 / (1 + np.exp(-(xs @ w + b)))


# --- Training ---------------------------------------------------------------

def train() -> None:
    print("Loading training seasons...", flush=True)
    train_df = pd.concat([load_season_events(s) for s in TRAIN_SEASONS], ignore_index=True)
    print(f"  {len(train_df)} plate appearances, {train_df['game_pk'].nunique()} games", flush=True)

    y = train_df["home_win"].astype(float).to_numpy()
    x = baseline_features(train_df)
    w, b, mean, std = fit_logistic(x, y)
    base_p = predict_logistic(x, w, b, mean, std)

    # Empirical per-state win rates, shrunk toward the baseline's average
    # prediction for that state.
    train_df = train_df.assign(base_p=base_p)
    g = train_df.groupby("state_key").agg(
        wins=("home_win", "sum"), n=("home_win", "size"), p0=("base_p", "mean")
    )
    g["p"] = (g["wins"] + SHRINK_K * g["p0"]) / (g["n"] + SHRINK_K)

    wp_by_state = g["p"].to_dict()
    n_by_state = g["n"].to_dict()

    # --- Leverage: mean |ΔWP| across real transitions out of each state ----
    print("Computing leverage index per state...", flush=True)
    lookup = train_df[["game_pk", "at_bat_number", "state_key", "home_win"]].sort_values(
        ["game_pk", "at_bat_number"]
    )
    p_cur = lookup["state_key"].map(wp_by_state).to_numpy()
    next_key = lookup.groupby("game_pk")["state_key"].shift(-1)
    p_next = next_key.map(wp_by_state).to_numpy()
    # Final PA of each game resolves to the actual outcome (1 or 0).
    p_next = np.where(pd.isna(p_next), lookup["home_win"].astype(float).to_numpy(), p_next)
    delta = np.abs(p_next - p_cur)
    li = pd.Series(delta, index=lookup.index).groupby(lookup["state_key"]).mean()
    li_by_state = li.to_dict()

    # --- Validation on the holdout season ----------------------------------
    print(f"Validating on {HOLDOUT_SEASON} holdout...", flush=True)
    hold = load_season_events(HOLDOUT_SEASON)
    yh = hold["home_win"].astype(float).to_numpy()
    ph = hold["state_key"].map(wp_by_state)
    # Unseen states fall back to the baseline.
    missing = ph.isna()
    if missing.any():
        xb = baseline_features(hold[missing])
        ph[missing] = predict_logistic(xb, w, b, mean, std)
    ph = ph.to_numpy().astype(float).clip(1e-4, 1 - 1e-4)

    def log_loss(p, y_):
        return float(-(y_ * np.log(p) + (1 - y_) * np.log(1 - p)).mean())

    ll_model = log_loss(ph, yh)
    naive = np.full_like(yh, yh.mean())
    ll_naive = log_loss(naive.clip(1e-4, 1 - 1e-4), yh)
    acc = float(((ph > 0.5) == yh).mean())

    calibration = []
    bins = np.linspace(0, 1, 11)
    which = np.digitize(ph, bins) - 1
    for i in range(10):
        m = which == i
        if m.sum() > 0:
            calibration.append({
                "bin": f"{bins[i]:.1f}-{bins[i+1]:.1f}",
                "predicted": round(float(ph[m].mean()), 4),
                "actual": round(float(yh[m].mean()), 4),
                "n": int(m.sum()),
            })
    print(f"  holdout log-loss {ll_model:.4f} (naive {ll_naive:.4f}), accuracy {acc:.3f}")
    for c in calibration:
        print(f"  {c['bin']}: predicted {c['predicted']:.3f} actual {c['actual']:.3f} (n={c['n']})")

    # Coarse fallback for live states never seen in training (rare but
    # possible): weighted mean p per (inning, half, diff) ignoring base/outs,
    # so app-side lookups never need to re-implement the logistic baseline.
    coarse = train_df.assign(p=train_df["state_key"].map(wp_by_state))
    coarse["coarse_key"] = (
        coarse["inning_c"].astype(str) + "|" + coarse["half"].astype(str) + "|"
        + coarse["diff"].astype(str)
    )
    fallback = coarse.groupby("coarse_key")["p"].mean().round(5).to_dict()

    # Global mean leverage — the denominator for "this moment is N× as
    # tense as average" style displays.
    mean_li = float(np.mean(list(li_by_state.values())))

    artifact = {
        "states": {
            k: [round(float(wp_by_state[k]), 5),
                round(float(li_by_state.get(k, 0.0)), 5),
                int(n_by_state[k])]
            for k in wp_by_state
        },
        "fallback": fallback,
        "mean_li": round(mean_li, 5),
        "baseline": {
            "coef": w.tolist(), "intercept": float(b),
            "mean": mean.tolist(), "std": std.tolist(),
            "base_run_potential": {str(k): v for k, v in BASE_RUN_POTENTIAL.items()},
        },
        "config": {
            "max_inning": MAX_INNING, "max_diff": MAX_DIFF, "shrink_k": SHRINK_K,
            "train_seasons": TRAIN_SEASONS, "holdout_season": HOLDOUT_SEASON,
        },
        "metrics": {
            "holdout_log_loss": round(ll_model, 4),
            "naive_log_loss": round(ll_naive, 4),
            "holdout_accuracy": round(acc, 4),
            "holdout_pa": int(len(yh)),
            "train_pa": int(len(train_df)),
            "calibration": calibration,
        },
    }
    ARTIFACT_PATH.write_text(json.dumps(artifact))
    print(f"Wrote {ARTIFACT_PATH} ({ARTIFACT_PATH.stat().st_size // 1024} KB, "
          f"{len(wp_by_state)} states)", flush=True)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("download", "all"):
        for season in TRAIN_SEASONS + [HOLDOUT_SEASON]:
            download_season(season)
    if mode in ("train", "all"):
        train()
