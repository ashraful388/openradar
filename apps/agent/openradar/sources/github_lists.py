"""Community list ingestion: the cheahjs/free-llm-api-resources repo and similar.

We pull the README, regex out provider/model mentions, and queue them as
candidates for the review step. We do NOT auto-add anything from these
sources — the human/agent curator makes that call."""
from __future__ import annotations
import re
import httpx

REPOS = [
    "https://raw.githubusercontent.com/cheahjs/free-llm-api-resources/main/README.md",
    # Add more curated lists here as the project grows.
]

PROVIDER_HINT = re.compile(r"`?https?://([a-z0-9\-\.]+)/?`?", re.IGNORECASE)


def fetch_all(timeout: float = 30.0) -> list[str]:
    out: list[str] = []
    for url in REPOS:
        try:
            r = httpx.get(url, timeout=timeout, follow_redirects=True)
            if r.status_code == 200:
                out.append(r.text)
        except httpx.HTTPError:
            continue
    return out


def extract_candidates(readmes: list[str]) -> list[dict]:
    """Cheap extraction: every homepage link in the README is a candidate provider."""
    seen: set[str] = set()
    out: list[dict] = []
    for text in readmes:
        for m in PROVIDER_HINT.finditer(text):
            host = m.group(1).lower()
            if host in seen or host.endswith("github.com") or host.endswith("github.io"):
                continue
            seen.add(host)
            out.append({"homepage": f"https://{host}", "host": host, "source": "github_list"})
    return out
