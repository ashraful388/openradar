"""Check what 'API Providers' labels appear on the home page."""
import urllib.request

t = urllib.request.urlopen("http://127.0.0.1:3000/", timeout=30).read().decode("utf-8", errors="ignore")
for needle in ["API Providers", "API providers", "api-providers", "API provider",
               "providers grid", "search providers", "all regions",
               "01", "Free endpoints, grouped by provider",
               "row-title", "APIProviders"]:
    print(f"  {needle!r:40s}  {t.count(needle)}")
