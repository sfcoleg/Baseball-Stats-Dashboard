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

st.set_page_config(page_title="Sim | Diamond Metrics", layout="wide")
st.title("Player Simulator")
st.caption(
    "Build a hitter: set how he puts the ball in play, and how good he is at the three things "
    "that decide what happens when he does."
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
    "chase_take":         ("Chase Take", "%", 1, True),
    "shadow_out_take":    ("Shadow-out Take", "%", 1, True),
    "shadow_in_swing":    ("Shadow-in Swing", "%", 1, True),
    "waste_take":         ("Waste Take", "%", 1, True),
    "heart_swing":        ("Heart Swing", "%", 1, True),
    # Contact
    "two_strike_contact": ("Two-strike Contact", "%", 1, True),
    "shadow_in_contact":  ("Shadow-in Contact", "%", 1, True),
    "shadow_out_contact": ("Shadow-out Contact", "%", 1, True),
    "chase_contact":      ("Chase Contact", "%", 1, True),
    "heart_contact":      ("Heart Contact", "%", 1, True),
    "swing_length":       ("Swing Length", " ft", 1, False),
    "hp_to_1b":           ("Home-to-1st", " s", 2, False),
    # Power
    "hard_hit_pct":       ("Hard-Hit", "%", 1, False),
    "avg_exit_velo":      ("Avg Exit Velo", " mph", 1, False),
    "max_exit_velo":      ("Max Exit Velo", " mph", 1, False),
    "sweet_spot_percent": ("Sweet-Spot", "%", 1, False),
    "avg_bat_speed":      ("Bat Speed", " mph", 1, False),
}

SCORES = {
    "Eye": (db._EYE_WEIGHTS, set(),
            "Swing decisions — does he offer at the right pitches."),
    "Contact": (db._CONTACT_WEIGHTS, db._CONTACT_INVERTED,
                "Bat-to-ball — does he hit it when he swings."),
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
    }


def _score_from_components(weights, inverted, values, refs):
    """Same math as db.py: weighted mean of z-scores, 50 + 15z, with the
    weights of anything unmeasured renormalised out."""
    wz = used = 0.0
    for col, w in weights.items():
        ref = refs.get(col)
        if not ref:
            continue
        z = (values[col] - ref["mean"]) / ref["sd"]
        wz += w * (-z if col in inverted else z)
        used += w
    if not used:
        return 50
    return int(round(min(100, max(1, 50 + 15 * (wz / used)))))


def _score_colour(score: int) -> str:
    """Red below average, blue above, muted right around it — the same
    reading direction as the gradient on every stat table."""
    if score >= 70:
        return "var(--dm-green)"
    if score >= 58:
        return "var(--dm-blue)"
    if score >= 43:
        return "var(--dm-dim)"
    if score >= 31:
        return "var(--dm-amber)"
    return "var(--dm-red)"


def _score_chip(name: str, score: int) -> str:
    colour = _score_colour(score)
    return (
        f"<div style='flex:1;min-width:150px;background:var(--dm-card);"
        f"border:1px solid var(--dm-line);border-left:4px solid {colour};"
        f"border-radius:10px;padding:14px 16px'>"
        f"<div style='font-size:0.72rem;letter-spacing:1.3px;text-transform:uppercase;"
        f"color:var(--dm-dim)'>{name}</div>"
        f"<div style='font-family:\"Archivo Narrow\",sans-serif;font-weight:800;"
        f"font-size:2.3rem;line-height:1.1;color:{colour}'>{score}</div>"
        f"<div style='font-size:0.75rem;color:var(--dm-dim)'>{score - 50:+d} vs league average</div>"
        f"</div>"
    )


# --- batted-ball profile ----------------------------------------------------
_BB_SLIDERS = [
    ("pull_air", "Pull Air", 18.0, "#2E86DE"),
    ("straight_air", "Straight Air", 20.0, "#6FAFE8"),
    ("oppo_air", "Oppo Air", 17.0, "#A8CDF0"),
    ("pull_gb", "Pull GB", 20.0, "#B7791F"),
    ("straight_gb", "Straight GB", 15.0, "#D6A44C"),
    ("oppo_gb", "Oppo GB", 5.0, "#EBD09A"),
]

with style.section("Batted Ball Profile", "batting"):
    st.caption(
        "Where the ball goes when he puts it in play. Air is fly balls, line drives and popups "
        "together — these six are every batted ball he hits."
    )
    bb_values = {}
    air_col, gb_col = st.columns(2)
    for container, group, heading in ((air_col, _BB_SLIDERS[:3], "In the Air"),
                                      (gb_col, _BB_SLIDERS[3:], "On the Ground")):
        with container:
            st.markdown(
                f"<div style='font-size:0.72rem;letter-spacing:1.3px;text-transform:uppercase;"
                f"color:var(--dm-dim);margin-bottom:2px'>{heading}</div>",
                unsafe_allow_html=True,
            )
            for key, label, default, _ in group:
                bb_values[key] = st.slider(label, 0.0, 60.0, default, 0.5, key=f"bb_{key}",
                                           format="%.1f%%")

    total = sum(bb_values.values())
    # The bar IS the readout: each slice is drawn at its true share of 100%,
    # so a profile that doesn't add up shows as a visible gap (or spills
    # past the marker) instead of needing a warning box to say so.
    slices = "".join(
        f"<div title='{label} {bb_values[key]:.1f}%' style='width:{min(bb_values[key], 100):.2f}%;"
        f"background:{colour};'></div>"
        for key, label, _, colour in _BB_SLIDERS if bb_values[key] > 0
    )
    gap = max(0.0, 100.0 - total)
    if gap > 0:
        slices += (f"<div title='unassigned' style='width:{gap:.2f}%;"
                   f"background:repeating-linear-gradient(45deg,var(--dm-field),"
                   f"var(--dm-field) 6px,transparent 6px,transparent 12px);'></div>")
    note = ("balanced" if abs(total - 100) < 0.05
            else f"{total - 100:+.1f}% off — {'over' if total > 100 else 'unassigned'}")
    if abs(total - 100.0) < 0.05:
        st.success(f"Batted-ball profile totals {total:.1f}%")
    elif total > 100:
        st.warning(f"Totals {total:.1f}% — that's {total - 100:.1f}% more than a hitter actually has.")
    else:
        st.warning(f"Totals {total:.1f}% — {100 - total:.1f}% of his batted balls are unaccounted for.")
    note_colour = "var(--dm-dim)" if abs(total - 100) < 0.05 else "var(--dm-amber)"
    st.markdown(
        f"<div style='margin-top:6px'>"
        f"<div style='display:flex;height:22px;border-radius:6px;overflow:hidden;"
        f"border:1px solid var(--dm-line)'>{slices}</div>"
        f"<div style='display:flex;justify-content:space-between;margin-top:5px;font-size:0.75rem'>"
        f"<span style='color:var(--dm-dim)'>"
        + "  ".join(
            f"<span style='color:{colour}'>&#9632;</span> {label}"
            for _, label, _, colour in _BB_SLIDERS
        )
        + f"</span><span style='color:{note_colour}'>{total:.1f}% &middot; {note}</span></div></div>",
        unsafe_allow_html=True,
    )

# --- the three skill scores -------------------------------------------------
score_values = {}
for name, (weights, inverted, blurb) in SCORES.items():
    with style.section(name, "batting"):
        st.caption(blurb)
        refs = {c: r for c, r in ((c, _stats_for(c)) for c in weights) if r}
        detailed = st.toggle(
            "Set by individual stats", key=f"detail_{name}",
            help="Off: one slider for the score. On: set the real stats it's built from, "
                 "and the score follows.",
        )

        if not detailed or not refs:
            score_values[name] = st.slider(name, 1, 100, 50, key=f"score_{name}",
                                           label_visibility="collapsed")
            if not refs:
                st.caption("Component data isn't in the database for this season — score slider only.")
        else:
            cols = st.columns(min(3, len(refs)))
            vals = {}
            for i, (col, ref) in enumerate(refs.items()):
                label, suffix, dec, _ = _COMPONENT_META.get(col, (col, "", 1, False))
                step = round(max(ref["sd"] / 10, 10 ** -dec), dec)
                # A rate cannot exceed 100% or drop below 0, and 2.5sd off
                # the mean runs past both for the tighter components — the
                # earlier version offered a 105.3% Waste Take slider.
                is_pct = _COMPONENT_META.get(col, (None, "", 1, False))[1] == "%"
                lo_b = round(ref["mean"] - 2.5 * ref["sd"], dec)
                hi_b = round(ref["mean"] + 2.5 * ref["sd"], dec)
                if is_pct:
                    lo_b, hi_b = max(0.0, lo_b), min(100.0, hi_b)
                with cols[i % len(cols)]:
                    vals[col] = st.slider(
                        f"{label}{suffix}", lo_b, hi_b,
                        round(ref["mean"], dec), step, key=f"comp_{name}_{col}",
                        help=f"League average {ref['mean']:.{dec}f}"
                             + ("  ·  lower is better" if col in inverted else ""),
                    )
            score_values[name] = _score_from_components(weights, inverted, vals, refs)
        st.markdown(_score_chip(name, score_values[name]), unsafe_allow_html=True)

# --- what you've built ------------------------------------------------------
with style.section("Your Hitter", "batting"):
    st.markdown(
        "<div style='display:flex;gap:12px;flex-wrap:wrap'>"
        + "".join(_score_chip(n, score_values.get(n, 50)) for n in SCORES)
        + "</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Next: this profile gets matched against every qualified hitter to predict a stat line "
        "and surface his closest real-life comps."
    )
