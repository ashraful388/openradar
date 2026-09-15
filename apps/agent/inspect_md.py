"""Inspect models.dev for things that could falsely match b.ai's models."""
import json
import httpx

r = httpx.get("https://models.dev/api.json", timeout=30,
              headers={"User-Agent": "openradar/0.1 (https://github.com/openradar)"},
              follow_redirects=True)
r.raise_for_status()
md = r.json()
matches = 0
for pid, prov in md.items():
    for mid, mdl in (prov.get("models") or {}).items():
        cost = (mdl or {}).get("cost") or {}
        try:
            inp = float(cost.get("input") or 0)
            out = float(cost.get("output") or 0)
        except (TypeError, ValueError):
            continue
        if inp == 0 and out == 0:
            if any(t in mid.lower() for t in ("gpt-5", "opus", "mimo", "kimi", "glm", "qwen3", "gemini", "minimax")):
                print(f"  {pid:30s}  {mid:35s}  cost=0/0  <-- could match b.ai's paid model of same id")
                matches += 1
print(f"total potentially-conflicting matches: {matches}")
