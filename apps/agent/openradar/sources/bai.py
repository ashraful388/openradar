"""b.ai source.

Two paths to the data:

1. **scrape_chat()** — fetches https://chat.b.ai/key, which is a Next.js
   server-rendered page that embeds the full model list with pricing in
   a RSC payload. This is the primary path. No LLM, no headless browser.
   The data is JSON-like text; we extract model blocks with a forgiving
   regex.

2. **fetch_live()** — if BAI_API_KEY is set, calls the live /v1/models
   endpoint. This gives accurate `id` strings but no pricing.

3. **CATALOG (static)** — the typed list of models, used as a fallback
   when both paths above fail. Maintained manually from screenshots.
"""
from __future__ import annotations
import os
import re
import httpx
from .. import provider_keys
from ..models import Model, now


# Static catalog. Used only when both scrape and live fail. Kept in sync
# with the last known b.ai pricing page.
CATALOG: list[dict] = [
    # DeepSeek
    {"provider": "DeepSeek", "family": "DeepSeek", "model": "DeepSeek-V4-Flash",
     "display": "DeepSeek V4 Flash", "input": 0, "cache_write": 0, "cache_read": 0, "output": 0,
     "modalities": ["chat"]},
    {"provider": "DeepSeek", "family": "DeepSeek", "model": "DeepSeek-V4-Flash-Vision-Exp",
     "display": "DeepSeek V4 Flash Vision (exp)", "input": None, "cache_write": None, "cache_read": None, "output": None,
     "free": False,  # 1-token probe 2026-09-16: "credit insufficient balance" — now credit-gated
     "modalities": ["chat", "vision"]},
    {"provider": "DeepSeek", "family": "DeepSeek", "model": "DeepSeek-V4-Pro",
     "display": "DeepSeek V4 Pro", "input": 1.32, "cache_write": 1.32, "cache_read": 0.044, "output": 3.96,
     "modalities": ["chat", "vision"]},
    # Tencent Hunyuan
    {"provider": "Tencent", "family": "Hunyuan", "model": "Hy3",
     "display": "Hunyuan Hy3", "input": 0, "cache_write": 0, "cache_read": 0, "output": 0,
     "modalities": ["chat"]},
    {"provider": "Tencent", "family": "Hunyuan", "model": "Hy4-preview",
     "display": "Hunyuan Hy4 (preview)", "input": 0.834, "cache_write": 0.834, "cache_read": 0.0417, "output": 2.501,
     "modalities": ["chat"]},
    # Xiaomi MiMo
    {"provider": "Xiaomi", "family": "MiMo", "model": "MiMo-V2.5",
     "display": "MiMo V2.5", "input": 0, "cache_write": 0, "cache_read": 0, "output": 0,
     "modalities": ["chat"]},
    {"provider": "Xiaomi", "family": "MiMo", "model": "MiMo-V2.5-Pro",
     "display": "MiMo V2.5 Pro", "input": 0.435, "cache_write": 0.435, "cache_read": 0.0036, "output": 0.87,
     "modalities": ["chat"]},
    # Z.ai / GLM
    {"provider": "Z.ai", "family": "GLM", "model": "GLM-5.3-Flash",
     "display": "GLM 5.3 Flash", "input": None, "cache_write": None, "cache_read": None, "output": None,
     "free": False,  # 1-token probe 2026-09-16: "credit insufficient balance, required=102" — repriced
     "modalities": ["chat"]},
    {"provider": "Z.ai", "family": "GLM", "model": "GLM-5.3",
     "display": "GLM 5.3", "input": 1.4, "cache_write": 1.4, "cache_read": 0.28, "output": 4.4,
     "modalities": ["chat", "vision"]},
    {"provider": "Z.ai", "family": "GLM", "model": "GLM-5.2",
     "display": "GLM 5.2", "input": 1.4, "cache_write": 1.4, "cache_read": 0.28, "output": 4.4,
     "modalities": ["chat", "vision"]},
    {"provider": "Z.ai", "family": "GLM", "model": "GLM-5.1",
     "display": "GLM 5.1", "input": 1.4, "cache_write": 1.4, "cache_read": 0.28, "output": 4.4,
     "modalities": ["chat", "vision"]},
    # Alibaba Qwen
    {"provider": "Alibaba", "family": "Qwen", "model": "Qwen3.8-Flash",
     "display": "Qwen 3.8 Flash", "input": 0, "cache_write": 0, "cache_read": 0, "output": 0,
     "modalities": ["chat"]},
    {"provider": "Alibaba", "family": "Qwen", "model": "Qwen3.8-Max",
     "display": "Qwen 3.8 Max", "input": 2, "cache_write": 2, "cache_read": 0.25, "output": 6,
     "modalities": ["chat", "vision"]},
    {"provider": "Alibaba", "family": "Qwen", "model": "Qwen3.8-27B",
     "display": "Qwen 3.8 27B", "input": 0.22, "cache_write": 0.22, "cache_read": 0.022, "output": 1.6,
     "modalities": ["chat"]},
    # Anthropic Claude
    {"provider": "Anthropic", "family": "Claude", "model": "Claude Opus 5",
     "display": "Claude Opus 5", "input": 5, "cache_write": 6.25, "cache_read": 0.5, "output": 25,
     "modalities": ["chat", "vision"]},
    {"provider": "Anthropic", "family": "Claude", "model": "Claude Fable 5",
     "display": "Claude Fable 5", "input": 10, "cache_write": 12.5, "cache_read": 1, "output": 50,
     "modalities": ["chat", "vision"]},
    {"provider": "Anthropic", "family": "Claude", "model": "Claude Opus 4.8",
     "display": "Claude Opus 4.8", "input": 5, "cache_write": 6.25, "cache_read": 0.5, "output": 25,
     "modalities": ["chat", "vision"]},
    {"provider": "Anthropic", "family": "Claude", "model": "Claude Opus 4.7",
     "display": "Claude Opus 4.7", "input": 5, "cache_write": 6.25, "cache_read": 0.5, "output": 25,
     "modalities": ["chat", "vision"]},
    {"provider": "Anthropic", "family": "Claude", "model": "Claude Opus 4.6",
     "display": "Claude Opus 4.6", "input": 5, "cache_write": 6.25, "cache_read": 0.5, "output": 25,
     "modalities": ["chat", "vision"]},
    {"provider": "Anthropic", "family": "Claude", "model": "Claude Opus 4.5",
     "display": "Claude Opus 4.5", "input": 5, "cache_write": 6.25, "cache_read": 0.5, "output": 25,
     "modalities": ["chat", "vision"]},
    {"provider": "Anthropic", "family": "Claude", "model": "Claude Sonnet 5",
     "display": "Claude Sonnet 5", "input": 2, "cache_write": 2.5, "cache_read": 0.2, "output": 10,
     "modalities": ["chat", "vision"]},
    {"provider": "Anthropic", "family": "Claude", "model": "Claude Sonnet 4.6",
     "display": "Claude Sonnet 4.6", "input": 3, "cache_write": 3.75, "cache_read": 0.3, "output": 15,
     "modalities": ["chat", "vision"]},
    {"provider": "Anthropic", "family": "Claude", "model": "Claude Sonnet 4.5",
     "display": "Claude Sonnet 4.5", "input": 3, "cache_write": 3.75, "cache_read": 0.3, "output": 15,
     "modalities": ["chat", "vision"]},
    {"provider": "Anthropic", "family": "Claude", "model": "Claude Haiku 4.5",
     "display": "Claude Haiku 4.5", "input": 1, "cache_write": 1.25, "cache_read": 0.1, "output": 5,
     "modalities": ["chat", "vision"]},
    # OpenAI
    {"provider": "OpenAI", "family": "OpenAI", "model": "GPT-5.6 Sol",
     "display": "GPT-5.6 Sol", "input": 4, "cache_write": 5, "cache_read": 0.4, "output": 20,
     "modalities": ["chat", "vision"]},
    {"provider": "OpenAI", "family": "OpenAI", "model": "GPT-5.6 Terra",
     "display": "GPT-5.6 Terra", "input": 2, "cache_write": 2.5, "cache_read": 0.2, "output": 12,
     "modalities": ["chat", "vision"]},
    {"provider": "OpenAI", "family": "OpenAI", "model": "GPT-5.6 Luna",
     "display": "GPT-5.6 Luna", "input": 0.2, "cache_write": 0.25, "cache_read": 0.02, "output": 1.2,
     "modalities": ["chat", "vision"]},
    {"provider": "OpenAI", "family": "OpenAI", "model": "GPT-5.5",
     "display": "GPT-5.5", "input": 5, "cache_write": 5, "cache_read": 0.5, "output": 30,
     "modalities": ["chat", "vision"]},
    {"provider": "OpenAI", "family": "OpenAI", "model": "GPT-5.5-Instant",
     "display": "GPT-5.5 Instant", "input": 5, "cache_write": 5, "cache_read": 0.5, "output": 30,
     "modalities": ["chat", "vision"]},
    {"provider": "OpenAI", "family": "OpenAI", "model": "GPT-5.4",
     "display": "GPT-5.4", "input": 2.5, "cache_write": 2.5, "cache_read": 0.25, "output": 15,
     "modalities": ["chat", "vision"]},
    {"provider": "OpenAI", "family": "OpenAI", "model": "GPT-5.2",
     "display": "GPT-5.2", "input": 1.75, "cache_write": 1.75, "cache_read": 0.175, "output": 14,
     "modalities": ["chat", "vision"]},
    {"provider": "OpenAI", "family": "OpenAI", "model": "GPT-5.4 Pro",
     "display": "GPT-5.4 Pro", "input": 30, "cache_write": 30, "cache_read": 3, "output": 180,
     "modalities": ["chat", "vision"]},
    {"provider": "OpenAI", "family": "OpenAI", "model": "GPT-5.4 mini",
     "display": "GPT-5.4 mini", "input": 0.75, "cache_write": 0.75, "cache_read": 0.075, "output": 4.5,
     "modalities": ["chat", "vision"]},
    {"provider": "OpenAI", "family": "OpenAI", "model": "GPT-5 mini",
     "display": "GPT-5 mini", "input": 0.25, "cache_write": 0.25, "cache_read": 0.025, "output": 2,
     "modalities": ["chat", "vision"]},
    {"provider": "OpenAI", "family": "OpenAI", "model": "GPT-5.4 nano",
     "display": "GPT-5.4 nano", "input": 0.2, "cache_write": 0.2, "cache_read": 0.02, "output": 1.25,
     "modalities": ["chat", "vision"]},
    {"provider": "OpenAI", "family": "OpenAI", "model": "GPT-5 nano",
     "display": "GPT-5 nano", "input": 0.05, "cache_write": 0.05, "cache_read": 0.005, "output": 0.4,
     "modalities": ["chat", "vision"]},
    # Google Gemini
    {"provider": "Google", "family": "Gemini", "model": "Gemini 3.1 Pro",
     "display": "Gemini 3.1 Pro", "input": 2, "cache_write": 2, "cache_read": 0.2, "output": 12,
     "modalities": ["chat", "vision"]},
    {"provider": "Google", "family": "Gemini", "model": "Gemini 3.5 flash",
     "display": "Gemini 3.5 Flash", "input": 1.5, "cache_write": 1.5, "cache_read": 0.15, "output": 9,
     "modalities": ["chat", "vision"]},
    {"provider": "Google", "family": "Gemini", "model": "Gemini 3 Flash",
     "display": "Gemini 3 Flash", "input": 0.5, "cache_write": 0.5, "cache_read": 0.05, "output": 3,
     "modalities": ["chat", "vision"]},
    {"provider": "Google", "family": "Gemini", "model": "Gemini 3.5 flash-lite",
     "display": "Gemini 3.5 Flash-Lite", "input": 0.3, "cache_write": 0.3, "cache_read": 0.03, "output": 2.5,
     "modalities": ["chat", "vision"]},
    {"provider": "Google", "family": "Gemini", "model": "Gemini 3.6 flash",
     "display": "Gemini 3.6 Flash", "input": 1.5, "cache_write": 1.5, "cache_read": 0.15, "output": 7.5,
     "modalities": ["chat", "vision"]},
    # MiniMax
    {"provider": "MiniMax", "family": "MiniMax", "model": "MiniMax-M3",
     "display": "MiniMax M3", "input": 0.3, "cache_write": 0.3, "cache_read": 0.06, "output": 1.2,
     "modalities": ["chat"]},
    {"provider": "MiniMax", "family": "MiniMax", "model": "MiniMax-M2.7",
     "display": "MiniMax M2.7", "input": 0.3, "cache_write": 0.375, "cache_read": 0.06, "output": 1.2,
     "modalities": ["chat"]},
    # Moonshot Kimi
    {"provider": "Moonshot", "family": "Kimi", "model": "Kimi-K2.6",
     "display": "Kimi K2.6", "input": 0.95, "cache_write": 0.95, "cache_read": 0.1615, "output": 4,
     "modalities": ["chat"]},
    {"provider": "Moonshot", "family": "Kimi", "model": "Kimi K3",
     "display": "Kimi K3", "input": 3, "cache_write": 3, "cache_read": 0.3, "output": 15,
     "modalities": ["chat"]},
]


# Mapping from b.ai's `provider` label (in the page payload) to a normalized
# display name. Used to compute the b.ai-family grouping on the detail page.
PROVIDER_LABELS = {
    "deepseek": "DeepSeek",
    "tencent": "Tencent",
    "xiaomi": "Xiaomi",
    "z.ai": "Z.ai",
    "alibaba": "Alibaba",
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google",
    "minimax": "MiniMax",
    "moonshot": "Moonshot",
}

# Pull from pointPricing + pricing.units. Returns dict or None.
def _parse_block(chunk: str) -> dict | None:
    id_m = re.search(r'"id":"([^"]+)"', chunk)
    if not id_m:
        return None
    model_id = id_m.group(1)
    display_m = re.search(r'"displayName":"([^"]+)"', chunk)
    display = display_m.group(1) if display_m else model_id
    provider_m = re.search(r'"companyLabel":"([^"]+)"', chunk)
    provider = provider_m.group(1) if provider_m else ""
    # pointPricing.units: array of {cost, name}
    pp = re.search(r'"pointPricing":\{"units":\s*\[([^\]]+)\]', chunk)
    point: dict[str, float] = {}
    if pp:
        for m in re.finditer(r'"cost":([\d.]+),"name":"([^"]+)"', pp.group(1)):
            point[m.group(2)] = float(m.group(1))
    # pricing.units: array of {name, rate, unit, strategy}
    pr = re.search(r'"pricing":\{"currency":"[^"]+","units":\s*\[([^\]]+)\]', chunk)
    cash: dict[str, float] = {}
    if pr:
        for m in re.finditer(r'"name":"([^"]+)","rate":([\d.]+),"strategy":"[^"]+","unit":"([^"]+)"', pr.group(1)):
            cash[m.group(1)] = float(m.group(2))
    return {
        "id": model_id,
        "display": display,
        "provider": provider,
        "input": point.get("inputPrice", 0),
        "output": point.get("outputPrice", 0),
        "cache_read": cash.get("textInput_cacheRead", 0),
        "cache_write": cash.get("textInput_cacheWrite", 0),
    }


def scrape_chat(timeout: float = 20.0) -> list[dict]:
    """Fetch https://chat.b.ai/key and extract every model block from
    its embedded RSC payload. Returns [] on any failure.

    The page embeds the model list as a JS-encoded string inside HTML,
    so all the JSON quotes are backslash-escaped (\"...\"). We strip
    the escapes first, then regex against the normalized text."""
    try:
        r = httpx.get(
            "https://chat.b.ai/key",
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"},
        )
    except httpx.HTTPError:
        return []
    if r.status_code != 200 or not r.text:
        return []
    # Unescape the JS string: \" -> ", \\ -> \
    text = r.text.replace('\\"', '"').replace("\\\\", "\\")
    blocks: list[dict] = []
    seen_ids: set[str] = set()
    for m in re.finditer(r'"id":"([a-z0-9\-.]+)","isMaintenance":(true|false),"maxOutput":(\d+)', text):
        model_id = m.group(1)
        if model_id in seen_ids:
            continue
        seen_ids.add(model_id)
        start = max(0, m.start() - 200)
        end = min(len(text), m.end() + 1800)
        block = _parse_block(text[start:end])
        if block and block.get("input") is not None and block.get("output") is not None:
            blocks.append(block)
    return blocks


def fetch_live(timeout: float = 15.0) -> list[dict]:
    """If BAI_API_KEY is set, pull the live /v1/models list. Returns empty
    list otherwise (caller falls back to scraping, then to the static CATALOG).
    The key resolves from the environment first (CI/Vercel path), then the
    Settings → Provider API keys store."""
    key = os.environ.get("BAI_API_KEY") or provider_keys.get("BAI_API_KEY")
    if not key:
        return []
    try:
        r = httpx.get(
            "https://api.b.ai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        return data.get("data", data) if isinstance(data, dict) else data
    except httpx.HTTPError:
        return []


def is_free(row: dict) -> bool:
    """A model is 'free' when its input AND output pricing is 0.
    Models with a gift-box icon (new-signup promo) are flagged via the
    `is_promo` field on the scraped row, which sets free_kind='free_credits'.
    A row carrying `free: False` has no usable pricing (b.ai repriced it
    behind a credit balance — probe-verified 2026-09-16) or is a
    live-list row with no pricing at all: unknown is never free."""
    if row.get("free") is False:
        return False
    try:
        return float(row.get("input", 0) or 0) == 0 and float(row.get("output", 0) or 0) == 0
    except (TypeError, ValueError):
        return False


def to_model_id(row: dict) -> str:
    # Scraped rows carry the display name in `model`; live /v1/models rows
    # use `id`. Fall back to either so a single row shape works for both.
    name = row.get("model") or row.get("id") or ""
    return name.replace(" ", "-")


def normalize_display(model_id: str) -> str:
    """Convert b.ai's kebab-case model id ('claude-opus-5') to the
    title-cased display ('Claude Opus 5') so we can route by display name
    into the upstream providers (where models are kept under display names
    like 'Claude Opus 5')."""
    overrides = {
        "claude-opus-5": "Claude Opus 5",
        "claude-fable-5": "Claude Fable 5",
        "claude-opus-4.8": "Claude Opus 4.8",
        "claude-opus-4.7": "Claude Opus 4.7",
        "claude-opus-4.6": "Claude Opus 4.6",
        "claude-opus-4.5": "Claude Opus 4.5",
        "claude-sonnet-5": "Claude Sonnet 5",
        "claude-sonnet-4.6": "Claude Sonnet 4.6",
        "claude-sonnet-4.5": "Claude Sonnet 4.5",
        "claude-haiku-4.5": "Claude Haiku 4.5",
        "gpt-5.6-sol": "GPT-5.6 Sol",
        "gpt-5.6-terra": "GPT-5.6 Terra",
        "gpt-5.6-luna": "GPT-5.6 Luna",
        "gpt-5.5": "GPT-5.5",
        "gpt-5.5-instant": "GPT-5.5 Instant",
        "gpt-5.4": "GPT-5.4",
        "gpt-5.2": "GPT-5.2",
        "gpt-5.4-pro": "GPT-5.4 Pro",
        "gpt-5.4-mini": "GPT-5.4 mini",
        "gpt-5-mini": "GPT-5 mini",
        "gpt-5.4-nano": "GPT-5.4 nano",
        "gpt-5-nano": "GPT-5 nano",
        "deepseek-v4-flash": "DeepSeek V4 Flash",
        "deepseek-v4-flash-vision-exp": "DeepSeek V4 Flash Vision (exp)",
        "deepseek-v4-pro": "DeepSeek V4 Pro",
        "hy3": "Hy3",
        "hy4-preview": "Hy4-preview",
        "mimo-v2.5": "MiMo V2.5",
        "mimo-v2.5-pro": "MiMo V2.5 Pro",
        "glm-5.3-flash": "GLM 5.3 Flash",
        "glm-5.3": "GLM 5.3",
        "glm-5.2": "GLM 5.2",
        "glm-5.1": "GLM 5.1",
        "qwen3.8-flash": "Qwen 3.8 Flash",
        "qwen3.8-max": "Qwen 3.8 Max",
        "qwen3.8-27b": "Qwen 3.8 27B",
        "gemini-3.1-pro": "Gemini 3.1 Pro",
        "gemini-3.5-flash": "Gemini 3.5 flash",
        "gemini-3-flash": "Gemini 3 Flash",
        "gemini-3.5-flash-lite": "Gemini 3.5 flash-lite",
        "gemini-3.6-flash": "Gemini 3.6 flash",
        "minimax-m3": "MiniMax M3",
        "minimax-m2.7": "MiniMax M2.7",
        "kimi-k2.6": "Kimi K2.6",
        "kimi-k3": "Kimi K3",
    }
    return overrides.get(model_id.lower(), model_id)


def all_rows() -> list[dict]:
    """Combine all sources in priority order:

      1. Live API (BAI_API_KEY set) — accurate model ids, NO pricing:
         those rows are marked `free: False` because b.ai now credit-gates
         models individually; an unpriced live row used to default to
         free and kept repriced models (GLM-5.3-Flash) looking free.
      2. Scrape chat.b.ai/key — accurate model ids and pricing.
      3. Static CATALOG — last known values (rows probe-verified to
         require credits carry `free: False`).

    Each step only fills in models the previous step didn't cover."""
    live = fetch_live()
    scraped = scrape_chat()
    by_id: dict[str, dict] = {}
    for row in scraped:
        by_id[row["id"]] = row
    for row in live:
        mid = row.get("id") or row.get("name") or ""
        if mid and mid not in by_id:
            # Raw live rows carry no pricing — b.ai credit-gates models
            # individually, so "unknown price" must not classify as free.
            # The 1-token probe (with a key) re-verifies the genuinely
            # free ones every run.
            by_id[mid] = {"id": mid, "free": False}
    for row in CATALOG:
        # the catalog's "model" key maps to the b.ai kebab-case id; convert.
        scraped_id = row["model"].lower().replace(" ", "-")
        if scraped_id not in by_id:
            by_id[scraped_id] = {
                "id": scraped_id,
                "display": row["display"],
                "provider": row["provider"],
                "input": row.get("input"),
                "output": row.get("output"),
                "cache_read": row.get("cache_read"),
                "cache_write": row.get("cache_write"),
                "free": row.get("free"),
            }
    return list(by_id.values())
