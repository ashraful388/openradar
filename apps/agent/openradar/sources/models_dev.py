"""models.dev source.

Public, no-auth JSON at https://models.dev/api.json. Structure is:
  { "<provider_id>": { "name": ..., "models": { "<model_id>": { ... } } } }

This is the source of truth for pricing and capabilities. We use it to:
  1. Backfill `last_verified`, `context_window`, and pricing for any
     provider/model we already know about.
  2. Build the cheap-flagships leaderboard (frontier models with a
     published $/M-in and $/M-out).

The full provider list from models.dev is also used as a candidate-pool
during discovery."""
from __future__ import annotations
import httpx

URL = "https://models.dev/api.json"


def fetch(timeout: float = 30.0) -> dict:
    r = httpx.get(URL, timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    return r.json()


def is_cheap_flagship(model: dict) -> bool:
    """A model is a 'cheap flagship' candidate if:
      - it has a published USD pricing for both input and output tokens, and
      - the combined cost is below a threshold (we use $20/M-out as a
        generous ceiling, since Claude Sonnet 4.5 is around there), and
      - it has at least one of: tool calling, structured output, or vision
        (real flagship capability signal)."""
    cost = model.get("cost") or {}
    try:
        inp = float(cost.get("input") or 0)
        out = float(cost.get("output") or 0)
    except (TypeError, ValueError):
        return False
    if inp == 0 or out == 0:
        return False  # not a paid flagship
    if out > 20.0:
        return False  # too expensive for the leaderboard
    caps = []
    for m in (model.get("modalities") or {}).values():
        if isinstance(m, list):
            caps.extend(m)
    tools = model.get("tool_call") or False
    if not (tools or "image" in caps or "file" in caps or "audio" in caps):
        return False
    return True
