"""Diagnose: which b.ai GPT-5.6 row landed as 'free' in the snapshot?"""
import json
from pathlib import Path

snap = json.loads(Path("data/snapshot.json").read_text(encoding="utf-8"))
# Find every b.ai model and report is_free + pricing.
print("=== All b.ai models in snapshot ===")
for m in snap["models"]:
    if m["provider_id"] in ("p_bai", "p_openai"):
        price = ""
        if m.get("input_per_1m") is not None:
            price = f" in=${m['input_per_1m']} out=${m['output_per_1m']}"
        print(f"  is_free={m['is_free']!s:5s} {m['model_id']:40s} {m['display_name']:30s}{price}")
print()
print("=== Static CATALOG truth (from bai.py) ===")
from openradar.sources.bai import CATALOG
for row in CATALOG:
    if "GPT" in row.get("family", "") or "OpenAI" in row.get("provider", ""):
        print(f"  family={row['family']:10s} model={row['model']:30s} in=${row['input']:6.3f} out=${row['output']:6.3f}")
