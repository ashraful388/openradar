"""Find all serverModelLists arrays in the page."""
import httpx, re
r = httpx.get("https://chat.b.ai/key", timeout=15, follow_redirects=True,
              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
text = r.text.replace('\\"', '"').replace("\\\\", "\\")

# Find every "aiProvider":... pattern and walk to its closing brace.
# Pattern: "aiProvider":{<provider>:<provider>...}
provider_starts = list(re.finditer(r'"aiProvider":\{', text))
print(f"found {len(provider_starts)} aiProvider blocks")
all_ids = set()
for p in provider_starts:
    # Walk braces to find the end of this aiProvider object
    i = p.end() - 1  # at the opening {
    depth = 0
    end = i
    for j in range(i, min(i+200000, len(text))):
        ch = text[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    block = text[p.start():end]
    # Find serverModelLists within
    sm = re.search(r'"serverModelLists":\s*\[', block)
    if not sm:
        continue
    arr_start = sm.end() - 1
    depth = 0
    arr_end = arr_start
    for j in range(arr_start, min(arr_start+200000, len(block))):
        ch = block[j]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                arr_end = j + 1
                break
    arr = block[arr_start:arr_end]
    # extract ids from this array
    for m in re.finditer(r'"id":"([^"]+)"', arr):
        all_ids.add(m.group(1))
    print(f"  provider block at {p.start()}: {len(arr)} chars, ids: ", end="")
    ids_in_block = re.findall(r'"id":"([^"]+)"', arr)
    print(ids_in_block[:5])

print()
print(f"unique ids total: {len(all_ids)}")
for i in sorted(all_ids):
    print("  ", i)
