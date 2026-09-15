"""Xkiro source: a multi-model gateway whose /v1/models is fully public
and — unusually — self-describes each row's billing tier.

The payload carries fields most providers don't:
  access_tier: "free" | "premium" | "paid"
  pricing: {input, output} per 1M tokens (0/0 on free rows)
  capabilities / context_length / max_output_tokens

Free classification is therefore ground truth from the source itself:
access_tier == "free" OR pricing 0/0. No probe needed."""
from __future__ import annotations
import httpx

ENDPOINT = "https://xkiro.com/v1/models"


def fetch(timeout: float = 20.0) -> list[dict]:
    r = httpx.get(ENDPOINT, timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    data = r.json()
    rows = data.get("data", data) if isinstance(data, dict) else data
    return rows if isinstance(rows, list) else []


def is_free(row: dict) -> bool:
    if (row.get("access_tier") or "").lower() == "free":
        return True
    pr = row.get("pricing") or {}
    try:
        return float(pr.get("input")) == 0 and float(pr.get("output")) == 0
    except (TypeError, ValueError):
        return False


def is_paid(row: dict) -> bool:
    pr = row.get("pricing") or {}
    try:
        return float(pr.get("input")) > 0 or float(pr.get("output")) > 0
    except (TypeError, ValueError):
        return False


def context_window(row: dict) -> int | None:
    try:
        return int(row.get("context_length"))
    except (TypeError, ValueError):
        return None


def display_name(row: dict) -> str:
    return row.get("display_name") or row.get("id") or ""
