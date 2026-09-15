import json
data = json.load(open('C:/Users/Dr. Ashraful Babu/Documents/OpenRadar-update/data/snapshot.json'))
for c in data['changelog'][-30:]:
    print(f'{c["kind"]}: {c["text"]}')