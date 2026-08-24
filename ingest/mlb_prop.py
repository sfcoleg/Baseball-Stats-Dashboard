"""P.R.O.P.+ — Pitch Raw Output Profile: Diamond Metrics' own pitch-quality
model, the MLB counterpart to the NHL's SLOT.

PROP+ grades a pitch on its PHYSICAL properties alone — how hard it's thrown,
how much it moves, how that movement compares both to league average for that
pitch type and to the pitcher's own fastball — and asks what run value a pitch
shaped like that is worth. Results are deliberately kept out of the inputs: no
whiff rate, no strikeout rate, no wOBA, no hard-hit rate. Those are what the
model predicts, never what it looks at. That's the whole point of a "stuff"
metric — it describes the pitch, not what happened to it, so it stabilizes far
faster than outcomes do and says something about a pitcher before the results
arrive.

Scaled so 100 is league average and 10 points is one standard deviation, higher
being better: a 120 slider is a genuinely nasty pitch, an 80 is batting practice.

Two honest limits, both from the data we have:
  * The unit is a pitcher's pitch TYPE over a season, not an individual pitch —
    pitch_arsenal is a season aggregate. Real Stuff+ models grade each pitch.
    Training is weighted by plate appearances to compensate, since a pitch type
    with 20 PA behind it carries five times the run-value noise of one with 400.
  * Spin rate is entirely missing before 2020 in this table, so the model is
    trained and applied from 2020 on rather than treating "no spin" as a
    feature, which would really just encode "this is an old season."

Usage:
    python ingest/mlb_prop.py            # train, validate, score every pitch
    python ingest/mlb_prop.py --no-score # train and report only
"""
import argparse
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import r2_score

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "stats.db"
MODEL_DIR = ROOT / "app"
METRICS_PATH = MODEL_DIR / "prop_model.json"
MODEL_PATH = MODEL_DIR / "prop_model.joblib"

FIRST_SEASON = 2020      # spin rate doesn't exist before this
MIN_PA = 25              # below this, run value is mostly noise
FASTBALLS = ("FF", "SI", "FC")

# Physical inputs only. Everything the pitch DID (whiff_pct, k_percent, woba,
# est_woba, ba, slg, put_away, hard_hit_percent) is excluded on purpose —
# including any of it would turn this into a results model wearing a stuff
# model's name. usage_pct is excluded too: how often a pitch is thrown is a
# choice the pitcher makes, not a property of the pitch.
NUMERIC_FEATURES = [
    "velocity", "vert_break", "horz_break",
    "d_vert", "d_horz",            # movement vs league average for this pitch type
    "spin_rate",
    "velo_vs_fb", "dvert_vs_fb", "dhorz_vs_fb",   # separation from his own fastball
]
CATEGORICAL_FEATURES = ["pitch_type_code", "hand_code"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

PITCH_TYPES = ["FF", "SI", "FC", "SL", "ST", "SV", "CU", "CH", "FS", "KN", "SC"]
HANDS = ["R", "L"]
TARGET = "run_value_per_100"     # positive = good for the pitcher (verified:
                                 # +0.29 corr with K%, -0.85 with wOBA against)


def load_arsenal() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql("SELECT * FROM pitch_arsenal WHERE season >= ?", conn, params=(FIRST_SEASON,))
    df = df[df["pa"] >= MIN_PA].copy()

    # Movement relative to what that pitch type normally does. Statcast already
    # mirrors horizontal break for left-handers (verified: LHP and RHP fastballs
    # both average ~+7.7), so arm-side is arm-side regardless of hand.
    df["d_vert"] = df["vert_break"] - df["league_break_z"]
    df["d_horz"] = df["horz_break"] - df["league_break_x"]

    # Separation from the pitcher's own primary fastball that season — the
    # thing that makes a 88 mph changeup play up behind 99 mph heat.
    fb = df[df["pitch_type"].isin(FASTBALLS)].sort_values("usage_pct", ascending=False)
    fb = fb.drop_duplicates(["mlbID", "season"])[
        ["mlbID", "season", "velocity", "vert_break", "horz_break"]]
    fb.columns = ["mlbID", "season", "fb_velo", "fb_vert", "fb_horz"]
    df = df.merge(fb, on=["mlbID", "season"], how="left")
    df["velo_vs_fb"] = df["velocity"] - df["fb_velo"]
    df["dvert_vs_fb"] = df["vert_break"] - df["fb_vert"]
    df["dhorz_vs_fb"] = df["horz_break"] - df["fb_horz"]

    df["pitch_type_code"] = pd.Categorical(df["pitch_type"], categories=PITCH_TYPES).codes
    df["hand_code"] = pd.Categorical(df["pitch_hand"], categories=HANDS).codes
    return df.dropna(subset=["velocity", "vert_break", "horz_break", TARGET])


def _fit(df: pd.DataFrame) -> HistGradientBoostingRegressor:
    model = HistGradientBoostingRegressor(
        loss="squared_error", learning_rate=0.05, max_iter=500, max_leaf_nodes=31,
        min_samples_leaf=40, l2_regularization=1.0, early_stopping=True,
        validation_fraction=0.12, n_iter_no_change=30, random_state=17,
        categorical_features=[f in CATEGORICAL_FEATURES for f in FEATURES],
    )
    model.fit(df[FEATURES], df[TARGET], sample_weight=df["pa"])
    return model


def _wmean_wsd(values, weights):
    m = np.average(values, weights=weights)
    sd = float(np.sqrt(np.average((values - m) ** 2, weights=weights)))
    return float(m), sd


def train(df: pd.DataFrame) -> dict:
    """Temporal holdout, then the test that actually matters for a stuff
    model: does it predict NEXT season better than this season's results do?"""
    seasons = sorted(df["season"].unique())
    test_seasons = seasons[-2:]
    tr = df[~df["season"].isin(test_seasons)]
    te = df[df["season"].isin(test_seasons)]
    print(f"\n  train {len(tr):,} pitch-seasons ({seasons[0]}-{test_seasons[0]-1})  |  "
          f"holdout {len(te):,} ({test_seasons[0]}-{test_seasons[-1]})", flush=True)

    model = _fit(tr)
    pred = model.predict(te[FEATURES])
    w = te["pa"].to_numpy(dtype=float)

    # Baselines: league average, and the average for that pitch type.
    league = np.full(len(te), np.average(tr[TARGET], weights=tr["pa"]))
    by_type = tr.groupby("pitch_type").apply(
        lambda g: np.average(g[TARGET], weights=g["pa"]), include_groups=False)
    type_base = te["pitch_type"].map(by_type).fillna(league[0]).to_numpy()

    print("\n  holdout accuracy (PA-weighted):", flush=True)
    results = []
    for name, p in (("league average", league), ("pitch-type average", type_base), ("PROP+", pred)):
        r2 = r2_score(te[TARGET], p, sample_weight=w)
        rmse = float(np.sqrt(np.average((te[TARGET] - p) ** 2, weights=w)))
        results.append({"model": name, "r2": float(r2), "rmse": rmse})
        print(f"    {name:<20} R2 {r2:+.4f}   RMSE {rmse:.4f}", flush=True)

    # --- the stickiness test -------------------------------------------------
    # A stuff model earns its keep by predicting the FUTURE better than past
    # results do. Pair each pitch with the same pitcher's same pitch the
    # following season and compare.
    scored = df.copy()
    # Scored with the holdout model (trained without the last two seasons) so
    # this isn't a self-fulfilling test.
    scored["pred"] = model.predict(scored[FEATURES])
    nxt = scored[["mlbID", "pitch_type", "season", TARGET, "pa"]].copy()
    nxt["season"] -= 1
    nxt = nxt.rename(columns={TARGET: "next_rv", "pa": "next_pa"})
    pairs = scored.merge(nxt, on=["mlbID", "pitch_type", "season"], how="inner")
    pairs = pairs[pairs["next_pa"] >= MIN_PA]
    wq = np.sqrt(pairs["pa"] * pairs["next_pa"])
    def _wcorr(a, b, w):
        am, bm = np.average(a, weights=w), np.average(b, weights=w)
        cov = np.average((a - am) * (b - bm), weights=w)
        return float(cov / np.sqrt(np.average((a - am) ** 2, weights=w) * np.average((b - bm) ** 2, weights=w)))
    r_stuff = _wcorr(pairs["pred"].to_numpy(), pairs["next_rv"].to_numpy(), wq.to_numpy())
    r_results = _wcorr(pairs[TARGET].to_numpy(), pairs["next_rv"].to_numpy(), wq.to_numpy())
    print(f"\n  predicting NEXT season's run value ({len(pairs):,} same-pitcher/same-pitch pairs):", flush=True)
    print(f"    this season's actual run value -> next season : r = {r_results:+.4f}", flush=True)
    print(f"    PROP+                          -> next season : r = {r_stuff:+.4f}", flush=True)
    print(f"    {'PROP+ is stickier' if r_stuff > r_results else 'results are stickier'}", flush=True)

    return {
        "name": "PROP+", "full_name": "Pitch Raw Output Profile",
        "trained_at": pd.Timestamp.now("UTC").isoformat(timespec="seconds"),
        "seasons": [int(s) for s in seasons], "min_pa": MIN_PA,
        "n": int(len(df)), "features": FEATURES,
        "holdout": {"seasons": [int(s) for s in test_seasons], "n": int(len(te)), "results": results},
        "stickiness": {"pairs": int(len(pairs)), "prop_to_next": r_stuff, "results_to_next": r_results},
    }


def score(df: pd.DataFrame, model) -> pd.DataFrame:
    """Predicted run value -> a 100-centred index, PA-weighted so a handful of
    tiny-sample oddities can't drag the scale around. Higher is better."""
    df = df.copy()
    df["pred_rv100"] = model.predict(df[FEATURES])
    m, sd = _wmean_wsd(df["pred_rv100"].to_numpy(), df["pa"].to_numpy(dtype=float))
    df["prop_plus"] = 100 + 10 * (df["pred_rv100"] - m) / (sd or 1.0)
    return df, {"mean": m, "sd": sd}


def store(df: pd.DataFrame) -> None:
    per_pitch = df[["mlbID", "Name", "season", "pitch_type", "pitch_name", "pa",
                    "usage_pct", "pred_rv100", "prop_plus"]].copy()
    # A pitcher's overall grade is his arsenal weighted by how often he uses it.
    overall = (df.assign(w=df["usage_pct"].fillna(0))
                 .groupby(["mlbID", "season"])
                 .apply(lambda g: pd.Series({
                     "prop_plus": np.average(g["prop_plus"], weights=g["w"]) if g["w"].sum() else np.nan,
                     "pitches": len(g), "pa": int(g["pa"].sum()),
                 }), include_groups=False)
                 .reset_index().dropna(subset=["prop_plus"]))
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DROP TABLE IF EXISTS pitch_prop")
        conn.execute("DROP TABLE IF EXISTS pitcher_prop")
        per_pitch.to_sql("pitch_prop", conn, index=False)
        overall.to_sql("pitcher_prop", conn, index=False)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pitch_prop ON pitch_prop(season, mlbID)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pitcher_prop ON pitcher_prop(season, mlbID)")
        conn.commit()
    print(f"\n  stored {len(per_pitch):,} pitch grades and {len(overall):,} pitcher grades", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-score", action="store_true")
    args = ap.parse_args()

    print("=== P.R.O.P.+ (Pitch Raw Output Profile) ===", flush=True)
    df = load_arsenal()
    print(f"  {len(df):,} pitcher-pitch-seasons, {df['season'].min()}-{df['season'].max()}, "
          f"min {MIN_PA} PA", flush=True)

    metrics = train(df)

    print("\n  refitting on every season for the shipped model...", flush=True)
    model = _fit(df)
    scored, scale = score(df, model)
    metrics["scale"] = scale
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        import joblib
        joblib.dump(model, MODEL_PATH)
    except Exception as e:  # noqa: BLE001
        print(f"  (model artifact not saved: {e!r})", flush=True)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    print(f"  wrote {METRICS_PATH}", flush=True)

    if not args.no_score:
        store(scored)
        top = scored[scored["pa"] >= 100].nlargest(10, "prop_plus")
        print("\n  best pitches in the data (min 100 PA):", flush=True)
        for _, r in top.iterrows():
            print(f"    {r['prop_plus']:6.1f}  {r['Name']:<24} {r['pitch_name']:<18} "
                  f"{r['season']}  {r['velocity']:.1f} mph", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
