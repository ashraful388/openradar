"""Server-side store for LLM verifier provider credentials.

The web Settings → Intelligence panel writes a JSON file at
`data/.verifier-secrets.json` (gitignored). The agent reads it at run
time. The file lives outside the public config.json on purpose — it
carries the user's API keys and must never be committed.

File shape:
    {
      "providers": [
        {
          "name": "openai-main",
          "base_url": "https://api.openai.com/v1/chat/completions",
          "api_format": "openai",          # openai | anthropic | custom
          "api_key": "sk-...",
          "models": [
            {"name": "gpt-4o-mini", "model_id": "gpt-4o-mini"},
            ...
          ]
        },
        ...
      ]
    }
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any


def _secrets_path() -> Path:
    p = Path(os.environ.get("OPENRADAR_DATA", Path(__file__).resolve().parents[3] / "data")) / ".verifier-secrets.json"
    return p


def load() -> dict[str, Any]:
    """Return the full secrets file. Empty default if missing/corrupt."""
    f = _secrets_path()
    if not f.exists():
        return {"providers": []}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"providers": []}


def get_provider(name: str) -> dict[str, Any] | None:
    """Find a provider card by name (case-insensitive). Returns the raw
    dict including api_key — this is the agent side, it needs the key."""
    if not name:
        return None
    target = name.strip().lower()
    for p in load().get("providers", []):
        if (p.get("name") or "").strip().lower() == target:
            return p
    return None


def save(providers: list[dict[str, Any]]) -> Path:
    """Replace the secrets file with the given providers list. Used by
    the web form's POST handler. Not called from the agent at runtime —
    only by the web route."""
    f = _secrets_path()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"providers": providers}, indent=2), encoding="utf-8")
    return f
