import json
data = json.load(open('C:/Users/Dr. Ashraful Babu/Documents/OpenRadar-update/data/snapshot.json'))
for c in data['changelog']:
    if 'search' in c['text'].lower() or 'refresh' in c['text'].lower() or 'promoted' in c['text'].lower():
        print(f'{c["kind"]}: {c["text"]}')