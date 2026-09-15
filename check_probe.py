import json
data = json.load(open('C:/Users/Dr. Ashraful Babu/Documents/OpenRadar-update/data/snapshot.json'))
for p in data['providers']:
    if p['slug'] in ['zai', 'google-ai-studio', 'qwen-bailian', 'siliconflow', 'cohere', 'bai']:
        print(f'{p["slug"]}: probe_status={p["probe_status"]}, status={p["status"]}')