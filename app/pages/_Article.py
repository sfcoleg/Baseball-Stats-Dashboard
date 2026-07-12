import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import style

st.set_page_config(page_title="Article | Sabermetrics Dashboard", layout="wide")

article = st.session_state.get("selected_article")
if not article:
    st.title("Article")
    st.info("Pick a storyline from the Daily Digest page to read it here.")
    st.stop()

if st.button("← Back to Daily Digest"):
    st.switch_page("pages/12_Daily_Digest.py")

st.markdown(
    f"<div style='display:flex;align-items:center;gap:16px;margin-top:12px'>"
    f"<img src='{style.headshot_url(article['mlbID'], width=240)}' style='width:100px;height:100px;"
    f"border-radius:12px;object-fit:cover;flex-shrink:0' />"
    f"<div><h1 style='margin:0'>{article['headline']}</h1>"
    f"<span style='background-color:{article['color']}66;color:#FAFAFA;padding:3px 12px;"
    f"border-radius:8px;font-weight:700;font-size:0.9rem'>{article['Tm']}</span></div>"
    f"</div>",
    unsafe_allow_html=True,
)
st.divider()

for paragraph in article["paragraphs"]:
    st.markdown(f"<p style='font-size:1.05rem;line-height:1.7;color:#DCE1EA'>{paragraph}</p>", unsafe_allow_html=True)
