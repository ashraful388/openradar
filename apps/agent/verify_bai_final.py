"""Confirm b.ai data is correct."""
import json
from pathlib import Path

s = json.loads(Path("data/snapshot.json").read_text(encoding="utf-8"))
bai = [m for m in s["models"] if m["provider_id"] == "p_bai"]
free_bai = [m for m in bai if m["is_free"]]
paid_bai = [m for m in bai if not m["is_free"]]
print(f"b.ai rows: {len(bai)}  free: {len(free_bai)}  paid: {len(paid_bai)}")
mimo = next((m for m in bai if m["model_id"] == "MiMo-V2.5"), None)
print(f"MiMo-V2.5 is free? {mimo and mimo['is_free']}  in=${mimo and mimo.get('input_per_1m')}/M")
sol = next((m for m in bai if m["model_id"] == "GPT-5.6-Sol"), None)
print(f"GPT-5.6-Sol is free? {sol and sol['is_free']}  in=${sol and sol.get('input_per_1m')}/M  out=${sol and sol.get('output_per_1m')}/M")
