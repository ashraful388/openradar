import json
data = json.load(open('C:/Users/Dr. Ashraful Babu/Documents/OpenRadar-update/data/snapshot.json'))

# Check Z.ai models
zai_models = [m for m in data['models'] if m['provider_id'] == 'p_zai']
print(f"Z.ai models: {len(zai_models)}")
for m in zai_models:
    free = "FREE" if m['is_free'] else "paid"
    print(f"  {m['model_id']}: {free}, free_kind={m['free_kind']}, source={m.get('free_evidence_source')}, verified={m.get('free_verified_at')}")

print()
# Check Google models
google_models = [m for m in data['models'] if m['provider_id'] == 'p_google']
print(f"Google models: {len(google_models)}")
free_google = [m for m in google_models if m['is_free']]
print(f"  Free: {len(free_google)}")
for m in free_google:
    print(f"  {m['model_id']}: free_kind={m['free_kind']}, source={m.get('free_evidence_source')}, verified={m.get('free_verified_at')}")

print()
# Check Qwen models
qwen_models = [m for m in data['models'] if m['provider_id'] == 'p_qwen']
print(f"Qwen models: {len(qwen_models)}")
free_qwen = [m for m in qwen_models if m['is_free']]
print(f"  Free: {len(free_qwen)}")
for m in free_qwen:
    print(f"  {m['model_id']}: free_kind={m['free_kind']}, source={m.get('free_evidence_source')}, verified={m.get('free_verified_at')}")

print()
# Check b.ai models - should be on p_bai only
bai_models = [m for m in data['models'] if m['provider_id'] == 'p_bai']
print(f"b.ai models: {len(bai_models)}")
free_bai = [m for m in bai_models if m['is_free']]
print(f"  Free: {len(free_bai)}")
for m in free_bai[:10]:
    print(f"  {m['model_id']}: free_kind={m['free_kind']}, source={m.get('free_evidence_source')}, verified={m.get('free_verified_at')}")

# Check if any b.ai models leaked to upstream
print("\nChecking for b.ai models on upstream providers...")
upstream_bai = [m for m in data['models'] if m['provider_id'] != 'p_bai' and 'b.ai' in (m.get('free_limit') or '').lower()]
print(f"Models with b.ai in free_limit on non-b.ai providers: {len(upstream_bai)}")
for m in upstream_bai[:10]:
    print(f"  {m['provider_id']}: {m['model_id']} - free_limit={m.get('free_limit')[:80]}")