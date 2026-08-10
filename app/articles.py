"""Loads hand-written articles for the Daily Digest page. Deliberately NOT
in the SQLite database (which is a daily-ingest artifact, replaced wholesale
by the GitHub Actions refresh) — these are plain markdown files under
content/articles/, git-tracked like everything else in the repo, so they
survive Streamlit Cloud redeploys the same way the code does. Written by a
person (unlike the researched player-bio experiment this app tried and
dropped), so there's no ingest step: just add a .md file and push.

File format — simple frontmatter, then the body:

    ---
    title: Your Title Here
    author: Your Name
    date: 2026-08-10
    ---
    Body text here, plain text or markdown (headers, bold, links all work
    since it's rendered through st.markdown).
"""
import base64
import re
from pathlib import Path

import requests
import streamlit as st

ARTICLES_DIR = Path(__file__).resolve().parent.parent / "content" / "articles"


def load_articles() -> list[dict]:
    """Every article in content/articles/, newest first (by the `date`
    frontmatter field, not file mtime — so backdating or reordering is just
    a matter of editing that field). Malformed files (no frontmatter, no
    title) are skipped rather than crashing the page."""
    if not ARTICLES_DIR.exists():
        return []
    articles = []
    for path in sorted(ARTICLES_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        meta = {}
        for line in parts[1].strip().splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip().lower()] = value.strip()
        if not meta.get("title"):
            continue
        articles.append({
            "title": meta["title"],
            "author": meta.get("author", ""),
            "date": meta.get("date", ""),
            "body": parts[2].strip(),
            "slug": path.stem,
        })
    articles.sort(key=lambda a: a["date"], reverse=True)
    return articles


def publish_article(title: str, author: str, pub_date, body: str) -> tuple[bool, str]:
    """Commits a new article file straight to the live GitHub repo via the
    Contents API — the only way something written in the deployed app can
    actually stick. Streamlit Community Cloud's own filesystem is
    ephemeral (wiped and rebuilt from the repo on every redeploy), so a
    local file write here would vanish the moment the app restarts; a
    real commit is what makes it permanent, and it's what the daily stats
    refresh already does for the same reason (see the GitHub Actions
    workflow). Requires two Streamlit secrets:
      github_token — a fine-grained personal access token scoped to just
        this repo, with Contents: Read and write permission
        (github.com/settings/personal-access-tokens/new)
      github_repo  — "owner/repo", e.g. "sfcoleg/Baseball-Stats-Dashboard"
    Set both in the app's Settings -> Secrets on share.streamlit.io (and,
    for local testing, in .streamlit/secrets.toml — gitignored, never
    commit real tokens). Returns (success, message)."""
    token = st.secrets.get("github_token")
    repo = st.secrets.get("github_repo")
    if not token or not repo:
        return False, "Not configured yet — see articles.py's publish_article docstring for the two secrets it needs."

    slug_base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "article"
    slug = f"{pub_date.isoformat()}-{slug_base}"
    path = f"content/articles/{slug}.md"
    content = f"---\ntitle: {title}\nauthor: {author}\ndate: {pub_date.isoformat()}\n---\n{body.strip()}\n"

    try:
        resp = requests.put(
            f"https://api.github.com/repos/{repo}/contents/{path}",
            headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
            json={
                "message": f"Add article: {title}",
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            },
            timeout=15,
        )
    except requests.RequestException as e:
        return False, f"Couldn't reach GitHub ({e})."

    if resp.status_code in (200, 201):
        return True, (
            "Published! Streamlit Cloud will pick up the new commit and redeploy automatically — "
            "usually live within a minute or two."
        )
    return False, f"GitHub API error ({resp.status_code}): {resp.text[:300]}"
