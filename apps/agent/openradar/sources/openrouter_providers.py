"""OpenRouter provider-directory discovery.

https://openrouter.ai/providers lists every upstream provider routed
through OpenRouter, with per-provider model counts and — the useful
part — how many of those models are free. A provider advertising free
models there is a strong discovery signal: either it has its own API
we should catalog, or its models are at least reachable through
OpenRouter.

The page is a Next.js app; the provider cards arrive embedded in the
RSC flight payload (self.__next_f.push chunks). Parsing is tolerant:
any failure returns an empty list and the caller logs a soft note."""
from __future__ import annotations
import json
import re

import httpx

URL = "https://openrouter.ai/providers"

_CARD_NAME = re.compile(r'"name":"([^"]+)","slug":"([^"]+)","displayName"')


def fetch(timeout: float = 25.0) -> list[dict]:
    """Return [{name, slug, free, models}] for every provider card."""
    r = httpx.get(URL, timeout=timeout, follow_redirects=True,
                  headers={"User-Agent": "Mozilla/5.0 (OpenRadar discovery)"})
    r.raise_for_status()
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', r.text, re.S)
    joined = "".join(c.encode().decode("unicode_escape", errors="ignore") for c in chunks)
    # Card order is consistent: find each slug, then the next
    # freeModelCount/modelCount pair within the same object window.
    cards: dict[str, dict] = {}
    for m in _CARD_NAME.finditer(joined):
        name, slug = m.group(1), m.group(2)
        window = joined[m.start():m.start() + 1200]
        free = _int(window, "freeModelCount")
        models = _int(window, "modelCount")
        cards.setdefault(slug, {"name": name, "slug": slug,
                                "free": free, "models": models})
    return list(cards.values())


def _int(window: str, key: str) -> int:
    m = re.search(rf'"{key}":(\d+)', window)
    return int(m.group(1)) if m else 0


def match_known(slug: str, name: str, providers) -> bool:
    """True if an existing provider row already covers this card.

    Conservative token match: OpenRouter's 'nvidia' must match our
    'NVIDIA NIM' (p_nvidia), 'google-ai-studio' our 'Google AI Studio
    (Gemini)'. Normalized substring on both slug and name."""
    tokens = re.sub(r"[^a-z0-9]", "", slug.lower())
    name_norm = re.sub(r"[^a-z0-9]", "", name.lower())
    if not tokens:
        return True
    for p in providers:
        hay_slug = re.sub(r"[^a-z0-9]", "", (p.slug or "").lower())
        hay_id = re.sub(r"[^a-z0-9]", "", (p.id or "").lower())
        hay_name = re.sub(r"[^a-z0-9]", "", (p.name or "").lower())
        if (tokens in hay_slug or tokens in hay_id or tokens in hay_name
                or (len(name_norm) >= 4 and
                    (name_norm in hay_name or hay_name in name_norm))):
            return True
    return False
