import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import sidebar
import style

st.set_page_config(page_title="Prediction Accuracy | Sabermetrics Dashboard", layout="wide")
sidebar.render_search()
st.title("Prediction Accuracy")
st.caption(
    "Track record for this dashboard's own Log5-based win predictions (see the Today's Games page). "
    "Every prediction is locked in the day it's made and checked against the real result once the game "
    "finishes — nothing here is recomputed with hindsight."
)

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
history = db.load_prediction_history(mtime)

if history.empty:
    st.info("No predictions recorded yet — check back after the next daily refresh.")
    st.stop()

resolved = history[history["actual_winner"].notna()].copy()
pending = history[history["actual_winner"].isna()]

if resolved.empty:
    st.info(f"{len(pending)} prediction(s) made so far, none resolved yet — check back once today's games finish.")
    st.stop()

overall_accuracy = resolved["correct"].mean()

col1, col2, col3 = st.columns(3)
col1.metric("Overall Accuracy", f"{overall_accuracy*100:.1f}%")
col2.metric("Games Resolved", len(resolved))
col3.metric("Pending", len(pending))

style.colored_header("Calibration", "chart")
st.caption(
    "How confident the model was in each pick vs. how often it was actually right. "
    "A well-calibrated model's accuracy roughly matches its stated confidence in each bucket."
)

resolved["confidence"] = resolved.apply(
    lambda r: r["predicted_home_prob"] if r["predicted_winner"] == "home" else 1 - r["predicted_home_prob"],
    axis=1,
)
bins = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
labels = ["50-60%", "60-70%", "70-80%", "80-90%", "90-100%"]
resolved["bucket"] = pd.cut(resolved["confidence"], bins=bins, labels=labels, include_lowest=True)
calibration = resolved.groupby("bucket", observed=True).agg(
    predictions=("correct", "count"), accuracy=("correct", "mean")
).reset_index()
calibration["accuracy"] = (calibration["accuracy"] * 100).round(1)
st.dataframe(
    calibration.rename(columns={"bucket": "Confidence", "predictions": "Predictions", "accuracy": "Actual Accuracy %"}),
    use_container_width=True,
    hide_index=True,
)

style.colored_header("Recent Predictions", "batting")
display = resolved[[
    "date", "away_abbr", "away_score", "home_abbr", "home_score", "predicted_winner", "actual_winner", "correct",
]].rename(columns={
    "date": "Date", "away_abbr": "Away", "away_score": "Away Score",
    "home_abbr": "Home", "home_score": "Home Score",
    "predicted_winner": "Predicted", "actual_winner": "Actual", "correct": "Correct",
})
display["Correct"] = display["Correct"].map({1: "Yes", 0: "No"})
st.dataframe(display.head(50), use_container_width=True, hide_index=True)

if not pending.empty:
    style.colored_header("Pending", "headliners")
    st.caption(f"{len(pending)} prediction(s) awaiting a final result.")
    pending_display = pending[["date", "away_abbr", "home_abbr", "predicted_winner", "predicted_home_prob"]].rename(columns={
        "date": "Date", "away_abbr": "Away", "home_abbr": "Home",
        "predicted_winner": "Predicted", "predicted_home_prob": "Home Win Prob",
    })
    st.dataframe(pending_display, use_container_width=True, hide_index=True)
