"""Test the b.ai scraper end-to-end."""
from openradar.sources.bai import scrape_chat, all_rows, normalize_display

rows = scrape_chat()
print(f"scraped {len(rows)} models")
if rows:
    print()
    print("=== first 6 ===")
    for r in rows[:6]:
        print(f"  {r}")
    print()
    print("=== all 45 expected ids present? ===")
    expected = [
        "deepseek-v4-flash", "deepseek-v4-flash-vision-exp", "deepseek-v4-pro",
        "hy3", "hy4-preview",
        "mimo-v2.5", "mimo-v2.5-pro",
        "glm-5.3-flash", "glm-5.3", "glm-5.2", "glm-5.1",
        "qwen3.8-flash", "qwen3.8-max", "qwen3.8-27b",
        "claude-opus-5", "claude-fable-5",
        "claude-opus-4.8", "claude-opus-4.7", "claude-opus-4.6", "claude-opus-4.5",
        "claude-sonnet-5", "claude-sonnet-4.6", "claude-sonnet-4.5", "claude-haiku-4.5",
        "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
        "gpt-5.5", "gpt-5.5-instant", "gpt-5.4", "gpt-5.2", "gpt-5.4-pro",
        "gpt-5.4-mini", "gpt-5-mini", "gpt-5.4-nano", "gpt-5-nano",
        "gemini-3.1-pro", "gemini-3.5-flash", "gemini-3-flash",
        "gemini-3.5-flash-lite", "gemini-3.6-flash",
        "minimax-m3", "minimax-m2.7",
        "kimi-k2.6", "kimi-k3",
    ]
    scraped_ids = {r["id"] for r in rows}
    missing = [e for e in expected if e not in scraped_ids]
    extra = scraped_ids - set(expected)
    print(f"  missing: {len(missing)}  {missing[:10]}")
    print(f"  extra:   {len(extra)}  {list(extra)[:10]}")

print()
print("=== all_rows() (scrape + fallback catalog) ===")
combined = all_rows()
print(f"total: {len(combined)}")
for r in combined[:3]:
    print(f"  {r}")
