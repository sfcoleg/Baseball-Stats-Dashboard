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
    # The six batted-ball rates live in their own table and were missing
    # here, so "load a real player" silently left the profile sliders at
    # their defaults — which happen to total 95%, the number that showed up
    # on screen.
    bb = db.load_batted_ball(season, db_mtime_val)
    if not bb.empty:
        bb_cols = [c for c in ("mlbID", "pull_air_rate", "straight_air_rate", "oppo_air_rate",
                               "pull_gb_rate", "straight_gb_rate", "oppo_gb_rate")
                   if c in bb.columns]
        out = out.merge(bb[bb_cols], on="mlbID", how="left")
    return out


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


def _score_pool(score_name: str) -> pd.DataFrame:
    """The population a score is scaled against — which is NOT the same for
    all three, and has to match db.py exactly or a custom hitter lands on a
    different scale than every real player on the site. Getting this wrong
    put the Sim 1-3 points off db.py's own numbers for the same player,
    worst on Power, whose db.py default is PA >= 100 rather than 200."""
    if score_name == "Eye" and "total_pitches" in pool.columns:
        return pool[pool["total_pitches"] >= db.EYE_MIN_PITCHES]
    if score_name == "Contact" and "two_strike_swings" in pool.columns:
        return pool[pool["two_strike_swings"] >= db.CONTACT_MIN_SWINGS]
    if score_name == "Power" and "PA" in pool.columns:
        return pool[pool["PA"] >= 100]
    return pool


def _stats_for(col, score_name="Eye"):
    """mean / sd / display range for one component, from that score's own
    reference population."""
    ref_pool = _score_pool(score_name)
    s = ref_pool[col].dropna() if col in ref_pool.columns else pd.Series(dtype=float)
    if s.empty or not s.std():
        return None
    scale = 100.0 if _COMPONENT_META.get(col, (None, None, None, False))[3] else 1.0
    return {
        "mean": float(s.mean()) * scale,
        "sd": float(s.std()) * scale,
        "lo": float(s.quantile(0.05)) * scale,
        "hi": float(s.quantile(0.95)) * scale,
        # Autofill writes a real player's actual value into these sliders,
        # and Streamlit raises if a value sits outside a slider's range —
        # so the track has to contain the whole league, not just the middle
        # of it. Arraez's contact rates are far beyond +2.5sd.
        "min": float(s.min()) * scale,
        "max": float(s.max()) * scale,
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


# --- load a real player ------------------------------------------------------
_BB_COLUMNS = {
    "pull_air": "pull_air_rate", "straight_air": "straight_air_rate",
    "oppo_air": "oppo_air_rate", "pull_gb": "pull_gb_rate",
    "straight_gb": "straight_gb_rate", "oppo_gb": "oppo_gb_rate",
}


def _autofill():
    """Copy a real hitter's own numbers into every control.

    Runs as an on_change CALLBACK, which matters: Streamlit will not let
    you assign to a widget's session_state key after that widget has been
    created in the same run. A callback fires before the rerun builds the
    widgets, so the sliders come up already holding the new values.

    Each score is also flipped into detailed mode, since the point of
    loading a player is to see the real stats underneath his score — and
    the score recomputed from them should land on the same number db.py
    gives that player, which is a live check that both paths agree.
    """
    label = st.session_state.get("sim_player")
    mlb_id = player_ids.get(label)
    if mlb_id is None:
        return
    rows = pool[pool["mlbID"] == mlb_id]
    if rows.empty:
        return
    row = rows.iloc[0]

    for key, col in _BB_COLUMNS.items():
        if col in row.index and pd.notna(row[col]):
            st.session_state[f"bb_{key}"] = round(float(row[col]) * 100, 1)

    for score_name, (weights, _inv, _blurb) in SCORES.items():
        filled = False
        for col in weights:
            ref = _stats_for(col, score_name)
            if not ref or col not in row.index or pd.isna(row[col]):
                continue
            _lbl, suffix, dec, is_frac = _COMPONENT_META.get(col, (col, "", 1, False))
            value = float(row[col]) * (100.0 if is_frac else 1.0)
            lo_b = round(min(ref["mean"] - 2.5 * ref["sd"], ref["min"]), dec)
            hi_b = round(max(ref["mean"] + 2.5 * ref["sd"], ref["max"]), dec)
            if suffix == "%":
                lo_b, hi_b = max(0.0, lo_b), min(100.0, hi_b)
            st.session_state[f"comp_{score_name}_{col}"] = round(
                min(max(value, lo_b), hi_b), dec
            )
            filled = True
        if filled:
            st.session_state[f"detail_{score_name}"] = True


def _reset_controls():
    """Clear every control back to its default. Runs as a callback so it
    may touch sim_player, which is a live widget key."""
    for k in list(st.session_state):
        if k.startswith(("bb_", "comp_", "detail_", "score_")):
            del st.session_state[k]
    st.session_state["sim_player"] = "—"


_names = db.load_batting(season, mtime)[["mlbID", "Name", "PA"]]
_names = _names[_names["mlbID"].isin(pool["mlbID"])].dropna(subset=["Name"])
_names = _names[_names["PA"] >= db.QUALIFIED_MIN_PA]
_names = _names.sort_values("PA", ascending=False)
player_ids = dict(zip(_names["Name"], _names["mlbID"]))

with style.section("Start From a Real Player", "batting"):
    st.caption(
        f"Optional. Pick a {season} hitter and every control below fills with his actual numbers — "
        "then change whatever you want from there."
    )
    pick_col, clear_col = st.columns([4, 1])
    with pick_col:
        st.selectbox(
            "Player", ["—"] + list(player_ids), key="sim_player",
            on_change=_autofill, label_visibility="collapsed",
        )
    with clear_col:
        # on_click, not an `if st.button(...)` body, for the same reason
        # _autofill is a callback: this clears sim_player, and Streamlit
        # refuses to modify a widget's session_state key once that widget
        # has been created in the current run — the selectbox above already
        # has been. Doing it inline raised StreamlitAPIException every time
        # Reset was pressed. A callback runs before the rerun builds any
        # widgets, so the assignment is legal there.
        st.button("Reset", on_click=_reset_controls, use_container_width=True)


# --- batted-ball profile ----------------------------------------------------
# Defaults are the league average of each rate, so a fresh page starts on a
# real, balanced hitter. The previous hand-picked numbers totalled 95%,
# which read as a bug the moment anyone looked at the total.
_BB_SLIDERS = [
    ("pull_air", "Pull Air", 18.5, "#2E86DE"),
    ("straight_air", "Straight Air", 20.3, "#6FAFE8"),
    ("oppo_air", "Oppo Air", 17.6, "#A8CDF0"),
    ("pull_gb", "Pull GB", 20.6, "#B7791F"),
    ("straight_gb", "Straight GB", 16.0, "#D6A44C"),
    ("oppo_gb", "Oppo GB", 7.0, "#EBD09A"),
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
                bb_values[key] = st.slider(label, 0.0, 60.0, default, 0.1, key=f"bb_{key}",
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
    # Six sliders each rounded to 0.1 can be off by up to 0.3 in total, so a
    # real player who genuinely sums to 100 lands on 99.9 or 100.1. Anything
    # inside that is rounding, not an unbalanced profile.
    _ROUNDING_SLACK = 0.35
    note = ("balanced" if abs(total - 100) <= _ROUNDING_SLACK
            else f"{total - 100:+.1f}% off — {'over' if total > 100 else 'unassigned'}")
    if abs(total - 100.0) <= _ROUNDING_SLACK:
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
        refs = {c: r for c, r in ((c, _stats_for(c, name)) for c in weights) if r}
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
                lo_b = round(min(ref["mean"] - 2.5 * ref["sd"], ref["min"]), dec)
                hi_b = round(max(ref["mean"] + 2.5 * ref["sd"], ref["max"]), dec)
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
