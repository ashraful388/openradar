"""Find every 'isMaintenance' instance and see what precedes it."""
import httpx, re
r = httpx.get("https://chat.b.ai/key", timeout=15, follow_redirects=True,
              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
text = r.text

# Find every "isMaintenance" and look backwards
matches = list(re.finditer(r'"isMaintenance":(true|false)', text))
print(f"found {len(matches)} isMaintenance tokens")
for m in matches[:3]:
    start = max(0, m.start() - 200)
    end = min(len(text), m.end() + 50)
    print("---")
    print(text[start:end])
