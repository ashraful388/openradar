"""Extract every model with its pricing from the b.ai page — more forgiving regex."""
import httpx
import re

r = httpx.get("https://chat.b.ai/key", timeout=15, follow_redirects=True,
              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
text = r.text

# Find every "id":"<name>","isMaintenance":...,"maxOutput":..., pattern. Then walk forward to grab the next ~1000 chars and parse them.
matches = list(re.finditer(r'"id":"([^"]+)","isMaintenance":(true|false),"maxOutput":(\d+)', text))
print(f"found {len(matches)} model id patterns")

def parse_numbers_near(text: str, start: int, end: int) -> dict:
    """Pull every (name, cost/rate) pair from a slice of text."""
    out = {}
    for m in re.finditer(r'"name":"([^"]+)"[^}]*?(?:"cost"|"rate")\s*:\s*([\d.]+)', text[start:end]):
        out[m.group(1)] = float(m.group(2))
    return out

# Provider groupings appear as a "provider":"<name>","displayName":"<name>"... pattern
provider_m = re.search(r'"provider"\s*:\s*"([^"]+)"\s*,\s*"displayName"', text)
# Actually, the structure might be: {id, displayName, abilities, provider, pricing, pointPricing}

models = []
for m in matches:
    model_id = m.group(1)
    # find the start of this object (look backwards for "abilities" or "id":"<id>")
    obj_start = max(0, m.start() - 400)
    obj_end = min(len(text), m.end() + 800)
    chunk = text[obj_start:obj_end]
    # display name
    d = re.search(r'"displayName"\s*:\s*"([^"]+)"', chunk)
    display = d.group(1) if d else model_id
    # provider
    p = re.search(r'"provider"\s*:\s*"([^"]+)"', chunk)
    provider = p.group(1) if p else ""
    # numbers (inputPrice, outputPrice, cacheRead, cacheWrite)
    nums = parse_numbers_near(chunk, 0, len(chunk))
    models.append({
        "id": model_id,
        "display": display,
        "provider": provider,
        "input": nums.get("inputPrice"),
        "output": nums.get("outputPrice"),
        "cache_read": nums.get("textInput_cacheRead"),
        "cache_write": nums.get("textInput_cacheWrite"),
    })

print(f"extracted {len(models)} models")
for m in models:
    print(f"  provider={m['provider']:12s}  id={m['id']:30s}  in={m['input']}  out={m['output']}  cacheRead={m['cache_read']}  cacheWrite={m['cache_write']}  display={m['display']}")
