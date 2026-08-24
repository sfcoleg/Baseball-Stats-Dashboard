import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Free Agency | Diamond Metrics", layout="wide")
st.title("Free Agency")
st.caption(
    "Players currently unattached, inferred from MLB's transaction log (declared free agency or "
    "released, with no signing/trade/waiver claim since)."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()

with st.spinner("Loading free agents..."):
    fa = db.free_agent_tracker(mtime)

if fa.empty:
    st.info("No free agents found.")
    st.stop()

col1, col2, col3 = st.columns(3)
with col1:
    positions = sorted(fa["Pos"].dropna().unique().tolist())
    pos_filter = st.multiselect("Position", positions, default=[])
with col2:
    ages = fa["Age"].dropna()
    if len(ages):
        age_range = st.slider("Age", int(ages.min()), int(ages.max()), (int(ages.min()), int(ages.max())))
    else:
        age_range = None
with col3:
    exp = fa["experience_years"].dropna()
    if len(exp):
        exp_range = st.slider("Years of experience", 0.0, float(exp.max()), (0.0, float(exp.max())))
    else:
        exp_range = None

filtered = fa.copy()
if pos_filter:
    filtered = filtered[filtered["Pos"].isin(pos_filter)]
if age_range:
    filtered = filtered[filtered["Age"].between(*age_range) | filtered["Age"].isna()]
if exp_range:
    filtered = filtered[filtered["experience_years"].between(*exp_range) | filtered["experience_years"].isna()]

st.caption(f"{len(filtered)} free agents")


def render_fa_card(row):
    team_abbr = row["last_team"] if isinstance(row["last_team"], str) else None
    team_color = teams.color_for_abbr(team_abbr) if team_abbr else "#666666"
    badge = (
        f"<span style='background-color:{team_color}66;color:var(--dm-text);padding:2px 9px;"
        f"border-radius:8px;font-size:0.65em;vertical-align:middle;font-weight:600'>{team_abbr}</span>"
        if team_abbr else ""
    )
    meta_bits = []
    if row.get("Pos"):
        meta_bits.append(row["Pos"])
    if row.get("Age") == row.get("Age"):  # not NaN
        meta_bits.append(f"Age {int(row['Age'])}")
    if row.get("experience_years") == row.get("experience_years"):
        meta_bits.append(f"{row['experience_years']:.1f} yrs MLB exp")
    meta_line = " · ".join(meta_bits)

    stat_line = row.get("last_stat_line") or "No recent MLB stats"
    season = row.get("last_season")
    stat_label = f"{int(season)}: {stat_line}" if season == season else stat_line

    st.markdown(
        f"<div style='display:flex;align-items:flex-start;gap:12px;margin-bottom:20px'>"
        f"<img src='{style.headshot_url(row['mlbID'], width=180)}' style='width:80px;height:80px;"
        f"border-radius:10px;object-fit:cover;object-position:center 25%;flex-shrink:0' />"
        f"<div style='flex:1;min-width:0'>"
        f"<div style='font-size:1.1rem;font-weight:700;line-height:1.3;overflow-wrap:break-word'>{row['Name']} {badge}</div>"
        f"<div style='color:var(--dm-dim);font-size:0.85rem;margin-top:2px'>{meta_line}</div>"
        f"<div style='margin-top:6px'><span style='background-color:var(--dm-blue-soft);color:var(--dm-blue-text);padding:3px 10px;"
        f"border-radius:8px;font-weight:600;font-size:0.9rem'>{stat_label}</span></div>"
        f"<div style='color:var(--dm-dim);font-size:0.8rem;margin-top:4px'>{row['fa_type']} · {row['fa_date']}</div>"
        f"</div></div>",
        unsafe_allow_html=True,
    )


for _, row in filtered.iterrows():
    render_fa_card(row)

style.colored_header("Recent Signings", "fielding")
with st.spinner("Loading recent signings..."):
    signings = db.recent_free_agent_signings(mtime, days=90)

if signings.empty:
    st.caption("No free agents have signed in the last 90 days.")
else:
    for _, row in signings.iterrows():
        team_abbr = row["new_team"] if isinstance(row["new_team"], str) else None
        color = teams.color_for_abbr(team_abbr) if team_abbr else "#666666"
        badge = (
            f"<span style='background-color:{color}66;color:var(--dm-text);padding:2px 8px;"
            f"border-radius:6px;font-weight:700;font-size:0.8rem;margin-right:6px'>{team_abbr}</span>"
            if team_abbr else ""
        )
        st.markdown(
            f"<div style='background-color:var(--dm-surface-mute);border-left:4px solid var(--dm-blue);padding:8px 14px;"
            f"border-radius:6px;margin:4px 0'>{badge}"
            f"<span style='color:var(--dm-dim);font-size:0.85rem'>{row['signed_date']}</span>"
            f"<div style='color:var(--dm-text)'>{row['description']}</div></div>",
            unsafe_allow_html=True,
        )
