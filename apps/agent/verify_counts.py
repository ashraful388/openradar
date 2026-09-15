"""Confirm free_model_count in the snapshot matches the actual rows."""
import json
from pathlib import Path

snap = json.loads(Path("data/snapshot.json").read_text(encoding="utf-8"))
or_p = next(p for p in snap["providers"] if p["id"] == "p_openrouter")
hf_p = next(p for p in snap["providers"] if p["id"] == "p_hf")
bai_p = next(p for p in snap["providers"] if p["id"] == "p_bai")

actual_or = sum(1 for m in snap["models"] if m["provider_id"] == "p_openrouter" and m["is_free"])
actual_hf = sum(1 for m in snap["models"] if m["provider_id"] == "p_hf" and m["is_free"])
print(f"openrouter card: {or_p['free_model_count']}  (actual rows: {actual_or})  match={or_p['free_model_count'] == actual_or}")
print(f"huggingface card: {hf_p['free_model_count']}  (actual rows: {actual_hf})  match={hf_p['free_model_count'] == actual_hf}")
print(f"b.ai: {bai_p['name']}  api_base={bai_p['api_base']}  openai_compatible={bai_p['openai_compatible']}  free_model_count={bai_p['free_model_count']}")
