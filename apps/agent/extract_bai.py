"""Extract every model with its pricing from the b.ai page."""
import httpx
import re
import json

r = httpx.get("https://chat.b.ai/key", timeout=15, follow_redirects=True,
              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
text = r.text

# Find every model block. Pattern:
# "displayName":"<X>","enabled":true,"id":"<id>","isMaintenance":false,"maxOutput":N,
#   "pointPricing":{"units":[{"cost":<num>,"name":"inputPrice"},{"cost":<num>,"name":"outputPrice"}]},
#   "pricing":{"currency":"CNY","units":[
#     {"name":"textInput_cacheRead","rate":<num>,"strategy":"fixed","unit":"millionTokens"},
#     ...
#   ]}

# Use a more inclusive regex that captures the whole "model" object.
model_re = re.compile(
    r'"displayName":"(?P<display>[^"]+)","enabled":(?P<enabled>true|false),'
    r'"id":"(?P<id>[^"]+)","isMaintenance":(?P<maint>true|false),"maxOutput":(?P<maxo>\d+),'
    r'"pointPricing":\{(?P<point>[^}]+)\},'
    r'"pricing":\{(?P<pricing>[^}]+(?:\}[^}]+)*?\}),'
)

def parse_units(blob: str) -> dict:
    """Extract name->rate/cost from a {units: [...]} blob."""
    out = {}
    for m in re.finditer(r'"name":"([^"]+)"[^}]*?(?:"cost"|"rate")\s*:\s*"?([\d.]+)"?', blob):
        out[m.group(1)] = float(m.group(2))
    return out

results = []
for m in model_re.finditer(text):
    display = m.group("display")
    model_id = m.group("id")
    point_blob = "{" + m.group("point") + "}"
    price_blob = "{" + m.group("pricing") + "}"
    # point blob is small, just inputs and outputs
    point = parse_units(point_blob)
    price = parse_units(price_blob)
    results.append({
        "id": model_id,
        "display": display,
        "input": point.get("inputPrice"),
        "output": point.get("outputPrice"),
        "cache_read": price.get("textInput_cacheRead"),
        "cache_write": price.get("textInput_cacheWrite"),
    })

print(f"extracted {len(results)} models")
for r in results:
    print(f"  {r['id']:30s}  in={r['input']}  out={r['output']}  cacheRead={r['cache_read']}  cacheWrite={r['cache_write']}  display={r['display']}")
