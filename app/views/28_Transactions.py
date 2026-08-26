"""Transactions — recent MLB roster moves. Split out of the old
combined Around the League page."""
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import teams

st.set_page_config(page_title="Transactions | Diamond Metrics", layout="wide")
st.title("Transactions")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

st.caption("Recent MLB roster moves — trades, signings, DFAs, and more.")

def render_transaction_card(row):
    badges = ""
    for abbr in [row["to_abbr"], row["from_abbr"]]:
        if isinstance(abbr, str):
            color = teams.color_for_abbr(abbr)
            badges += (
                f"<span style='background-color:{color}66;color:var(--dm-text);padding:2px 8px;"
                f"border-radius:6px;font-weight:700;font-size:0.8rem;margin-right:6px'>{abbr}</span>"
            )
    st.markdown(
        f"<div class='dm-flat-card' style='background-color:var(--dm-surface-mute);"
        f"border-left:4px solid var(--dm-blue);padding:10px 14px;"
        f"border-radius:6px;margin:6px 0'>"
        f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px'>"
        f"<div>{badges}<span style='color:var(--dm-dim);font-size:0.85rem'>{row['type']}</span></div>"
        f"<span style='color:var(--dm-dim);font-size:0.85rem'>{row['date']}</span>"
        f"</div>"
        f"<div style='color:var(--dm-text)'>{row['description']}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

window_options = {"Last 3 days": 3, "Last 7 days": 7, "Last 14 days": 14, "Last 30 days": 30}
window_label = st.selectbox("Lookback window", list(window_options.keys()), index=1)
days = window_options[window_label]

with st.spinner("Loading transactions..."):
    txs = db.load_transactions(days)

if txs.empty:
    st.info("No transactions found in this window.")
else:
    all_types = sorted(txs["type"].dropna().unique().tolist())
    default_types = [t for t in ["Trade", "Signed as Free Agent", "Designated for Assignment", "Released", "Claimed Off Waivers", "Status Change"] if t in all_types]
    type_filter = st.multiselect("Transaction type", all_types, default=default_types or all_types)

    team_abbrs = sorted({a for a in txs["to_abbr"].tolist() + txs["from_abbr"].tolist() if isinstance(a, str)})
    tx_team_filter = st.selectbox("Team", ["All teams"] + team_abbrs, key="tx_team")

    filtered = txs[txs["type"].isin(type_filter)] if type_filter else txs
    if tx_team_filter != "All teams":
        filtered = filtered[(filtered["to_abbr"] == tx_team_filter) | (filtered["from_abbr"] == tx_team_filter)]

    st.caption(f"{len(filtered)} transactions")

    for _, row in filtered.iterrows():
        render_transaction_card(row)
