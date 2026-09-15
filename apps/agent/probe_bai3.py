"""Probe the b.ai page: look for the specific pricing values from the screenshots."""
import httpx
import re

r = httpx.get("https://chat.b.ai/key", timeout=15, follow_redirects=True,
              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
text = r.text
print("len:", len(text))
print()

# Look for "1.32" (DeepSeek-V4-Pro input) and "3.96" (output)
print("--- looking for 1.32 ---")
for m in list(re.finditer(r"1\.32", text))[:5]:
    print(text[max(0, m.start()-200):m.end()+200])
    print("===")
