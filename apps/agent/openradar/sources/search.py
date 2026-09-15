"""Search-API discovery.

Tries Brave first, then Tavily, then Exa — all of which have free tiers.
Reads the API key from the corresponding env var; if none is set, returns
empty results and the agent moves on (graceful degradation)."""
from __future__ import annotations
import os
import httpx


def search_new_free_apis(query: str = "new free LLM API 2026 site launch", limit: int = 10) -> list[dict]:
    if key := os.environ.get("BRAVE_SEARCH_API_KEY"):
        return _brave(query, key, limit)
    if key := os.environ.get("TAVILY_API_KEY"):
        return _tavily(query, key, limit)
    if key := os.environ.get("EXA_API_KEY"):
        return _exa(query, key, limit)
    return []


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
