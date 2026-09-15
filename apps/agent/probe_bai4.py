"""Debug: what does the structure look like exactly."""
import httpx, re
r = httpx.get("https://chat.b.ai/key", timeout=15, follow_redirects=True,
              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
text = r.text
# Find a known id and dump the surrounding structure
i = text.find('deepseek-v4-pro')
print("text[max(0,i-50):i+200]:")
print(text[max(0,i-50):i+200])
print()
# Look at every place "id":"<something>-pro" appears
print("all matches of 'id\":\"<...>-pro':")
for m in list(re.finditer(r'"id":"([a-z0-9\-]+-pro)"', text))[:5]:
    print(m.group(0))
    print("  context:", text[max(0, m.start()-30):m.end()+200])
    print("---")
