"""Verify the b.ai fixes and new UI are present in the rendered pages."""
import json
import urllib.request
from pathlib import Path

snap = json.loads(Path("data/snapshot.json").read_text(encoding="utf-8"))
bai_detail = urllib.request.urlopen("http://127.0.0.1:3000/providers/bai", timeout=30).read().decode("utf-8", errors="ignore")
models_page = urllib.request.urlopen("http://127.0.0.1:3000/models", timeout=30).read().decode("utf-8", errors="ignore")
flagships_page = urllib.request.urlopen("http://127.0.0.1:3000/cheap-flagships", timeout=30).read().decode("utf-8", errors="ignore")
home = urllib.request.urlopen("http://127.0.0.1:3000/", timeout=30).read().decode("utf-8", errors="ignore")

print("=== Snapshot integrity ===")
gpt56sol = next((m for m in snap["models"] if m["model_id"] == "GPT-5.6-Sol"), None)
if gpt56sol:
    print(f"  GPT-5.6 Sol:  is_free={gpt56sol['is_free']}  in=${gpt56sol.get('input_per_1m')}/M  out=${gpt56sol.get('output_per_1m')}/M")
wrong = [m for m in snap["models"] if m["is_free"] and ((m.get('input_per_1m') or 0) > 0 or (m.get('output_per_1m') or 0) > 0)]
print(f"  Models marked free with non-zero pricing: {len(wrong)} (expected 0)")

print()
print("=== /providers/bai ===")
checks = ["All models on this provider", "GPT-5.6-Sol", "MiMo-V2.5", "Claude-Opus-5", "$4.000", "$20.000", "$0.000", "b.ai $0/M verified"]
for c in checks:
    print(f"  {c:30s}  count={bai_detail.count(c)}")

print()
print("=== /models ===")
checks = ["search model id", "section-link", "section-header", "modality-pill", "all providers", "Free models", "col-check"]
for c in checks:
    print(f"  {c:30s}  count={models_page.count(c)}")

print()
print("=== /cheap-flagships ===")
checks = ["search flagships", "of", "PaddleOCR", "GPT-5.6", "MiMo"]
for c in checks:
    print(f"  {c:30s}  count={flagships_page.count(c)}")

print()
print("=== Home ===")
checks = ["API Providers", "search providers", "all regions", "all signup types", "Home", "b.ai", "API Providers</a>"]
for c in checks:
    print(f"  {c:30s}  count={home.count(c)}")
