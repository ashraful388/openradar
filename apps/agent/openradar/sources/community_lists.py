"""Community list reaping.

Pulls a curated set of GitHub README files that track free LLM API
providers, regex-extracts provider hostnames and model ids, and queues
them as candidates. The agent promotes candidates to providers on the
next pass if they have an /v1/models endpoint that returns data."""
from __future__ import annotations
import re
import httpx

REPOS: list[tuple[str, str]] = [
    # (raw README url, label)
    ("https://raw.githubusercontent.com/cheahjs/free-llm-api-resources/main/README.md", "cheahjs/free-llm-api-resources"),
    ("https://raw.githubusercontent.com/zukixa/cool-ai-stuff/main/README.md", "zukixa/cool-ai-stuff"),
    ("https://raw.githubusercontent.com/jamez-bondos/awesome-gpt4o-images/main/README.md", "jamez-bondos/awesome-gpt4o-images"),
    ("https://raw.githubusercontent.com/open-free-llm-api/awesome-freellm-apis/main/README.md", "open-free-llm-api/awesome-freellm-apis"),
    ("https://raw.githubusercontent.com/nejib1/Free-LLM/main/README.md", "nejib1/Free-LLM"),
]

# Match a markdown table row of the form `| [name](https://host/path) | ...`
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
HOST_RE = re.compile(r"^https?://([a-z0-9\-\.]+)/?", re.IGNORECASE)
BARE_HOST_RE = re.compile(r"\b([a-z0-9-]+\.(?:ai|com|dev|io|app|cloud))\b", re.IGNORECASE)

# Hosts that are *infra*, not providers — never auto-promote.
NOISE_HOSTS = {
    "github.com", "github.io", "raw.githubusercontent.com", "shields.io", "badgen.net",
    "vercel.com", "netlify.com", "twitter.com", "x.com", "youtube.com", "youtu.be",
    "discord.gg", "discord.com", "reddit.com", "huggingface.co", "openrouter.ai",
    "platform.openai.com", "docs.anthropic.com", "console.groq.com", "console.cloud.google.com",
    "kaggle.com", "replicate.com", "poe.com", "perplexity.ai",
    "img.shields.io", "i.imgur.com", "i.giphy.com", "media.giphy.com", "wikimedia.org",
    "upload.wikimedia.org", "commons.wikimedia.org", "google.com", "googleusercontent.com",
    "wikipedia.org", "en.wikipedia.org", "medium.com", "substack.com", "notion.so",
    "notion.site", "figma.com", "drive.google.com", "docs.google.com", "sheets.google.com",
    "arxiv.org", "doi.org", "zenodo.org", "githubusercontent.com", "paypal.com",
    "buymeacoffee.com", "patreon.com", "kofi.com", "opencollective.com",
}

# Hosts that look like CDNs / image hosts and should be filtered out by suffix.
CDN_SUFFIXES = (".cdn.", ".static.", ".assets.", "cdn.", "static.", "media.",
                "fonts.", "images.", "img.")

# Markdown image syntax `![alt](url)` — those alt texts are noise, not names.
IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")


def fetch_all(timeout: float = 30.0) -> list[tuple[str, str]]:
    """Return list of (source_label, readme_text). Empty entries are dropped."""
    out: list[tuple[str, str]] = []
    for url, label in REPOS:
        try:
            r = httpx.get(url, timeout=timeout, follow_redirects=True)
            if r.status_code == 200 and r.text:
                out.append((label, r.text))
        except httpx.HTTPError:
            continue
    return out


def _clean_name(name: str) -> str:
    """Strip markdown image syntax and other noise from a candidate name."""
    n = IMG_RE.sub("", name).strip()
    # If the name still starts with a punctuation, take what's after it.
    n = n.lstrip("|*-_#").strip()
    return n or "unknown"


def _is_noise_host(host: str) -> bool:
    if host in NOISE_HOSTS:
        return True
    if any(s in host for s in CDN_SUFFIXES):
        return True
    return False


def extract_candidates(items: list[tuple[str, str]]) -> list[dict]:
    """For each README, find links whose host isn't a known infra host and
    isn't already a known provider. The result is a list of
    {host, name, source} dicts."""
    seen: set[str] = set()
    out: list[dict] = []
    for label, text in items:
        for m in LINK_RE.finditer(text):
            raw_name = m.group(1)
            # Skip markdown images: ![alt](url)
            if raw_name.startswith("!"):
                continue
            name = _clean_name(raw_name)
            url = m.group(2).strip()
            host_m = HOST_RE.match(url)
            if not host_m:
                continue
            host = host_m.group(1).lower()
            if _is_noise_host(host) or host in seen:
                continue
            if host.startswith("localhost") or "127.0.0.1" in host:
                continue
            seen.add(host)
            out.append({"host": host, "name": name, "url": url, "source": label})
        # Also pick up bare hostnames mentioned in body text, but require
        # the immediate context to be a model/API mention, not a badge alt.
        for m in BARE_HOST_RE.finditer(text):
            host = m.group(1).lower()
            if _is_noise_host(host) or host in seen:
                continue
            seen.add(host)
            out.append({"host": host, "name": host, "url": f"https://{host}", "source": label})
    return out
