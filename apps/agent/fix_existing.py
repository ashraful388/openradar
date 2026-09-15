"""One-shot fixup: any model currently marked is_free=True that carries
non-zero pricing is wrong (GPT-5.6 Sol and 22 friends). Reset them."""
import json
from pathlib import Path

snap_path = Path("data/snapshot.json")
snap = json.loads(snap_path.read_text(encoding="utf-8"))
fixed = 0
for m in snap["models"]:
    inp = m.get("input_per_1m") or 0
    out = m.get("output_per_1m") or 0
    if m["is_free"] and (inp > 0 or out > 0):
        m["is_free"] = False
        if m.get("free_kind") in ("free_tier", "free_credits", "promo"):
            m["free_kind"] = "byok_required"
        m["free_limit"] = m.get("free_limit") or "via b.ai"
        fixed += 1
# Recompute free_model_count for every provider.
prov_by_id = {p["id"]: p for p in snap["providers"]}
for p in snap["providers"]:
    p["free_model_count"] = sum(1 for m in snap["models"] if m["provider_id"] == p["id"] and m["is_free"])

snap_path.write_text(json.dumps(snap, indent=2), encoding="utf-8")
print(f"fixed {fixed} rows")
print("free_model_count per provider after fix:")
counts = {}
for m in snap["models"]:
    if m["is_free"]:
        counts[m["provider_id"]] = counts.get(m["provider_id"], 0) + 1
for pid, n in sorted(counts.items(), key=lambda x: -x[1]):
    p = prov_by_id.get(pid, {})
    print(f"  {n:3d}  {pid:25s}  {p.get('name', pid)}")
