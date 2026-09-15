import json
data = json.load(open('C:/Users/Dr. Ashraful Babu/Documents/OpenRadar-update/data/snapshot.json'))
print(f"Providers: {len(data['providers'])}")
print(f"Models: {len(data['models'])}")
print(f"Credit providers: {len(data.get('credit_providers', []))}")