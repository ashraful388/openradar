"""Quick check of the new cheap-flagships leaderboard."""
import json
from pathlib import Path

snap = json.loads(Path("data/snapshot.json").read_text(encoding="utf-8"))
print(f"Total flagships: {len(snap['cheap_flagships'])}")
print()
print("=== Top 25 ===")
for f in snap["cheap_flagships"][:25]:
    ctx = f.get("context_window") or "—"
    print(f"  #{f['rank']:2d}  {f['display_name']:32s}  ${f['input_per_1m']:6.3f} in / ${f['output_per_1m']:6.3f} out  ({f['provider']})")
print()
print("=== Flagships from b.ai's catalog ===")
bai_flagships = [f for f in snap["cheap_flagships"] if "b.ai" in f.get("provider", "").lower() or "b-ai" in f.get("model_id", "").lower()]
print(f"  count: {len(bai_flagships)}")
for f in bai_flagships[:20]:
    print(f"  #{f['rank']:2d}  {f['display_name']:32s}  ${f['input_per_1m']:6.3f} in / ${f['output_per_1m']:6.3f} out  ({f['provider']})")
print()
print("=== Free model count by provider (top 12) ===")
counts = {}
for m in snap["models"]:
    if m["is_free"]:
        counts[m["provider_id"]] = counts.get(m["provider_id"], 0) + 1
prov_by_id = {p["id"]: p for p in snap["providers"]}
for pid, n in sorted(counts.items(), key=lambda x: -x[1])[:12]:
    p = prov_by_id.get(pid, {})
    print(f"  {n:4d}  {pid:25s}  {p.get('name', pid)}")
