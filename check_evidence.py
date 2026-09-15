import json
data = json.load(open('C:/Users/Dr. Ashraful Babu/Documents/OpenRadar-update/data/snapshot.json'))
free_models = [m for m in data['models'] if m['is_free']]
with_source = [m for m in free_models if m.get('free_evidence_source')]
print(f"Models with source: {len(with_source)}")
for m in with_source[:10]:
    print(f"  {m['provider_id']}: {m['model_id']} - source={m.get('free_evidence_source')}, verified={m.get('free_verified_at')}")

# Also check declared source
declared = [m for m in free_models if m.get('free_evidence_source') == 'declared']
print(f"\nDeclared: {len(declared)}")
for m in declared[:10]:
    print(f"  {m['provider_id']}: {m['model_id']} - source={m.get('free_evidence_source')}, verified={m.get('free_verified_at')}")

# Check models with no source
none = [m for m in free_models if not m.get('free_evidence_source')]
print(f"\nNone: {len(none)}")
for m in none[:10]:
    print(f"  {m['provider_id']}: {m['model_id']} - free_kind={m.get('free_kind')}, verified={m.get('free_verified_at')}")