"""Check what's on /providers/bai."""
import urllib.request

t = urllib.request.urlopen("http://127.0.0.1:3000/providers/bai", timeout=30).read().decode("utf-8", errors="ignore")
for n in ["All models on this provider", "MiMo-V2.5", "Claude-Opus-5", "GPT-5.6-Sol",
          "4.000", "20.000", "badge-free", "section-title", "Free models",
          "model-id-row", "model-name", "Total models"]:
    print(f"  {n:30s}  {t.count(n)}")
print()
print("--- pricing in the 'All models' table ---")
import re
# Find the "All models" section
i = t.find("All models on this provider")
if i > 0:
    sample = t[i:i+3000]
    # find every price cell like "$X.XXX"
    prices = re.findall(r"\$[\d.]+", sample)
    print(f"  prices found: {prices[:30]}")
