"""Show the b.ai free models (those routed to upstream providers)."""
import json
from pathlib import Path

s = json.loads(Path("data/snapshot.json").read_text(encoding="utf-8"))
print("=== b.ai catalog's truly free models — where did they land? ===")
expected = [
    ("DeepSeek", "DeepSeek-V4-Flash"),
    ("DeepSeek", "DeepSeek-V4-Flash-Vision-Exp"),
    ("Tencent", "Hy3"),
    ("Xiaomi", "MiMo-V2.5"),
    ("Z.ai", "GLM-5.3-Flash"),
    ("Alibaba", "Qwen3.8-Flash"),
]
for upstream, model in expected:
    matches = [m for m in s["models"] if m["model_id"].lower() == model.lower().replace(" ", "-").lower()]
    if not matches:
        print(f"  {model:30s}  NOT IN SNAPSHOT")
        continue
    for m in matches:
        p = next((p for p in s["providers"] if p["id"] == m["provider_id"]), None)
        print(f"  {upstream:10s} {model:30s} -> provider_id={m['provider_id']:20s}  is_free={m['is_free']!s:5s}  ({p['name'] if p else '?'})")
print()
print("=== deepseek p_deepseek free rows (should include V4-Flash) ===")
for m in s["models"]:
    if m["provider_id"] == "p_deepseek" and m["is_free"]:
        print(f"  {m['model_id']:30s}  display={m['display_name']}")
print()
print("=== p_zai free rows ===")
for m in s["models"]:
    if m["provider_id"] == "p_zai" and m["is_free"]:
        print(f"  {m['model_id']:30s}  display={m['display_name']}")
print()
print("=== p_qwen free rows ===")
for m in s["models"]:
    if m["provider_id"] == "p_qwen" and m["is_free"]:
        print(f"  {m['model_id']:30s}  display={m['display_name']}")
