"""Find every 'isMaintenance' raw."""
import httpx
r = httpx.get("https://chat.b.ai/key", timeout=15, follow_redirects=True,
              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
text = r.text
print("isMaintenance count:", text.count("isMaintenance"))
print("isMaintenance escape count:", text.count('isMaintenance":'))
print("sample around 'isMaintenance':")
i = text.find("isMaintenance")
while i > 0 and i < len(text):
    print(text[max(0,i-100):i+80])
    print("---")
    i = text.find("isMaintenance", i+1)
    if i > 50000: break
