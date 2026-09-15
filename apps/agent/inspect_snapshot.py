"""Quick inspection helper for the latest snapshot."""
import json
from pathlib import Path

snap = json.loads(Path("data/snapshot.json").read_text(encoding="utf-8"))
prov_by_id = {p["id"]: p for p in snap["providers"]}

print(f"providers: {len(snap['providers'])}")
print(f"models: {len(snap['models'])}")
print(f"free: {sum(1 for m in snap['models'] if m['is_free'])}")
print(f"flagships: {len(snap['cheap_flagships'])}")
print(f"changelog: {len(snap['changelog'])}")
print()

print("=== Models per provider (top 15) ===")
counts = {}
for m in snap["models"]:
    counts[m["provider_id"]] = counts.get(m["provider_id"], 0) + 1
for pid, n in sorted(counts.items(), key=lambda x: -x[1])[:15]:
    p = prov_by_id.get(pid, {})
    print(f"  {n:5d}  {pid:30s}  {p.get('name', pid)}")

print()
print("=== Newly discovered providers (from this run) ===")
new = [c for c in snap["changelog"] if "auto-promoted" in c["text"]]
for c in new[:20]:
    print(f"  + {c['text']}")
if not new:
    print("  (none this run)")

print()
print("=== Free models per provider (top 10) ===")
free_counts = {}
for m in snap["models"]:
    if m["is_free"]:
        free_counts[m["provider_id"]] = free_counts.get(m["provider_id"], 0) + 1
for pid, n in sorted(free_counts.items(), key=lambda x: -x[1])[:10]:
    p = prov_by_id.get(pid, {})
    print(f"  {n:4d}  {pid:30s}  {p.get('name', pid)}")

print()
print("=== Top 10 cheap flagships (by composite cost) ===")
for f in snap["cheap_flagships"][:10]:
    print(f"  #{f['rank']:2d}  {f['display_name']:35s}  ${f['input_per_1m']:6.3f} in / ${f['output_per_1m']:6.3f} out  ({f['provider']})")
