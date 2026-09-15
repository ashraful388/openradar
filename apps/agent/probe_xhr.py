"""Look for XHR URLs / Next.js data routes in the page."""
import httpx, re
r = httpx.get("https://chat.b.ai/key", timeout=15, follow_redirects=True,
              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
text = r.text
# Next.js routes typically look like /_next/data/<buildId>/<route>.json
print("--- /_next/data links ---")
for m in list(re.finditer(r'/_next/data/[^"\s]+', text))[:10]:
    print(" ", m.group(0)[:120])
print()
print("--- script srcs ---")
for m in list(re.finditer(r'src="(/_next/[^"]+)"', text))[:10]:
    print(" ", m.group(1)[:120])
print()
# Look for any fetch/XHR URL
print("--- fetch/axios URLs ---")
for m in list(re.finditer(r'(?:fetch|axios)\(["\']([^"\']+)["\']', text))[:10]:
    print(" ", m.group(1)[:120])
