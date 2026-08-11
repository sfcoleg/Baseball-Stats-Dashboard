"""Loads hand-written articles for the Daily Digest page. Deliberately NOT
in the SQLite database (which is a daily-ingest artifact, replaced wholesale
by the GitHub Actions refresh) — these are plain markdown files under
content/articles/, git-tracked like everything else in the repo, so they
survive Streamlit Cloud redeploys the same way the code does. New articles
are added by committing a new .md file here (and, optionally, an image
under content/articles/images/) rather than through any in-app UI.

File format — simple frontmatter, then the body:

    ---
    title: Your Title Here
    author: Your Name
    date: 2026-08-10
    mlbid: 123456          (optional — renders that player's MLB headshot)
    image: some-file.jpeg  (optional — renders content/articles/images/some-file.jpeg instead)
    ---
    Body text here, plain text or markdown (headers, bold, links all work
    since it's rendered through st.markdown).
"""
from pathlib import Path

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
        image_path = ARTICLES_DIR / "images" / meta["image"] if meta.get("image") else None
        articles.append({
            "title": meta["title"],
            "author": meta.get("author", ""),
            "date": meta.get("date", ""),
            "mlbid": meta.get("mlbid", ""),
            "image_path": image_path,
            "body": parts[2].strip(),
            "slug": path.stem,
        })
    articles.sort(key=lambda a: a["date"], reverse=True)
    return articles
