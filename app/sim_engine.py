"""Simulator engine — turn a built hitter into a projected stat line.

A plate appearance is played out rather than curve-fitted:

    1. walk, strikeout, or ball in play   (from the Eye/Contact fit)
    2. if in play, which of the six buckets   (the profile sliders)
    3. what that batted ball became    (bucket x hand x power/speed tier)

Step 3 is the part that makes the thing behave like baseball. Two hitters
with an identical pull-air rate do NOT get identical results: the lookup
is conditioned on power, and in the real data a top-quintile power hitter
homers on 19.6% of his pull-air balls against 14.4% for the bottom
quintile, with the out rate falling from .513 to .418. Ground-ball
buckets condition on SPEED instead, because what turns a grounder into an
infield single is how fast the hitter runs.

Everything comes from app/sim_model.json (built by
ingest/train_sim_model.py), so nothing here is a hand-tuned constant.

Seasons are simulated rather than solved analytically because the spread
matters as much as the middle: a true .270 hitter hits anywhere from about
.240 to .300 over 600 plate appearances on luck alone, and reporting one
number hides that.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

MODEL_PATH = Path(__file__).resolve().parent / "sim_model.json"
OUTCOMES = ["out", "single", "double", "triple", "home_run"]
_TOTAL_BASES = {"out": 0, "single": 1, "double": 2, "triple": 3, "home_run": 4}
BUCKETS = ["pull_air", "straight_air", "oppo_air",
           "pull_gb", "straight_gb", "oppo_gb"]

# How far the BABIP dial can move non-HR hit rates across its full range.
# Tuned empirically rather than guessed: at 0.5 the projections came out
# with 1.33x the spread of real hitters, i.e. the model was inventing more
# variation than exists. Calibrated so predicted spread matches actual.
BABIP_SWING = 0.30


def load_model() -> dict | None:
    try:
        return json.loads(MODEL_PATH.read_text())
    except Exception:
        return None


def score_to_percentile(score: float) -> float:
    """A 1-100 score back to where it sits in the league. Scores are built
    as 50 + 15z, so inverting is just the normal CDF of that z — no scipy
    needed for one erf."""
    z = (float(score) - 50.0) / 15.0
    return max(0.0, min(1.0, 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))))


def _tier_rates(model: dict, bucket: str, hand: str, pct: float,
                power_pct: float | None = None) -> np.ndarray:
    """Outcome probabilities for one bucket, given handedness and where the
    hitter sits on whichever attribute that bucket keys on."""
    node = model["buckets"].get(bucket)
    if not node:
        return np.array([1.0, 0.0, 0.0, 0.0, 0.0])
    hand_node = node["hands"].get(hand) or next(iter(node["hands"].values()), None)
    if not hand_node:
        cell = node["all"]
    else:
        cell = hand_node["all"]
        for tier in hand_node["tiers"]:
            if tier["lo"] <= pct < tier["hi"] or (pct >= 1.0 and tier["hi"] >= 1.0):
                cell = tier
                break
    probs = np.array([float(cell.get(o, 0.0)) for o in OUTCOMES], dtype=float)
    total = probs.sum()
    probs = probs / total if total > 0 else np.array([1.0, 0.0, 0.0, 0.0, 0.0])

    # Grounders carry a second axis. Speed decides most of what a ground
    # ball becomes, but how hard it was hit still matters — a scorched
    # grounder beats the infield far more often than a weak one, and
    # grounders are roughly 45% of all batted balls, so ignoring it was
    # leaving real signal on the table. Applied as a ratio against the
    # hand-level baseline so it adjusts the speed-based rates rather than
    # replacing them.
    if hand_node and power_pct is not None and hand_node.get("power_tiers"):
        base = hand_node["all"]
        for tier in hand_node["power_tiers"]:
            if tier["lo"] <= power_pct < tier["hi"] or (power_pct >= 1.0 and tier["hi"] >= 1.0):
                adj = np.array([
                    (float(tier.get(o, 0.0)) / float(base[o])) if float(base.get(o, 0.0)) > 1e-9 else 1.0
                    for o in OUTCOMES
                ], dtype=float)
                probs = probs * adj
                s = probs.sum()
                probs = probs / s if s > 0 else probs
                break
    return probs


def project(profile: dict, eye: float, contact: float, power: float,
            hand: str = "R", speed_pct: float = 0.5, park_hr_factor: float = 1.0,
            babip_pct: float = 0.5,
            n_pa: int = 600, n_sims: int = 1000, seed: int | None = 0) -> dict | None:
    """Project a hitter. `profile` is the six bucket rates as percentages;
    they are normalised here, so a profile that does not total 100 is
    still projected on its relative shape rather than rejected.

    Returns the median line plus a 10th-90th percentile band per stat.
    """
    model = load_model()
    if not model:
        return None

    weights = np.array([max(0.0, float(profile.get(b, 0.0))) for b in BUCKETS])
    if weights.sum() <= 0:
        return None
    weights = weights / weights.sum()

    pa_fit = model.get("pa") or {}
    bb_c, k_c = pa_fit.get("bb_pct"), pa_fit.get("k_pct")
    if not bb_c or not k_c:
        return None
    bb_rate = (bb_c["intercept"] + bb_c["eye"] * eye + bb_c["contact"] * contact) / 100.0
    k_rate = (k_c["intercept"] + k_c["eye"] * eye + k_c["contact"] * contact) / 100.0
    # A projection is not licence to produce an impossible plate appearance.
    bb_rate = float(min(max(bb_rate, 0.001), 0.35))
    k_rate = float(min(max(k_rate, 0.010), 0.60))
    if bb_rate + k_rate > 0.95:
        scale = 0.95 / (bb_rate + k_rate)
        bb_rate, k_rate = bb_rate * scale, k_rate * scale
    inplay_rate = 1.0 - bb_rate - k_rate

    power_pct = score_to_percentile(power)
    bucket_probs = np.vstack([
        _tier_rates(model, b, hand, speed_pct if b.endswith("_gb") else power_pct,
                    power_pct=power_pct if b.endswith("_gb") else None)
        for b in BUCKETS
    ])
    # BABIP skill — how well this hitter finds grass on balls in play,
    # beyond what his bucket mix and power already explain. Bucket-plus-
    # power assigns every hitter in a cell the league-average result for
    # that cell, which is why predictions came out under-dispersed: real
    # hitters differ inside a cell.
    #
    # It moves NON-HOME-RUN hits only. A home run is not a ball in play and
    # is decided by power and the park, not by finding a hole; letting a
    # BABIP dial inflate home runs would double-count power.
    if abs(babip_pct - 0.5) > 1e-9:
        # +-25% swing across the full percentile range, tuned to roughly
        # the real spread of qualified-hitter BABIP (about .250 to .350
        # around a ~.300 league mean).
        mult = 1.0 + BABIP_SWING * (float(babip_pct) - 0.5)
        for i in range(len(BUCKETS)):
            row = bucket_probs[i]
            hit_ix = [1, 2, 3]  # single, double, triple — HR excluded
            before = row[hit_ix].sum()
            row[hit_ix] = np.clip(row[hit_ix] * mult, 0.0, 1.0)
            # Outs absorb the difference so the row still sums to 1.
            row[0] = max(0.0, row[0] + (before - row[hit_ix].sum()))
            total = row.sum()
            bucket_probs[i] = row / total if total > 0 else row

    if park_hr_factor != 1.0:
        # Move HR probability by the park's own factor and settle the
        # difference into outs, so each row still sums to 1.
        for i in range(len(BUCKETS)):
            hr = bucket_probs[i, 4]
            new_hr = min(max(hr * park_hr_factor, 0.0), 0.95)
            bucket_probs[i, 4] = new_hr
            bucket_probs[i, 0] = max(0.0, bucket_probs[i, 0] + (hr - new_hr))
            bucket_probs[i] /= bucket_probs[i].sum()

    rng = np.random.default_rng(seed)
    # Per plate appearance: walk / strikeout / in play, then which bucket,
    # then what the ball became. Collapsed into one 8-way categorical draw
    # so a full season is a single vectorised call rather than a loop.
    cats = np.concatenate([[bb_rate, k_rate],
                           inplay_rate * (weights[:, None] * bucket_probs).sum(axis=0)])
    cats = cats / cats.sum()
    draws = rng.multinomial(n_pa, cats, size=n_sims)  # (sims, 7)

    bb, k = draws[:, 0], draws[:, 1]
    outs, singles, doubles, triples, hrs = (draws[:, 2 + i] for i in range(5))
    hits = singles + doubles + triples + hrs
    ab = n_pa - bb
    tb = singles + 2 * doubles + 3 * triples + 4 * hrs

    with np.errstate(divide="ignore", invalid="ignore"):
        avg = np.where(ab > 0, hits / ab, 0.0)
        obp = (hits + bb) / n_pa
        slg = np.where(ab > 0, tb / ab, 0.0)
    ops = obp + slg
    babip_den = ab - hrs - k
    babip = np.where(babip_den > 0, (hits - hrs) / babip_den, 0.0)

    def band(arr, dec=3):
        return {"p50": round(float(np.percentile(arr, 50)), dec),
                "p10": round(float(np.percentile(arr, 10)), dec),
                "p90": round(float(np.percentile(arr, 90)), dec)}

    return {
        "AVG": band(avg), "OBP": band(obp), "SLG": band(slg), "OPS": band(ops),
        "BABIP": band(babip),
        "HR": band(hrs, 0), "2B": band(doubles, 0), "3B": band(triples, 0),
        "BB": band(bb, 0), "SO": band(k, 0), "H": band(hits, 0),
        "BB%": band(100.0 * bb / n_pa, 1), "K%": band(100.0 * k / n_pa, 1),
        "pa": n_pa, "sims": n_sims,
    }


def nearest_comps(profile: dict, eye: float, contact: float, power: float,
                  pool, n: int = 5):
    """Closest real player-seasons to a built hitter, by Euclidean distance
    across the z-scored profile and scores — the same approach db.py's
    similar_players uses, extended to accept a made-up player as the query
    rather than an existing row.

    Also returns the raw distance to the nearest real hitter, which is what
    tells the page whether a built profile resembles anything that has
    actually happened or is off the edge of the map.
    """
    import pandas as pd

    cols = [f"{b}_rate" for b in BUCKETS]
    have = [c for c in cols if c in pool.columns]
    if not have or pool.empty:
        return pd.DataFrame(), float("nan")

    frame = pool.dropna(subset=have + ["Eye", "Contact", "Power"]).copy()
    if frame.empty:
        return pd.DataFrame(), float("nan")

    target, mat = [], []
    for c in have:
        s = frame[c] * 100.0
        sd = s.std() or 1.0
        mat.append(((s - s.mean()) / sd).to_numpy())
        target.append((float(profile.get(c.replace("_rate", ""), 0.0)) - s.mean()) / sd)
    for c, v in (("Eye", eye), ("Contact", contact), ("Power", power)):
        s = frame[c].astype(float)
        sd = s.std() or 1.0
        mat.append(((s - s.mean()) / sd).to_numpy())
        target.append((float(v) - s.mean()) / sd)

    diff = np.vstack(mat).T - np.array(target)
    dist = np.sqrt((diff ** 2).sum(axis=1))
    frame = frame.assign(distance=dist).sort_values("distance")
    return frame.head(n), float(dist.min())
