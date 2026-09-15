"""Get raw HTML of chat.b.ai/key to see structure."""
import httpx

r = httpx.get("https://chat.b.ai/key", timeout=15, follow_redirects=True,
              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"})
print("status:", r.status_code, "len:", len(r.text))
print("first 500:")
print(r.text[:500])
print()
print("looking for 'gift' or 'free' in HTML:")
import re
for m in re.finditer(r".{0,80}(gift|free|model).{0,80}", r.text, re.IGNORECASE):
    print("  ", m.group(0)[:200])
