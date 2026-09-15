"""Verify the new UI pieces are present in the served HTML."""
import urllib.request

def get(u):
    return urllib.request.urlopen(u, timeout=30).read().decode("utf-8", errors="ignore")

home = get("http://127.0.0.1:3000/")
provs = get("http://127.0.0.1:3000/providers/bai")
mods = get("http://127.0.0.1:3000/models")
orv = get("http://127.0.0.1:3000/providers/openrouter")

def count(s, needles):
    return {n: s.count(n) for n in needles}

print("=== HOME ===")
for k, v in count(home, ["API Providers", "Free API directory", "Directory",
                          "search providers", "all regions", "all signup types",
                          "bai", "openrouter", "huggingface"]).items():
    print(f"  {k:25s} {v}")
print()
print("=== /providers/bai ===")
for k, v in count(provs, ["b.ai", "Model ID", "Copy", "model-id-row", "api.b.ai/v1"]).items():
    print(f"  {k:25s} {v}")
print()
print("=== /models ===")
for k, v in count(mods, ["provider-section", "provider-section-name", "cell-link",
                          "grouped by provider", "open provider", "b.ai"]).items():
    print(f"  {k:25s} {v}")
print()
print("=== /providers/openrouter ===")
for k, v in count(orv, ["Free models", "Meta:", "Mistral", "model-id-row", "free-count"]).items():
    print(f"  {k:25s} {v}")
