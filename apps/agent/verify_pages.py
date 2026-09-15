"""Verify / and /api-providers are distinct."""
import urllib.request

home = urllib.request.urlopen("http://127.0.0.1:3000/", timeout=30).read().decode("utf-8", errors="ignore")
api = urllib.request.urlopen("http://127.0.0.1:3000/api-providers", timeout=30).read().decode("utf-8", errors="ignore")

def count(t, n): return t.count(n)

print("=== Home page (/) ===")
for n in ["Every free AI model API", "API Providers", "row-title", "providers-filters",
          "search providers", "What changed today", "provider-card", "providers-header"]:
    print(f"  {n:30s}  {count(home, n)}")
print()
print("=== /api-providers ===")
for n in ["Every free AI model API", "API Providers", "row-title", "providers-filters",
          "search providers", "What changed today", "provider-card", "providers-header",
          "The directory"]:
    print(f"  {n:30s}  {count(api, n)}")
