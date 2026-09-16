"""Provider submissions filed as GitHub issues by the deployed site.

The public OpenRadar deployment runs on Vercel, whose filesystem is
read-only — the Submit form cannot append to data/submissions.jsonl
there. Instead the form's API route opens an issue labeled
`provider-submission` in the repo; the discovery agent ingests the open
issues each run (changelog entry + candidate promotion when the
submitted endpoint probes as OpenAI-compatible), then closes them so
nothing is processed twice.

Local runs without a token can't close issues, so processed issue
numbers are tracked in data/.issues-state.json (gitignored) instead.
"""
from __future__ import annotations
import json
import os
import re
from pathlib import Path

import httpx

LABEL = "provider-submission"
STATE_FILE = ".issues-state.json"

_FENCE_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _headers(token: str | None) -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "openradar-agent",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def fetch_open(repo: str, token: str | None, timeout: float = 15.0) -> list[dict]:
    """Open issues labeled provider-submission. PRs are filtered out.
    Raises on HTTP errors — the caller decides whether that's fatal."""
    url = f"https://api.github.com/repos/{repo}/issues"
    r = httpx.get(
        url,
        params={"labels": LABEL, "state": "open", "per_page": 50},
        headers=_headers(token),
        timeout=timeout,
    )
    r.raise_for_status()
    return [i for i in r.json() if "pull_request" not in i]


def parse_body(body: str | None) -> dict:
    """Extract the submission payload the API route fenced into the body.
    Falls back to `key: value` lines for hand-filed issues."""
    if not body:
        return {}
    m = _FENCE_RE.search(body)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    out: dict[str, str] = {}
    for line in body.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip().strip("-* ").lower().replace(" ", "_")
            v = v.strip()
            if k and v and not k.startswith("```"):
                out[k] = v
    return out


def close(repo: str, number: int, token: str, comment: str) -> bool:
    """Comment + close an ingested submission issue. Best-effort: returns
    False on any failure so the run never dies over bookkeeping."""
    if not token:
        return False
    base = f"https://api.github.com/repos/{repo}/issues/{number}"
    try:
        httpx.post(
            f"{base}/comments",
            json={"body": comment},
            headers=_headers(token),
            timeout=15.0,
        ).raise_for_status()
        httpx.patch(
            base,
            json={"state": "closed", "state_reason": "completed"},
            headers=_headers(token),
            timeout=15.0,
        ).raise_for_status()
        return True
    except httpx.HTTPError:
        return False


def _state_path() -> Path:
    p = Path(os.environ.get("OPENRADAR_DATA", Path(__file__).resolve().parents[3] / "data"))
    return p / STATE_FILE


def load_processed() -> set[int]:
    f = _state_path()
    if not f.exists():
        return set()
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return {int(n) for n in data.get("processed_issues", [])}
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        return set()


def save_processed(numbers: set[int]) -> None:
    f = _state_path()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"processed_issues": sorted(numbers)}), encoding="utf-8")
