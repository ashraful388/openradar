"""Probe the b.ai page for the actual pricing data structure."""
import httpx
import re
import json

r = httpx.get("https://chat.b.ai/key", timeout=15, follow_redirects=True,
              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
text = r.text

# Look for model entries that include input/output prices
# The pattern in the RSC payload looks like "...input\":0,\"output\":0..."
for m in re.finditer(r'"(?:input|cacheWrite|cacheRead|output)":\s*[\d.]+', text):
    snippet = text[max(0, m.start()-200):m.end()+50]
    if "model" in snippet.lower() or "id" in snippet.lower():
        print("---")
        print(snippet[:300])

# Also look for the model id pattern
print("\n=== model id-like keys ===")
ids = set(re.findall(r'"(?:deepseek|claude|gpt|qwen|gemini|kimi|minimax|mimo|hunyuan|hy\d|glm|minimax|tencent|xiaomi|anthropic|moonshot|ali)[a-z0-9\-.]*"', text, re.IGNORECASE))
for i in sorted(ids)[:50]:
    print("  ", i)
