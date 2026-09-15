"""Helpers for promoting a candidate to a real provider row.

A candidate is a host we discovered from a community list. We promote
it when:
  1. Its `/v1/models` endpoint returns 200, OR
  2. It appears in models.dev's known providers list.

On promotion we generate a stable id, slug, and the smallest possible
Provider record. The agent's next pass will backfill models, regions,
and modalities from the live /v1/models payload."""
from __future__ import annotations
import re
from .models import Provider, now

SLUG_FRIENDLY = re.compile(r"[^a-z0-9]+")

# Link texts that say nothing about the provider ("Check [Models](…)",
# "[API](…)") — when a candidate's name is one of these, derive the
# brand from the host instead.
GENERIC_NAMES = {
    "models", "model", "api", "docs", "documentation", "doc", "here", "website",
    "home", "homepage", "link", "free", "free models", "free api", "unknown",
    "v1", "llm", "llms", "dashboard", "console", "platform", "signup",
    "sign up", "keys", "api keys", "pricing", "get started", "start",
}

HOST_PREFIXES = ("api.", "www.", "chat.", "platform.", "console.", "gateway.",
                 "llm.", "inference.", "playground.", "app.")


def brand_from_host(host: str) -> str:
    """api.voidai.app -> Voidai; hcap.ai -> Hcap; helixmind.online -> Helixmind."""
    h = (host or "").lower().split("/")[0]
    for prefix in HOST_PREFIXES:
        if h.startswith(prefix):
            h = h[len(prefix):]
            break
    label = re.sub(r"[^a-z0-9]", "", h.split(".")[0])
    return label.capitalize() if label else (host or "Unknown")


def is_generic_name(name: str | None) -> bool:
    return not name or name.strip().lower() in GENERIC_NAMES


def homepage_from_host(api_base: str) -> str:
    """Best-effort provider website from an api_base host.

    Strips the usual API subdomain prefixes (api. www. llm. …) and
    returns the bare https origin: https://api.voidai.app/v1 →
    https://voidai.app. Catalog rows that need a different canonical
    URL pin it via catalog.HOMEPAGES instead."""
    if not api_base or not api_base.startswith("http"):
        return ""
    host = api_base.split("//", 1)[-1].split("/", 1)[0].lower()
    for prefix in HOST_PREFIXES:
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    if not host or "." not in host:
        return ""
    return f"https://{host}"


def slugify(host: str) -> str:
    base = host.split(".")[0]
    s = SLUG_FRIENDLY.sub("-", base.lower()).strip("-")
    return s or "provider"


def make_provider(candidate: dict, taken_ids: set[str], taken_slugs: set[str]) -> Provider | None:
    host = candidate["host"]
    slug_base = slugify(host)
    slug = slug_base
    i = 2
    while slug in taken_slugs:
        slug = f"{slug_base}-{i}"
        i += 1
    taken_slugs.add(slug)
    pid = "p_" + slug.replace("-", "_")
    n = 2
    while pid in taken_ids:
        pid = f"p_{slug.replace('-', '_')}_{n}"
        n += 1
    taken_ids.add(pid)
    name = candidate.get("name") or host
    if is_generic_name(name):
        name = brand_from_host(host)
    return Provider(
        id=pid,
        slug=slug,
        name=name,
        region="Global",
        api_base=f"https://{host}/v1",
        openai_compatible=True,
        homepage=f"https://{host}",
        signup_friction="email",
        modalities=["chat"],
        tagline=f"Auto-discovered from {candidate.get('source', 'community list')}.",
        notes=f"First seen in {candidate.get('source', 'community list')}. Verify free tier before relying on it.",
        catch="Auto-added; review before building on it.",
        first_seen=now(),
        last_verified=now(),
    )