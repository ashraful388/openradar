"""Probe docs.b.ai/llmservice/models/ for the model list."""
import httpx, re
r = httpx.get("https://docs.b.ai/llmservice/models/", timeout=15, follow_redirects=True,
              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
print("status:", r.status_code, "len:", len(r.text))
ids = set(re.findall(r'[\"\']([a-z0-9\-.]+)[\"\']', r.text))
hits = [i for i in ids if any(t in i for t in ("claude", "gpt", "qwen", "gemini", "kimi", "mimo", "glm", "minimax", "deepseek", "opus", "sonnet", "haiku"))]
print("hits:", sorted(hits)[:60])
