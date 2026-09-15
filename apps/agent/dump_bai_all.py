"""All b.ai rows in current snapshot."""
import json
from pathlib import Path

s = json.loads(Path("data/snapshot.json").read_text(encoding="utf-8"))
bai_models = [m for m in s["models"] if m["provider_id"] == "p_bai"]
print(f"total b.ai rows: {len(bai_models)}")
for m in bai_models:
    print(f"  {m['model_id']:30s}  is_free={m['is_free']!s:5s}  in=${m.get('input_per_1m')}/M  out=${m.get('output_per_1m')}/M")
