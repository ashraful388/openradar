"""Verify the new nav shows API Providers."""
import urllib.request

t = urllib.request.urlopen("http://127.0.0.1:3000/", timeout=30).read().decode("utf-8", errors="ignore")
for n in ["API Providers", "Home", "search providers", "row-title"]:
    print(f"  {n:25s}  {t.count(n)}")
