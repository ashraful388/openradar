"""Search-based discovery of new free-API providers.

Preference order: Brave → Tavily → Exa (all have free tiers; keys come
from env vars or the Settings → Provider API keys store), then a keyless
DuckDuckGo HTML fallback so discovery never depends on the operator
having signed up anywhere. The fallback is best-effort: DDG has no
official free API and sometimes CAPTCHAs datacenter IPs (CI runners), in
which case it returns [] and the run moves on."""
from __future__ import annotations
import os
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from .. import provider_keys

_UDDG_RE = re.compile(r"uddg=([^&]+)")


def search_new_free_apis(query: str = "new free LLM API 2026 site launch", limit: int = 10) -> list[dict]:
    for env_name, fn in (
        ("BRAVE_SEARCH_API_KEY", _brave),
        ("TAVILY_API_KEY", _tavily),
        ("EXA_API_KEY", _exa),
    ):
        # provider_keys.get checks the env var first, then the local
        # Settings-written key file — either source enables the engine.
        if key := provider_keys.get(env_name):
            if results := fn(query, key, limit):
                return results
    return _duckduckgo(query, limit)


def _brave(query: str, key: str, limit: int) -> list[dict]:
    try:
        r = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": limit},
            headers={"X-Subscription-Token": key},
            timeout=20.0,
        )
        if r.status_code != 200:
            return []
        return r.json().get("web", [])
    except httpx.HTTPError:
        return []


def _tavily(query: str, key: str, limit: int) -> list[dict]:
    try:
        r = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": query, "max_results": limit},
            timeout=20.0,
        )
        if r.status_code != 200:
            return []
        return r.json().get("results", [])
    except httpx.HTTPError:
        return []


def _exa(query: str, key: str, limit: int) -> list[dict]:
    try:
        r = httpx.post(
            "https://api.exa.ai/search",
            json={"query": query, "numResults": limit},
            headers={"x-api-key": key},
            timeout=20.0,
        )
        if r.status_code != 200:
            return []
        return r.json().get("results", [])
    except httpx.HTTPError:
        return []


def _unwrap_ddg(href: str) -> str:
    """DDG wraps results in /l/?uddg=<urlencoded> redirects — extract the
    real URL; anything else is returned as-is."""
    if "uddg=" not in href:
        return href.replace("&amp;", "&")
    m = _UDDG_RE.search(href.replace("&amp;", "&"))
    return unquote(m.group(1)) if m else href


def _duckduckgo(query: str, limit: int) -> list[dict]:
    """Scrape DuckDuckGo's lightweight HTML endpoints for result links.
    Returns [{title, url}] shaped like the API results so ingest_search
    can treat every engine identically."""
    for url, data in (
        ("https://html.duckduckgo.com/html/", {"q": query}),
        ("https://lite.duckduckgo.com/lite/", {"q": query}),
    ):
        try:
            r = httpx.post(
                url,
                data=data,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                timeout=20.0,
                follow_redirects=True,
            )
            if r.status_code != 200 or not r.text:
                continue
        except httpx.HTTPError:
            continue
        out: list[dict] = []
        # <a class="result__a" href="...">title</a> — class usually precedes
        # href; try both orders before giving up on this endpoint.
        for pat in (
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            r'<a[^>]+href="([^"]+)"[^>]+class="result__a"[^>]*>(.*?)</a>',
        ):
            for m in re.finditer(pat, r.text, re.DOTALL):
                href = _unwrap_ddg(m.group(1))
                title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
                if href.startswith("http"):
                    out.append({"title": title, "url": href})
            if out:
                return out[:limit]
    return []
