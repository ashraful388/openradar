"""Probe the b.ai page for the actual pricing data structure."""
import httpx
import re

r = httpx.get("https://chat.b.ai/key", timeout=15, follow_redirects=True,
              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
text = r.text

# Look for model id-like keys
ids = set(re.findall(r'"(?:deepseek|claude|gpt|qwen|gemini|kimi|minimax|mimo|hunyuan|glm|tencent|xiaomi|anthropic|moonshot)[a-z0-9\-.]*"', text, re.IGNORECASE))
print("=== model id-like keys (first 60) ===")
for i in sorted(ids)[:60]:
    print("  ", i)

# Try to find a model list pattern - look for arrays of {id, displayName, abilities, pricing}
print()
print("=== pricing block samples (around 'input' fields) ===")
count = 0
for m in re.finditer(r'"input"\s*:\s*[\d.]+', text):
    snippet = text[max(0, m.start()-150):m.end()+250]
    print("---")
    print(snippet[:400])
    count += 1
    if count > 8:
        break
