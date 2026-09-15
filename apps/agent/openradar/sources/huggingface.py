"""Hugging Face Inference Providers.

Hugging Face exposes a router at https://router.huggingface.co/v1 that
speaks the OpenAI protocol. The /v1/models endpoint returns every model
that has at least one serverless provider attached, with per-provider
pricing, context length, and a `providers` array that tells us who can
serve it (cerebras, groq, together, replicate, etc.). Free-tier
inference is available on many of them, throttled but real.

No auth is required to list, but we send a token if HF_TOKEN is set
because the free-tier inference is gated behind a token at request
time."""
from __future__ import annotations
import os
import httpx

URL = "https://router.huggingface.co/v1/models"


def fetch(timeout: float = 30.0) -> list[dict]:
    headers = {}
    if tok := os.environ.get("HF_TOKEN"):
        headers["Authorization"] = f"Bearer {tok}"
    r = httpx.get(URL, headers=headers, timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    return r.json().get("data", [])


def context_window(model: dict) -> int | None:
    try:
        n = model.get("max_context_length") or model.get("context_length")
        return int(n) if n else None
    except (TypeError, ValueError):
        return None


def is_free_via_provider(model: dict) -> bool:
    """HF marks a model as free-eligible when at least one of its providers
    has `price` of 0 and the model is in the free inference tier. We
    approximate by checking any of the attached providers."""
    for prov in model.get("providers") or []:
        raw = prov.get("price", None)
        if raw is None:
            continue
        try:
            if float(raw) == 0:
                return True
        except (TypeError, ValueError):
            continue
    return False
