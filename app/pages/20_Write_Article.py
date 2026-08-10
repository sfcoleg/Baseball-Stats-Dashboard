import sys
from datetime import date
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import articles

st.set_page_config(page_title="Write Article | Diamond Metrics", layout="wide")
st.title("Write Article")

# A password gate, not a real account system — this app has no login
# anywhere else, and one admin writing occasional articles doesn't need
# one either. The page itself is a normal visible sidebar link (per
# request); what's gated is the write form behind it, not the tab's
# existence — a visitor who clicks it just sees a password prompt.
_pw = st.text_input("Admin password", type="password")
if not _pw:
    st.stop()
if _pw != st.secrets.get("admin_password"):
    st.error("Incorrect password.")
    st.stop()

st.success("Welcome back.")
st.caption(
    "Publishing commits the article straight to the GitHub repo (see articles.py) — Streamlit Cloud "
    "redeploys automatically afterward, usually live within a minute or two."
)

with st.form("write_article_form", clear_on_submit=True):
    title = st.text_input("Title")
    author = st.text_input("Byline", value="Greg")
    pub_date = st.date_input("Date", value=date.today())
    body = st.text_area("Body", height=350, placeholder="Plain text or markdown — headers, bold, links all work.")
    submitted = st.form_submit_button("Publish")

if submitted:
    if not title.strip() or not body.strip():
        st.error("Title and body are both required.")
    else:
        with st.spinner("Publishing..."):
            success, message = articles.publish_article(title.strip(), author.strip(), pub_date, body)
        (st.success if success else st.error)(message)

st.divider()
st.caption("Already-published articles:")
for a in articles.load_articles():
    st.markdown(f"- **{a['title']}** — {a['author']}, {a['date']}")
