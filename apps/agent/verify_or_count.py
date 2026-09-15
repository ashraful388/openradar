"""Check the OR free count in the rendered page."""
import re
import urllib.request

t = urllib.request.urlopen("http://127.0.0.1:3000/providers/openrouter", timeout=30).read().decode("utf-8", errors="ignore")
m = re.search(r'"free_model_count":(\d+)', t)
print("free_model_count in stream:", m.group(0) if m else "not found")
print('"85" occurrences:', t.count('"85"'))
print('"free-count" className occurrences:', t.count('"free-count"'))
print('"85" + "free-count" within 500 chars:',
      any('"85"' in t[i:i+500] and 'free-count' in t[i:i+500]
          for i in range(0, len(t), 100)))
print('page size:', len(t))
