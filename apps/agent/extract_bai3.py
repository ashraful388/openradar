"""Show a 2000-char slice around deepseek-v4-pro so we can see the actual structure."""
import httpx
r = httpx.get("https://chat.b.ai/key", timeout=15, follow_redirects=True,
              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
text = r.text
i = text.find('deepseek-v4-pro')
print(text[max(0,i-300):i+1500])
