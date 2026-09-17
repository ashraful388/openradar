"""OpenRouter source.

Pulls the public models listing (https://openrouter.ai/api/v1/models) and
returns every entry whose `id` ends with `:free` — these are the providers'
own free variants surfaced through OpenRouter's router. We use the listing
to:
  1. Reap provider hosts (the part of the id before the `/` is the upstream
     provider, e.g. `meta-llama/...` or `deepseek/...`).
  2. Add each :free model as a row in our snapshot, linked to the upstream
     provider (creating a provider entry if needed).

The endpoint is public; no key required."""
from __future__ import annotations
import re
import httpx

URL = "https://openrouter.ai/api/v1/models"


def fetch(timeout: float = 30.0) -> list[dict]:
    r = httpx.get(URL, timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    return r.json().get("data", [])


def is_free(model: dict) -> bool:
    """Heuristic: id ends with :free, or pricing.prompt/completion is exactly 0."""
    mid = str(model.get("id", ""))
    if mid.endswith(":free"):
        return True
    pricing = model.get("pricing") or {}
    try:
        prompt = parse_price(pricing.get("prompt"))
        comp = parse_price(pricing.get("completion"))
    except (TypeError, ValueError):
        return False
    if prompt is None or comp is None:
        return False
    return prompt == 0 and comp == 0


def upstream(model: dict) -> str:
    """Best-effort upstream provider name. Falls back to the id prefix."""
    mid = str(model.get("id", ""))
    if "/" in mid:
        return mid.split("/", 1)[0]
    return str(model.get("name", mid)).split(" ", 1)[0]


def context_window(model: dict) -> int | None:
    n = model.get("context_length") or model.get("top_provider", {}).get("context_length")
    try:
        return int(n) if n else None
    except (TypeError, ValueError):
        return None


_PRICE_RE = re.compile(r"[-+]?\d*\.?\d+")


def parse_price(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    m = _PRICE_RE.match(s)
    if not m:
        return None
    try:
        # OpenRouter publishes $/token as a string; normalize to $/1M.
        per_token = float(m.group(0))
        return per_token * 1_000_000
    except ValueError:
        return None
