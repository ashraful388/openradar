"""Show the actual JSON structure of one model block."""
import httpx, re, json
r = httpx.get("https://chat.b.ai/key", timeout=15, follow_redirects=True,
              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
text = r.text.replace('\\"', '"').replace("\\\\", "\\")

# The page contains "serverModelLists":[{"abilities":{...},"id":"<id>",...}]
# Find the first serverModelLists block.
m = re.search(r'\{[^{}]*"serverModelLists":\s*\[', text)
if m:
    # Walk to the matching closing bracket
    start = m.end() - 1  # at the '['
    depth = 0
    end = start
    for i, ch in enumerate(text[start:], start=start):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    arr_text = text[start:end]
    print("array length:", len(arr_text))
    # Each item is a {...} object. Split on top-level commas... actually just count braces.
    # Try to extract just the model objects
    objs = []
    depth = 0
    obj_start = None
    for i, ch in enumerate(arr_text):
        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start is not None:
                objs.append(arr_text[obj_start:i+1])
                obj_start = None
    print(f"found {len(objs)} model objects")
    print()
    print("=== first model object (pretty) ===")
    print(json.dumps(json.loads(objs[0]), indent=2)[:1500])
    print()
    print("=== second model object (first 800 chars) ===")
    print(objs[1][:800])
    print()
    print("=== ids found in this list ===")
    for o in objs:
        id_m = re.search(r'"id":"([^"]+)"', o)
        if id_m:
            print("  ", id_m.group(1))
