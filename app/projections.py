"""ML-based next-season rate-stat projections — the Marcel-the-Monkey idea
(regress recent performance toward a baseline, adjust for age and sample
size) but with a gradient-boosted model learning the aging/regression curve
from the data instead of hand-tuned weights. Trained on every season-N ->
season-(N+1) pair in the DB for players who cleared the PA/IP bar in both
years, so it captures real historical aging patterns, not just this year's
noise.
"""
import sqlite3

import pandas as pd
import streamlit as st
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score

import db

# Traditional Baseball-Reference rate/counting stats only — these are
# populated for every season back to 2008, unlike the Statcast-era columns
# (exit velo, barrels, etc.) which only exist from ~2015 on and would starve
# the training set of most of its historical pairs.
BATTING_FEATURES = ["Age", "PA", "BA", "OBP", "SLG", "OPS", "ISO", "BABIP", "BB_PCT", "K_PCT", "HR", "SB"]
PITCHING_FEATURES = ["Age", "IP", "ERA", "WHIP", "K_9", "BB_9", "K_BB", "FIP", "HR"]

BATTING_TARGETS = ["OPS", "BA", "OBP", "SLG", "ISO", "HR", "SB"]
PITCHING_TARGETS = ["ERA", "WHIP", "FIP", "K_9", "BB_9"]
LOWER_BETTER = {"ERA", "WHIP", "BB_9", "FIP"}

MIN_SAMPLE = {"batting": 200, "pitching": 40}  # PA / IP required in BOTH the input and output season


@st.cache_data(show_spinner=False, max_entries=8)
def _load_history(table: str, db_mtime_val: float) -> pd.DataFrame:
    features = BATTING_FEATURES if table == "batting" else PITCHING_FEATURES
    cols = list(dict.fromkeys(["mlbID", "season"] + features))
    select_cols = ", ".join(f'"{c}"' for c in cols)
    with sqlite3.connect(db.DB_PATH) as conn:
        return pd.read_sql(f"SELECT {select_cols} FROM {table}", conn)


def _build_pairs(history: pd.DataFrame, features: list[str], target: str, min_sample: float, min_col: str) -> pd.DataFrame:
    by_season = {s: g.set_index("mlbID") for s, g in history.groupby("season")}
    rows = []
    for s in sorted(by_season):
        if s + 1 not in by_season:
            continue
        cur = by_season[s]
        cur = cur[cur[min_col] >= min_sample]
        nxt = by_season[s + 1]
        nxt = nxt[nxt[min_col] >= min_sample]
        shared = cur.index.intersection(nxt.index)
        if len(shared) == 0:
            continue
        block = cur.loc[shared, features].copy()
        block["_target"] = nxt.loc[shared, target].to_numpy()
        block["_season"] = s
        rows.append(block)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


@st.cache_resource(show_spinner=False)
def train_projection_model(table: str, target: str, db_mtime_val: float):
    """Fits a gradient-boosted season-N -> season-(N+1) model for `target`.

    Reports out-of-sample R²/MAE on the single most recent season-pair
    (held out of training) so the UI can show honest accuracy instead of an
    inflated in-sample number, then refits on the full dataset (including
    that held-out pair) to produce the model actually used for projections.
    """
    features = BATTING_FEATURES if table == "batting" else PITCHING_FEATURES
    min_col = "PA" if table == "batting" else "IP"
    min_sample = MIN_SAMPLE[table]

    history = _load_history(table, db_mtime_val)
    pairs = _build_pairs(history, features, target, min_sample, min_col).dropna()
    if len(pairs) < 50:
        return None

    test_season = pairs["_season"].max()
    train = pairs[pairs["_season"] != test_season]
    test = pairs[pairs["_season"] == test_season]

    model = GradientBoostingRegressor(n_estimators=150, max_depth=3, learning_rate=0.05, random_state=0)
    model.fit(train[features], train["_target"])

    metrics = None
    if len(test) >= 15:
        preds = model.predict(test[features])
        metrics = {
            "r2": r2_score(test["_target"], preds),
            "mae": mean_absolute_error(test["_target"], preds),
            "n": int(len(test)),
            "test_season": int(test_season),
        }

    model.fit(pairs[features], pairs["_target"])
    return {"model": model, "features": features, "metrics": metrics}


def project_next_season(table: str, target: str, season: int, db_mtime_val: float):
    """Returns (projections_df, metrics) for every player who qualified in
    `season`, projecting their `target` stat for `season + 1`. None, None if
    there isn't enough training data yet.
    """
    trained = train_projection_model(table, target, db_mtime_val)
    if trained is None:
        return None, None
    features, model, metrics = trained["features"], trained["model"], trained["metrics"]
    min_col = "PA" if table == "batting" else "IP"
    min_sample = MIN_SAMPLE[table]

    current = db.load_batting(season, db_mtime_val) if table == "batting" else db.load_pitching(season, db_mtime_val)
    current = current[current[min_col] >= min_sample].dropna(subset=features).copy()
    if current.empty:
        return None, metrics

    current["Projected"] = model.predict(current[features])
    current["Δ"] = current["Projected"] - current[target]
    out = current[["Name", "Tm", "Age", target, "Projected", "Δ"]].rename(columns={target: "Current"})
    ascending = target in LOWER_BETTER
    return out.sort_values("Projected", ascending=ascending), metrics
