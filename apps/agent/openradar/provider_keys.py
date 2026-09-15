"""Server-side store for provider API keys (BYOK credentials).

Provider free tiers are only visible through an authenticated
/v1/models, so the operator needs a way to hand the agent one key per
provider. Keys can come from two places, in order:

  1. environment variables (repo secrets / Vercel env / shell), named
     after the provider's api_key_env (GROQ_API_KEY, ...);
  2. `data/.provider-keys.json` — written by the web Settings →
     Provider API keys panel (gitignored; carries secrets, never
     committed, never written to the public config.json).

File shape:
    {"keys": {"GROQ_API_KEY": "gsk_...", "BAI_API_KEY": "..."}}

Env vars win: they're the CI/Vercel deployment path, and the file is
the local-dev convenience.
"""
from __future__ import annotations
import json
import os
from pathlib import Path


def _keys_path() -> Path:
    p = Path(os.environ.get("OPENRADAR_DATA", Path(__file__).resolve().parents[3] / "data"))
    return p / ".provider-keys.json"


def _file_keys() -> dict[str, str]:
    f = _keys_path()
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    keys = data.get("keys", {}) if isinstance(data, dict) else {}
    return {k: v for k, v in keys.items() if isinstance(k, str) and isinstance(v, str)}


def get(env_name: str | None) -> str | None:
    """Resolve a provider credential by its env-var name: environment
    first, then the Settings-written key file. None = not configured."""
    if not env_name:
        return None
    token = os.environ.get(env_name)
    if token:
        return token
    return _file_keys().get(env_name) or None
