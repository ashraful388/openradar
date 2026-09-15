"""Poll an OpenAI-compatible /v1/models endpoint and report what's there."""
from __future__ import annotations
import httpx
from ..models import Provider, Model, now


def list_models(base_url: str, api_key: str | None = None, timeout: float = 15.0) -> list[dict]:
    """Returns the raw model objects as the provider returns them. Empty list on failure."""
    url = base_url.rstrip("/") + "/models"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        r = httpx.get(url, headers=headers, timeout=timeout)
    except httpx.HTTPError:
        return []
    if r.status_code >= 400:
        return []
    # Some providers return HTML (login pages, 404s with a body) instead of JSON.
    ctype = r.headers.get("content-type", "")
    if "json" not in ctype.lower():
        return []
    try:
        data = r.json()
    except Exception:
        return []
    return data.get("data", data) if isinstance(data, dict) else data


def fetch_models(base_url: str, api_key: str | None = None,
                 timeout: float = 15.0) -> tuple[str, list[dict]]:
    """Like list_models but reports WHY a fetch came back empty.

    Returns (status, rows):
      "ok"        — 200 + JSON payload (rows may still be empty)
      "needs_key" — 401/403 (or an HTML login page) and no key was sent;
                    the model list exists but is behind a login
      "gated"     — 401/403 even though a key was sent (key rejected,
                    expired, or lacking scope)
      "error"     — network failure, 5xx, or a non-JSON 200 body that
                    isn't a login page
    """
    url = base_url.rstrip("/") + "/models"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        r = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError:
        return "error", []
    if r.status_code in (401, 403):
        return ("needs_key", []) if api_key is None else ("gated", [])
    if r.status_code >= 400:
        return "error", []
    ctype = r.headers.get("content-type", "")
    if "json" not in ctype.lower():
        # HTML body on a 200 is usually an auth/login wall.
        text_start = r.text[:200].lower() if r.text else ""
        if "<html" in text_start or "sign in" in text_start or "login" in text_start:
            return ("needs_key", []) if api_key is None else ("gated", [])
        return "error", []
    try:
        data = r.json()
    except Exception:
        return "error", []
    rows = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return "error", []
    return "ok", rows


def verify_openai_compatible(base_url: str, timeout: float = 5.0) -> bool:
    """A provider is OpenAI-compatible if /v1/models returns 200 (or 401, which still proves the route)."""
    url = base_url.rstrip("/") + "/models"
    try:
        r = httpx.get(url, timeout=timeout)
    except httpx.HTTPError:
        return False
    return r.status_code in (200, 401)
