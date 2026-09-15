"""Show b.ai free vs paid split."""
import json
from pathlib import Path

s = json.loads(Path("data/snapshot.json").read_text(encoding="utf-8"))
print("=== b.ai free models ===")
for m in s["models"]:
    if m["provider_id"] == "p_bai" and m["is_free"]:
        print(f"  free  {m['display_name']:30s}  in=${m.get('input_per_1m')}/M  out=${m.get('output_per_1m')}/M")
print()
print("=== b.ai paid models (sample) ===")
n = 0
for m in s["models"]:
    if m["provider_id"] == "p_bai" and not m["is_free"]:
        print(f"  paid  {m['display_name']:30s}  in=${m.get('input_per_1m')}/M  out=${m.get('output_per_1m')}/M")
        n += 1
        if n >= 8:
            break
print()
print("=== summary by provider ===")
counts = {}
for m in s["models"]:
    if m["is_free"]:
        counts[m["provider_id"]] = counts.get(m["provider_id"], 0) + 1
prov_by_id = {p["id"]: p for p in s["providers"]}
for pid, n in sorted(counts.items(), key=lambda x: -x[1])[:12]:
    p = prov_by_id.get(pid, {})
    print(f"  {n:3d}  {pid:25s}  {p.get('name', pid)}")
