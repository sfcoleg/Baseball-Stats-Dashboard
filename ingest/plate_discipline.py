"""Plate discipline / eye — swing rates by Statcast attack zone, computed
from raw pitch-level data because no published leaderboard has what this
needs.

Savant's Swing/Take leaderboard reports RUN VALUES per zone (runs_heart,
runs_shadow, runs_chase, runs_waste) — not swing rates — and treats Shadow
as a single bucket. Shadow straddles the strike-zone edge by design, so
roughly half of it is actually strikes and half actually balls, and those
are opposite decisions: swinging at a shadow pitch that IS a strike is
correct, swinging at one that ISN'T is a mistake. Splitting Shadow at the
true zone boundary is the whole point of this module, and it means going
to raw pitches.

ZONES. Both axes are normalised so the strike-zone boundary sits at 1.0 —
horizontally against a fixed half-width, vertically against that pitch's
own sz_top/sz_bot (the zone is per-batter, and Statcast gives it per
pitch). Distance is max() of the two, not hypot, because the strike zone
is a RECTANGLE: a pitch is a strike when both axes are inside, so the
binding constraint is whichever axis is further out.

    d <= 0.67   heart        the middle, where nearly everyone swings
    0.67-1.00   shadow_in    borderline STRIKE  -> swinging is correct
    1.00-1.33   shadow_out   borderline BALL    -> swinging is forgivable
    1.33-2.00   chase        clearly a ball     -> swinging is a mistake
    > 2.00      waste        nowhere near       -> nobody good swings

COUNT CONTEXT. A pitch's decision is only as meaningful as its situation:
protecting with two strikes is not the same decision as chasing on 3-0.
Every pitch is therefore weighted by how diagnostic that decision is in
that count (see _COUNT_WEIGHTS), and each rate is a weighted rate,
sum(w*swing)/sum(w), rather than a raw one. Without this a disciplined
two-strike hitter and a reckless first-pitch hacker score the same.

Writes one row per batter-season to the `plate_discipline` table:
weighted swing rates for heart/shadow_in, weighted TAKE rates for
shadow_out/chase/waste (everything stored as higher-is-better so the
score that consumes it needs no sign flipping), plus raw pitch counts per
zone so sample size is visible.

    python plate_discipline.py 2026        # one season
"""
import sqlite3
import sys
import time
import warnings
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from refresh_data import CURRENT_SEASON, DB_PATH, _store_season_table
from ballparks import SEASON_RANGES
from _dates import pacific_today

# Half-width of the strike zone in feet: the plate is 17in (0.708ft each
# side of centre) and a pitch is a strike if ANY part of the ball clips
# it, so add a ball's radius (~1.45in).
ZONE_HALF_WIDTH_FT = 0.708 + 0.121

# Zone boundaries in normalised units (1.0 == the strike-zone edge).
HEART_MAX = 0.67
SHADOW_MAX = 1.33
CHASE_MAX = 2.00

# description values that mean the batter offered at the pitch. Anything
# not listed here (ball, called_strike, blocked_ball, hit_by_pitch,
# pitchout...) is a take.
SWING_DESCRIPTIONS = {
    "swinging_strike", "swinging_strike_blocked", "foul", "foul_tip",
    "hit_into_play", "foul_bunt", "missed_bunt", "bunt_foul_tip",
}

# Swings that came up empty. Everything else in SWING_DESCRIPTIONS made
# contact — fouls included, since a foul is bat-on-ball and is exactly how
# hitters survive two-strike counts.
WHIFF_DESCRIPTIONS = {"swinging_strike", "swinging_strike_blocked", "missed_bunt"}

# How much a decision in this count reveals. Out-of-zone and in-zone pull
# in OPPOSITE directions, which is the point: laying off on 3-0 is easy
# and expected (so chasing there is damning), while protecting the plate
# with two strikes is mandatory (so a shadow-out swing there is close to
# excusable). Mirrored for in-zone: taking a first-pitch strike is a
# normal patient approach, taking one with two strikes is a strikeout.
_HITTERS_COUNTS = {(2, 0), (3, 0), (3, 1), (2, 1)}


def _out_of_zone_weight(balls, strikes):
    if strikes >= 2:
        return 0.4          # protecting is legitimate
    if (balls, strikes) in _HITTERS_COUNTS:
        return 1.5          # no excuse to chase when you can afford to wait
    return 1.0


def _in_zone_weight(balls, strikes):
    if strikes >= 2:
        return 1.5          # taking a strike here is a strikeout
    if (balls, strikes) == (3, 0):
        return 0.3          # taking is almost always correct
    if (balls, strikes) == (0, 0):
        return 0.5          # a first-pitch take is approach, not bad eye
    return 1.0


def classify_zone(df: pd.DataFrame) -> pd.Series:
    """heart / shadow_in / shadow_out / chase / waste per pitch."""
    half_height = (df["sz_top"] - df["sz_bot"]) / 2.0
    centre_z = (df["sz_top"] + df["sz_bot"]) / 2.0
    x_norm = df["plate_x"].abs() / ZONE_HALF_WIDTH_FT
    z_norm = (df["plate_z"] - centre_z).abs() / half_height.replace(0, pd.NA)
    # Rectangle, not ellipse — the binding axis is whichever is further out.
    d = pd.concat([x_norm, z_norm], axis=1).max(axis=1)
    return pd.cut(
        d,
        bins=[-0.01, HEART_MAX, 1.0, SHADOW_MAX, CHASE_MAX, float("inf")],
        labels=["heart", "shadow_in", "shadow_out", "chase", "waste"],
    )


def fetch_season_pitches(season=CURRENT_SEASON) -> pd.DataFrame:
    """Every pitch of `season` with the fields needed to place it in a
    zone and know what the batter did about it. Chunked like
    ballparks.download_season — this is every PITCH, not every batted
    ball, so it is several times the volume of the other ingests."""
    from pybaseball import statcast

    start_s, end_s = SEASON_RANGES.get(season, (f"{season}-03-20", None))
    end_s = end_s or (pacific_today() - timedelta(days=1)).isoformat()
    start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)

    cols = ["batter", "plate_x", "plate_z", "sz_top", "sz_bot", "description", "balls", "strikes"]
    frames = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=13), end)
        print(f"  statcast {chunk_start} .. {chunk_end}", flush=True)
        raw = statcast(start_dt=chunk_start.isoformat(), end_dt=chunk_end.isoformat(), verbose=False)
        if raw is not None and not raw.empty and all(c in raw.columns for c in cols):
            keep = raw[cols].dropna(subset=["plate_x", "plate_z", "sz_top", "sz_bot", "description"])
            if not keep.empty:
                frames.append(keep)
        chunk_start = chunk_end + timedelta(days=1)
        time.sleep(1)

    if not frames:
        return pd.DataFrame(columns=cols)
    return pd.concat(frames, ignore_index=True)


def compute_rates(pitches: pd.DataFrame, season: int) -> pd.DataFrame:
    """Per-batter weighted swing rates (heart, shadow_in) and weighted
    TAKE rates (shadow_out, chase, waste). Stored higher-is-better across
    the board so nothing downstream has to flip signs."""
    df = pitches.copy()
    df["zone"] = classify_zone(df)
    df = df[df["zone"].notna()]
    df["swing"] = df["description"].isin(SWING_DESCRIPTIONS).astype(float)

    in_zone = df["zone"].isin(["heart", "shadow_in"])
    df["w"] = [
        _in_zone_weight(b, s) if iz else _out_of_zone_weight(b, s)
        for b, s, iz in zip(df["balls"], df["strikes"], in_zone)
    ]
    # In-zone zones score on SWINGING; out-of-zone zones score on TAKING.
    df["good"] = df["swing"].where(in_zone, 1.0 - df["swing"])
    df["wg"] = df["w"] * df["good"]

    grouped = df.groupby(["batter", "zone"], observed=True).agg(
        wg=("wg", "sum"), w=("w", "sum"), pitches=("swing", "size")
    )
    rate = (grouped["wg"] / grouped["w"]).unstack("zone")
    counts = grouped["pitches"].unstack("zone")

    out = pd.DataFrame(index=rate.index)
    for zone, col in [("heart", "heart_swing"), ("shadow_in", "shadow_in_swing"),
                      ("shadow_out", "shadow_out_take"), ("chase", "chase_take"),
                      ("waste", "waste_take")]:
        out[col] = rate[zone] if zone in rate.columns else pd.NA
        out[f"{zone}_pitches"] = counts[zone] if zone in counts.columns else 0
    out["total_pitches"] = counts.sum(axis=1)

    # --- contact, for the Contact score -------------------------------
    # Contact rate is per SWING, not per pitch: the question is "when you
    # offered, did you hit it", which is a different skill from how often
    # you offer. Deliberately NOT count-weighted — unlike a swing
    # decision, whether you hit the ball is not more or less commendable
    # by count, it just is.
    swings = df[df["swing"] == 1].copy()
    swings["contact"] = (~swings["description"].isin(WHIFF_DESCRIPTIONS)).astype(float)

    by_zone = swings.groupby(["batter", "zone"], observed=True)["contact"].agg(["mean", "size"])
    contact_rate = by_zone["mean"].unstack("zone")
    swing_counts = by_zone["size"].unstack("zone")
    for zone in ["heart", "shadow_in", "shadow_out", "chase"]:
        out[f"{zone}_contact"] = contact_rate[zone] if zone in contact_rate.columns else pd.NA
        out[f"{zone}_swings"] = swing_counts[zone] if zone in swing_counts.columns else 0

    # Two-strike contact is the single most direct predictor of strikeout
    # rate that is not itself strikeout rate: with two strikes, making
    # contact IS the difference between surviving and being out. Fouls
    # count, which is the point — fouling off what you cannot drive is
    # how good two-strike hitters stay alive.
    two_k = swings[swings["strikes"] >= 2]
    out["two_strike_contact"] = two_k.groupby("batter")["contact"].mean()
    out["two_strike_swings"] = two_k.groupby("batter")["contact"].size()

    out["season"] = season
    return out.reset_index().rename(columns={"batter": "mlbID"})


def store(season: int, rates: pd.DataFrame) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        _store_season_table(conn, "plate_discipline", rates, season)
        conn.commit()
        stored = conn.execute(
            "SELECT COUNT(*) FROM plate_discipline WHERE season = ?", (season,)
        ).fetchone()[0]
    print(f"  stored {stored} batters for {season}", flush=True)


if __name__ == "__main__":
    season = int(sys.argv[1]) if len(sys.argv) > 1 else CURRENT_SEASON
    print(f"=== fetching {season} pitches ===", flush=True)
    pitches = fetch_season_pitches(season)
    print(f"total pitches: {len(pitches)}", flush=True)
    rates = compute_rates(pitches, season)
    print(f"batters: {len(rates)}", flush=True)
    store(season, rates)
    print("DONE", flush=True)
