"""Quick diagnostic of the current snapshot."""
import json
from pathlib import Path

snap = json.loads(Path("data/snapshot.json").read_text(encoding="utf-8"))
print(f"providers: {len(snap['providers'])}")
print(f"models: {len(snap['models'])}")
print(f"free: {sum(1 for m in snap['models'] if m['is_free'])}")
print(f"b.ai in catalog: {any(p['id'] == 'p_bai' for p in snap['providers'])}")
or_p = next(p for p in snap['providers'] if p['id'] == 'p_openrouter')
hf_p = next(p for p in snap['providers'] if p['id'] == 'p_hf')
print(f"openrouter free_model_count: {or_p['free_model_count']}")
print(f"huggingface free_model_count: {hf_p['free_model_count']}")
print()
print("--- b.ai provider record ---")
bai = next((p for p in snap['providers'] if p['id'] == 'p_bai'), None)
if bai:
    for k in ('name', 'slug', 'api_base', 'openai_compatible', 'free_model_count', 'tagline'):
        print(f"  {k}: {bai.get(k)}")
print()
print("--- changelog (last 10) ---")
for c in snap['changelog'][-10:]:
    print(f"  [{c['kind']}] {c['text'][:100]}")
