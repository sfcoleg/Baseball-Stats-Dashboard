"""Player Simulator — build a hitter from scratch and see who he looks
like. This file is the INTERFACE only: the batted-ball profile and the
three skill scores, with no prediction or comp engine behind them yet.

Each score can be driven two ways. Leave it collapsed and it is one
slider, 1-100. Open it and you set the underlying stats instead — the
real ones the score is actually built from — and the score recomputes
live from those, using the same weights and the same league mean/sd that
db.py uses for real players. That means a custom hitter is scored on
exactly the same scale as everyone in the league, not an invented one.

Slider ranges are the 5th-95th percentile of the actual qualified pool
rather than hardcoded bounds, so they cannot drift out of step with the
league as the data changes.
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import prefs
import style

st.set_page_config(page_title="Simulator | Diamond Metrics", layout="wide")
st.title("Player Simulator")
st.caption(
    "Build a hitter: set how he puts the ball in play, and how good he is at the three things "
    "that decide what happens when he does. Nothing is predicted yet — this is the control panel."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
seasons = db.get_seasons("batting")
season = st.selectbox("Compare against season", seasons, index=prefs.default_season_index(seasons))


# --- the league pool every custom player is measured against ----------------
@st.cache_data(show_spinner=False, max_entries=4)
def _component_pool(season: int, db_mtime_val: float) -> pd.DataFrame:
    """One row per qualified batter carrying every component of all three
    scores, pulled from the three tables they live across."""
    bat = db.load_batting(season, db_mtime_val)
    bt = db.load_bat_tracking(season, db_mtime_val)
    disc = db.load_plate_discipline(season, db_mtime_val)

    keep_bat = [c for c in ("mlbID", "PA", "hard_hit_pct", "avg_exit_velo", "max_exit_velo",
                            "sweet_spot_percent", "hp_to_1b") if c in bat.columns]
    out = bat[keep_bat]
    if not bt.empty:
        keep_bt = [c for c in ("mlbID", "avg_bat_speed", "swing_length") if c in bt.columns]
        out = out.merge(bt[keep_bt], on="mlbID", how="left")
    if not disc.empty:
        out = out.merge(disc.drop(columns="season", errors="ignore"), on="mlbID", how="left")
    return out[out["PA"] >= db.QUALIFIED_MIN_PA] if "PA" in out.columns else out


pool = _component_pool(season, mtime)
if pool.empty:
    st.warning("No qualified batters for this season yet.")
    st.stop()

# label, unit-suffix, decimals, and whether the stored value is a 0-1
# fraction that should be shown as a percentage.
_COMPONENT_META = {
    # Eye
    "chase_take":         ("Chase Take%", "%", 1, True),
    "shadow_out_take":    ("Shadow-out Take%", "%", 1, True),
    "shadow_in_swing":    ("Shadow-in Swing%", "%", 1, True),
    "waste_take":         ("Waste Take%", "%", 1, True),
    "heart_swing":        ("Heart Swing%", "%", 1, True),
    # Contact
    "two_strike_contact": ("Two-strike Contact%", "%", 1, True),
    "shadow_in_contact":  ("Shadow-in Contact%", "%", 1, True),
    "shadow_out_contact": ("Shadow-out Contact%", "%", 1, True),
    "chase_contact":      ("Chase Contact%", "%", 1, True),
    "heart_contact":      ("Heart Contact%", "%", 1, True),
    "swing_length":       ("Swing Length (ft)", " ft", 1, False),
    "hp_to_1b":           ("Home-to-1st (s)", " s", 2, False),
    # Power
    "hard_hit_pct":       ("Hard-Hit%", "%", 1, False),
    "avg_exit_velo":      ("Avg Exit Velo", " mph", 1, False),
    "max_exit_velo":      ("Max Exit Velo", " mph", 1, False),
    "sweet_spot_percent": ("Sweet-Spot%", "%", 1, False),
    "avg_bat_speed":      ("Bat Speed", " mph", 1, False),
}

SCORES = {
    "Eye": (db._EYE_WEIGHTS, set(),
            "Swing decisions — do you offer at the right pitches."),
    "Contact": (db._CONTACT_WEIGHTS, db._CONTACT_INVERTED,
                "Bat-to-ball — do you hit it when you swing."),
    "Power": (db._POWER_WEIGHTS, set(),
              "Damage — how hard, and at what angle."),
}


def _stats_for(col):
    """mean / sd / display range for one component, from the real pool."""
    s = pool[col].dropna() if col in pool.columns else pd.Series(dtype=float)
    if s.empty or not s.std():
        return None
    scale = 100.0 if _COMPONENT_META.get(col, (None, None, None, False))[3] else 1.0
    return {
        "mean": float(s.mean()) * scale,
        "sd": float(s.std()) * scale,
        "lo": float(s.quantile(0.05)) * scale,
        "hi": float(s.quantile(0.95)) * scale,
        "scale": scale,
    }


def _score_from_components(weights, inverted, values, refs):
    """Same math as db.py: weighted mean of z-scores, 50 + 15z, and the
    weights of any component we could not measure are renormalised out."""
    wz = 0.0
    used = 0.0
    for col, w in weights.items():
        ref = refs.get(col)
        if not ref:
            continue
        z = (values[col] - ref["mean"]) / ref["sd"]
        if col in inverted:
            z = -z
        wz += w * z
        used += w
    if not used:
        return 50
    return int(round(min(100, max(1, 50 + 15 * (wz / used)))))


# --- batted-ball profile ----------------------------------------------------
style.colored_header("Batted Ball Profile", "batting")
st.caption(
    "Where the ball goes when he puts it in play. These six are every batted ball, so they should "
    "total 100% — Air is fly balls, line drives and popups together."
)

_BB_SLIDERS = [
    ("pull_air", "Pull Air%", 18.0), ("straight_air", "Straight Air%", 20.0),
    ("oppo_air", "Oppo Air%", 17.0), ("pull_gb", "Pull GB%", 20.0),
    ("straight_gb", "Straight GB%", 15.0), ("oppo_gb", "Oppo GB%", 5.0),
]
bb_values = {}
air_col, gb_col = st.columns(2)
for col_container, group in ((air_col, _BB_SLIDERS[:3]), (gb_col, _BB_SLIDERS[3:])):
    with col_container:
        for key, label, default in group:
            bb_values[key] = st.slider(label, 0.0, 60.0, default, 0.5, key=f"bb_{key}")

total = sum(bb_values.values())
if abs(total - 100.0) < 0.05:
    st.success(f"Batted-ball profile totals {total:.1f}%")
elif total > 100:
    st.warning(f"Totals {total:.1f}% — that's {total - 100:.1f}% more than a hitter actually has.")
else:
    st.warning(f"Totals {total:.1f}% — {100 - total:.1f}% of his batted balls are unaccounted for.")

# --- the three skill scores -------------------------------------------------
score_values = {}
for name, (weights, inverted, blurb) in SCORES.items():
    style.colored_header(name, "batting")
    st.caption(blurb)

    refs = {c: _stats_for(c) for c in weights}
    refs = {c: r for c, r in refs.items() if r}
    detailed = st.toggle(
        f"Set {name} by individual stats", key=f"detail_{name}",
        help="Off: one slider for the score. On: set the real stats it's built from, and the score follows.",
    )

    if not detailed or not refs:
        score_values[name] = st.slider(name, 1, 100, 50, key=f"score_{name}")
        if not refs:
            st.caption("Component data isn't in the database for this season — score slider only.")
    else:
        cols = st.columns(min(3, len(refs)))
        vals = {}
        for i, (col, ref) in enumerate(refs.items()):
            label, suffix, dec, _ = _COMPONENT_META.get(col, (col, "", 1, False))
            step = round(max((ref["hi"] - ref["lo"]) / 100, 10 ** -dec), dec)
            with cols[i % len(cols)]:
                vals[col] = st.slider(
                    f"{label}{suffix}",
                    round(ref["lo"] - 2 * ref["sd"], dec), round(ref["hi"] + 2 * ref["sd"], dec),
                    round(ref["mean"], dec), step,
                    key=f"comp_{name}_{col}",
                    help=f"League average {ref['mean']:.{dec}f}"
                         + ("  ·  lower is better" if col in inverted else ""),
                )
        score_values[name] = _score_from_components(weights, inverted, vals, refs)
        st.metric(f"{name} score", score_values[name],
                  delta=f"{score_values[name] - 50:+d} vs league average", delta_color="normal")

# --- what you've built ------------------------------------------------------
style.colored_header("Your Hitter", "batting")
c1, c2, c3 = st.columns(3)
for c, name in zip((c1, c2, c3), SCORES):
    c.metric(name, score_values.get(name, 50))

st.caption(
    "Next: this profile gets matched against every qualified hitter to predict a stat line and "
    "surface his closest real-life comps. Not wired up yet."
)
