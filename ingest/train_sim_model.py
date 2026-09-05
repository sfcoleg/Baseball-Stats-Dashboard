"""Simulator outcome model — what actually happens to a batted ball,
learned from real ones.

The simulator needs to answer a specific question: two hitters put the
same share of balls in the air to the pull side, but one has far more
power — the one with power has to do better. That is not something to
hand-wave with a multiplier; it is measurable. This trains on every
batted ball of a season and reports, for each combination of

    bucket   pull/straight/oppo x air/ground   (what the sim's sliders set)
    hand     L or R                            (pull is a different field)
    power    which fifth of the league         (the thing being asked about)

the real distribution of outcomes: out, single, double, triple, home run.
Ground-ball buckets additionally split by SPEED rather than power, since
what decides an infield single is how fast the hitter runs, not how hard
he hit it.

Artifact is a JSON lookup, the same shape wp_model.json uses — no sklearn
dependency, and every number in it can be read and sanity-checked by eye
rather than taken on faith from a fitted object.

Small cells are shrunk toward their bucket's overall rate (see _shrink) so
a thinly-populated corner cannot produce a wild probability off a handful
of balls.

    python train_sim_model.py 2026
"""
import json
import sys
import time
import warnings
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from refresh_data import CURRENT_SEASON, DB_PATH
from ballparks import SEASON_RANGES
from line_drive_direction import _spray_angle_deg, _classify
from _dates import pacific_today

ARTIFACT_PATH = Path(__file__).resolve().parent.parent / "app" / "sim_model.json"

# How many balls a cell needs before its own rates are trusted outright.
# Below this it is pulled toward the bucket-wide rate in proportion to how
# thin it is, so a 12-ball cell does not get to claim a 40% home-run rate.
SHRINK_PRIOR = 150
N_TIERS = 5

TOTAL_BASES = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
OUTCOMES = ["out", "single", "double", "triple", "home_run"]


def _outcome(events: str) -> str:
    """Batted-ball events collapsed to the five things the sim cares about.
    Reached-on-error counts as an out: it is not a hit, and the sim is
    projecting a hitter's own line, not the defence's mistakes."""
    if events in TOTAL_BASES:
        return events
    return "out"


def fetch_season(season: int) -> pd.DataFrame:
    """Every batted ball of `season` with what it was and what it became."""
    from pybaseball import statcast

    start_s, end_s = SEASON_RANGES.get(season, (f"{season}-03-20", None))
    end_s = end_s or (pacific_today() - timedelta(days=1)).isoformat()
    start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)

    cols = ["batter", "stand", "hc_x", "hc_y", "bb_type", "events", "home_team"]
    frames = []
    chunk = start
    while chunk <= end:
        chunk_end = min(chunk + timedelta(days=13), end)
        print(f"  statcast {chunk} .. {chunk_end}", flush=True)
        raw = statcast(start_dt=chunk.isoformat(), end_dt=chunk_end.isoformat(), verbose=False)
        if raw is not None and not raw.empty and all(c in raw.columns for c in cols):
            keep = raw.loc[raw["bb_type"].notna(), cols]
            keep = keep.dropna(subset=["hc_x", "hc_y", "stand", "events"])
            if not keep.empty:
                frames.append(keep)
        chunk = chunk_end + timedelta(days=1)
        time.sleep(1)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=cols)


def label(df: pd.DataFrame) -> pd.DataFrame:
    """Attach bucket (direction x air/ground) and outcome to each ball."""
    df = df.copy()
    df["angle"] = _spray_angle_deg(df["hc_x"].tolist(), df["hc_y"].tolist()).values
    df["dir"] = _classify(df["angle"], df["stand"])
    df = df[df["dir"].notna()]
    df["traj"] = df["bb_type"].map(
        {"ground_ball": "gb", "fly_ball": "air", "line_drive": "air", "popup": "air"}
    )
    df = df[df["traj"].notna()]
    df["bucket"] = df["dir"].astype(str) + "_" + df["traj"]
    df["outcome"] = df["events"].map(_outcome)
    return df


def _rates(frame: pd.DataFrame) -> dict:
    counts = frame["outcome"].value_counts()
    n = int(counts.sum())
    return {"n": n, **{o: float(counts.get(o, 0)) / n for o in OUTCOMES}} if n else None


def _shrink(cell: dict, parent: dict) -> dict:
    """Pull a thin cell toward its bucket's overall rates. Weight is
    n/(n+SHRINK_PRIOR), so a cell with SHRINK_PRIOR balls sits halfway and
    a well-populated one is left essentially alone."""
    if not cell:
        return dict(parent)
    w = cell["n"] / (cell["n"] + SHRINK_PRIOR)
    return {"n": cell["n"],
            **{o: w * cell[o] + (1 - w) * parent[o] for o in OUTCOMES}}


def build(season: int, df: pd.DataFrame) -> dict:
    """bucket -> hand -> tier -> outcome rates. Air buckets tier on POWER,
    ground buckets on SPEED — because that is what actually decides each."""
    import sqlite3
    with sqlite3.connect(DB_PATH) as conn:
        bat = pd.read_sql(
            "SELECT mlbID, hard_hit_pct, avg_exit_velo, max_exit_velo, hp_to_1b "
            "FROM batting WHERE season = ?", conn, params=(season,))
    # A simple, always-available stand-in for the Power score: the season's
    # own percentile on the two exit-velocity measures that exist for every
    # Statcast year. Using the real Power score here would tie the training
    # data to bat-tracking coverage, which only reaches ~200 hitters.
    bat["power_rank"] = (bat[["hard_hit_pct", "avg_exit_velo"]]
                         .rank(pct=True).mean(axis=1))
    bat["speed_rank"] = 1 - bat["hp_to_1b"].rank(pct=True)  # lower time = faster
    df = df.merge(bat[["mlbID", "power_rank", "speed_rank"]],
                  left_on="batter", right_on="mlbID", how="left")

    model = {}
    for bucket, bframe in df.groupby("bucket", observed=True):
        parent = _rates(bframe)
        if not parent:
            continue
        model[bucket] = {"all": parent, "hands": {}}
        is_gb = bucket.endswith("_gb")
        tier_on = "speed_rank" if is_gb else "power_rank"
        for hand, hframe in bframe.groupby("stand", observed=True):
            hand_parent = _shrink(_rates(hframe), parent)
            tiers = []
            ranked = hframe.dropna(subset=[tier_on])
            for i in range(N_TIERS):
                lo, hi = i / N_TIERS, (i + 1) / N_TIERS
                sel = ranked[(ranked[tier_on] >= lo) & (ranked[tier_on] < hi + (1e-9 if i == N_TIERS - 1 else 0))]
                tiers.append({"lo": lo, "hi": hi, **_shrink(_rates(sel), hand_parent)})
            node = {"all": hand_parent, "tier_on": tier_on, "tiers": tiers}
            if is_gb:
                # Second axis for grounders: how hard it was hit still
                # matters, just less than who is running. Stored as its own
                # tier list the engine multiplies in, rather than a full
                # power x speed cross that would thin every cell out.
                p_tiers = []
                pranked = hframe.dropna(subset=["power_rank"])
                for i in range(N_TIERS):
                    lo, hi = i / N_TIERS, (i + 1) / N_TIERS
                    sel = pranked[(pranked["power_rank"] >= lo)
                                  & (pranked["power_rank"] < hi + (1e-9 if i == N_TIERS - 1 else 0))]
                    p_tiers.append({"lo": lo, "hi": hi, **_shrink(_rates(sel), hand_parent)})
                node["power_tiers"] = p_tiers
            model[bucket]["hands"][hand] = node
    return model


def fit_pa_model(season: int) -> dict:
    """Step 1 of a plate appearance: walk, strikeout, or ball in play.

    BB% and K% each regress on BOTH Eye and Contact, not one apiece,
    because the two interact — Schwarber walks a lot AND strikes out a
    lot, which a single-variable mapping cannot represent. Ordinary least
    squares on the season's qualified hitters; small, transparent, and
    the R2 is reported so an unconvincing fit is visible rather than
    buried.
    """
    import sqlite3
    import numpy as np

    with sqlite3.connect(DB_PATH) as conn:
        bat = pd.read_sql(
            "SELECT mlbID, PA, BB_PCT, K_PCT, hard_hit_pct, avg_exit_velo, max_exit_velo,"
            " sweet_spot_percent, hp_to_1b FROM batting WHERE season = ?",
            conn, params=(season,))
        disc = pd.read_sql("SELECT * FROM plate_discipline WHERE season = ?",
                           conn, params=(season,))
        try:
            bt = pd.read_sql("SELECT * FROM bat_tracking WHERE season = ?",
                             conn, params=(season,))
        except Exception:
            bt = pd.DataFrame(columns=["mlbID"])

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
    import db as appdb

    disc = disc.merge(bat[["mlbID", "hp_to_1b"]], on="mlbID", how="left")
    if not bt.empty:
        disc = disc.merge(bt[["mlbID", "swing_length"]], on="mlbID", how="left")
        bat = bat.merge(bt.drop(columns="season", errors="ignore"), on="mlbID", how="left")
    disc["Eye"] = appdb.discipline_eye_score(disc)
    disc["Contact"] = appdb.contact_score(disc)
    bat["Power"] = appdb.power_score(bat)

    df = bat.merge(disc[["mlbID", "Eye", "Contact"]], on="mlbID", how="inner")
    df = df[(df["PA"] >= appdb.QUALIFIED_MIN_PA)].dropna(subset=["Eye", "Contact", "BB_PCT", "K_PCT"])

    def ols(target):
        X = np.column_stack([np.ones(len(df)), df["Eye"].to_numpy(float),
                             df["Contact"].to_numpy(float)])
        y = df[target].to_numpy(float)
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        pred = X @ coef
        ss_res = float(((y - pred) ** 2).sum())
        ss_tot = float(((y - y.mean()) ** 2).sum())
        return {"intercept": float(coef[0]), "eye": float(coef[1]),
                "contact": float(coef[2]),
                "r2": 1 - ss_res / ss_tot if ss_tot else 0.0,
                "resid_sd": float(np.sqrt(ss_res / max(len(df) - 3, 1)))}

    return {"n": int(len(df)), "bb_pct": ols("BB_PCT"), "k_pct": ols("K_PCT")}


if __name__ == "__main__":
    season = int(sys.argv[1]) if len(sys.argv) > 1 else CURRENT_SEASON
    # Cache the labelled pull so the model structure can be revised without
    # paying for the fetch again — it is ~10 minutes of Statcast, and the
    # first validation pass already showed this model will need iterating.
    cache = Path(f"/tmp/sim_labelled_{season}.parquet")
    if cache.exists() and "--refetch" not in sys.argv:
        labelled = pd.read_parquet(cache)
        print(f"=== reusing cached {season} batted balls ({len(labelled)}) ===", flush=True)
    else:
        print(f"=== fetching {season} batted balls ===", flush=True)
        raw = fetch_season(season)
        print(f"batted balls: {len(raw)}", flush=True)
        labelled = label(raw)
        try:
            labelled.to_parquet(cache)
        except Exception as e:
            print(f"  (could not cache: {e})", flush=True)
    print(f"classified: {len(labelled)}", flush=True)
    model = build(season, labelled)

    print("\n=== fitting walk / strikeout model ===", flush=True)
    pa_model = fit_pa_model(season)
    print(f"  n={pa_model['n']} qualified hitters", flush=True)
    for key in ("bb_pct", "k_pct"):
        m = pa_model[key]
        print(f"  {key}: {m['intercept']:+.2f} {m['eye']:+.3f}*Eye {m['contact']:+.3f}*Contact"
              f"   R2={m['r2']:.3f}  resid sd={m['resid_sd']:.2f}", flush=True)

    artifact = {"season": season, "buckets": model, "pa": pa_model,
                "config": {"shrink_prior": SHRINK_PRIOR, "n_tiers": N_TIERS,
                           "outcomes": OUTCOMES}}
    ARTIFACT_PATH.write_text(json.dumps(artifact, separators=(",", ":")))
    print(f"wrote {ARTIFACT_PATH} ({ARTIFACT_PATH.stat().st_size // 1024} KB)", flush=True)

    # The whole point, printed so it can be eyeballed: within one bucket,
    # do the outcomes actually improve as power rises?
    pa = model.get("pull_air", {}).get("hands", {}).get("R")
    if pa:
        print("\npull_air, RHB — home-run rate by power tier (should climb):", flush=True)
        for t in pa["tiers"]:
            print(f"  power {t['lo']:.0%}-{t['hi']:.0%}  n={t['n']:6d}  "
                  f"HR {t['home_run']:.3f}  2B {t['double']:.3f}  out {t['out']:.3f}", flush=True)
    print("TRAIN_DONE", flush=True)
