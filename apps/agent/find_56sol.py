"""Find GPT-5.6 Sol in the snapshot."""
import json
from pathlib import Path

snap = json.loads(Path("data/snapshot.json").read_text(encoding="utf-8"))
print("--- All '5.6' / 'Sol' / 'GPT-5.6' models ---")
for m in snap["models"]:
    blob = (m["model_id"] + " " + m["display_name"]).lower()
    if "5.6" in blob or "5-6" in blob or " sol" in blob:
        print(f"  prov={m['provider_id']:18s}  id={m['model_id']:35s}  display={m['display_name']:30s}  is_free={m['is_free']!s:5s}  in=${m.get('input_per_1m')}  out=${m.get('output_per_1m')}")
print()
print("--- all models with is_free=True that have non-zero input_per_1m or output_per_1m (BUG) ---")
for m in snap["models"]:
    inp = m.get("input_per_1m") or 0
    out = m.get("output_per_1m") or 0
    if m["is_free"] and (inp > 0 or out > 0):
        print(f"  prov={m['provider_id']:18s}  id={m['model_id']:35s}  in=${inp}  out=${out}")
