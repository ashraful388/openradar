"""OpenRadar CLI.

The full refresh pipeline:

  1. Load existing snapshot (or seed from catalog.py).
  2. Pull every known provider's /v1/models and merge in any models
     we don't already have. (Bumps last_verified, updates free_model_count.)
  3. Pull OpenRouter's /v1/models, find every :free variant, and
     auto-add them — both as models under their upstream provider and
     as a new provider row if the upstream isn't already known.
  4. Pull Hugging Face's router /v1/models, find free-eligible models,
     and auto-add.
  5. Pull models.dev/api.json and:
       a) cross-reference pricing and context for everything we know,
       b) build the cheap-flagships leaderboard from its paid tier.
  6. Reap community lists, probe each candidate's /v1/models, promote
     any that respond into providers.
  7. Search-API sweep if a key is set.
  8. Read the submissions inbox.
  9. Write the snapshot, append to the changelog."""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

from .models import Snapshot, Provider, Model, CheapFlagship, Change, now, CreditProvider
from .catalog import PROVIDERS, CREDIT_PROVIDERS
from .catalog import HOMEPAGES as _CATALOG_HOMEPAGES  # noqa: F401  (re-exported for tests)
from . import sources
from . import promote
from . import config as agent_config
from . import provider_keys

# Providers that need an account id or are otherwise not probeable.
SKIP_PROBE = {"p_cloudflare"}

# Mark provider as stale after this many consecutive runs with 0 models + error probe
STALE_THRESHOLD_RUNS = 3


# ----------------------------- helpers -------------------------------------

def _data_dir() -> Path:
    p = Path(os.environ.get("OPENRADAR_DATA", Path(__file__).resolve().parents[3] / "data"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_existing() -> Snapshot:
    f = _data_dir() / "snapshot.json"
    if f.exists():
        try:
            snap = Snapshot.model_validate(json.loads(f.read_text()))
            # Ensure credit_providers field exists and is populated (for older snapshots)
            if not hasattr(snap, 'credit_providers') or snap.credit_providers is None or len(snap.credit_providers) == 0:
                snap.credit_providers = list(CREDIT_PROVIDERS)
            _migrate_bai_rows(snap)
            _dedup_models(snap)
            _repair_generic_names(snap)
            _fill_homepages(snap)
            _merge_catalog_providers(snap)
            # Clean up legacy free claims: providers with needs_key probe status
            # should not have is_free=True models without evidence source
            _cleanup_legacy_free_claims(snap)
            return snap
        except Exception as e:
            print(f"[warn] existing snapshot invalid ({e}); starting from seed", file=sys.stderr)
    # Seed with the canonical catalog, no models (we'll add them).
    return Snapshot(providers=list(PROVIDERS), models=[], cheap_flagships=[], changelog=[], credit_providers=list(CREDIT_PROVIDERS))


def _cleanup_legacy_free_claims(snap: Snapshot) -> int:
    """Demote is_free=True for models on providers with needs_key probe_status
    that lack any evidence source (legacy rows from before evidence tracking).
    
    Providers with probe_status='needs_key' have gated /v1/models endpoints.
    Their :free declarations were never verified (no probe, no secondary source).
    These models should be byok_required until probe or secondary evidence confirms free.
    Returns number of models demoted."""
    demoted = 0
    # Build provider lookup
    prov_by_id = {p.id: p for p in snap.providers}
    for m in snap.models:
        if not m.is_free:
            continue
        provider = prov_by_id.get(m.provider_id)
        if not provider:
            continue
        # If provider needs_key and model has no evidence source (legacy),
        # demote to byok_required
        if provider.probe_status == "needs_key" and not m.free_evidence_source:
            m.is_free = False
            m.free_kind = "byok_required"
            m.free_limit = (m.free_limit or "") + " [demoted: provider gated, no evidence]"
            demoted += 1
        # Also handle legacy rows that have evidence source but it's weak
        # (e.g., only 'declared' from a needs_key provider)
        elif provider.probe_status == "needs_key" and m.free_evidence_source == "declared":
            # Check if there's secondary evidence - if not, demote
            # Keep free if: probe-verified, models_dev, openrouter, xkiro, bai, huggingface
            strong_sources = {"probe", "models_dev", "openrouter", "xkiro", "bai", "huggingface", "verifier"}
            if m.free_evidence_source not in strong_sources and not m.free_verified_at:
                m.is_free = False
                m.free_kind = "byok_required"
                m.free_limit = (m.free_limit or "") + " [demoted: declared only, provider gated]"
                demoted += 1
    if demoted:
        snap.changelog.append(Change(
            kind="pricing",
            text=f"cleanup: demoted {demoted} legacy free claims on needs_key providers without evidence",
        ))
    return demoted


def _merge_catalog_providers(snap: Snapshot) -> int:
    """Add catalog providers that are missing from an existing snapshot,
    and sync operator-pinned catalog fields (api_base, homepage) onto
    rows already present — the catalog is the seed and the correction
    point; a fix made there must reach the next run's snapshot. Never
    removes or overrides anything else. Returns providers added."""
    known = {p.id: p for p in snap.providers}
    added = 0
    for seed in PROVIDERS:
        p = known.get(seed.id)
        if p is None:
            snap.providers.append(seed)
            known[seed.id] = seed
            added += 1
            snap.changelog.append(Change(
                kind="added",
                text=f"catalog: added {seed.name} ({seed.slug})",
            ))
            continue
        if seed.api_base and p.api_base != seed.api_base:
            p.api_base = seed.api_base
        if seed.homepage and p.homepage != seed.homepage:
            p.homepage = seed.homepage
    return added


def _repair_generic_names(snap: Snapshot) -> int:
    """Rename providers whose name fell back to a generic link text.

    Community-list candidates were promoted with whatever the README
    link happened to say, producing rows literally named "Models".
    The brand is derived from the api_base host (api.voidai.app →
    Voidai). Slugs and ids are untouched so existing links and model
    row ids stay valid. Repairs are changelogged."""
    repaired = 0
    for p in snap.providers:
        if not promote.is_generic_name(p.name) or not p.api_base:
            continue
        host = p.api_base.split("//", 1)[-1].split("/", 1)[0]
        brand = promote.brand_from_host(host)
        if brand and brand.lower() != p.name.strip().lower():
            snap.changelog.append(Change(
                kind="verified",
                text=f"renamed provider {p.name!r} → {brand!r} (host {host})",
            ))
            p.name = brand
            repaired += 1
    return repaired


def _fill_homepages(snap: Snapshot) -> int:
    """Give every provider a public website URL.

    Precedence: catalog pins (catalog.HOMEPAGES — aistudio.google.com
    rather than the API host, together.ai rather than together.xyz, …)
    are authoritative, so the operator corrects any row by editing the
    catalog; rows without a pin get a best-effort derivation from the
    api_base host; nothing ends up empty if it has an api_base."""
    changed = 0
    known = {p.id: p for p in snap.providers}
    for pid, url in _CATALOG_HOMEPAGES.items():
        p = known.get(pid)
        if p and url and p.homepage != url:
            p.homepage = url
            changed += 1
    for p in snap.providers:
        if not p.homepage and p.api_base:
            derived = promote.homepage_from_host(p.api_base)
            if derived:
                p.homepage = derived
                changed += 1
    return changed


def _migrate_bai_rows(snap: Snapshot) -> int:
    """Move rows whose only evidence is b.ai's catalog back onto p_bai.

    An earlier version of ingest_bai remapped rows onto upstream
    providers, so b.ai's free/pricing claims rendered on Z.ai/DeepSeek
    pages as if api.z.ai itself were free — wrong attribution, exactly
    the mistake the conservative-classification rule exists to prevent.

    Migration rule (per row on a non-b.ai provider):
      - evidence is ONLY b.ai markers in free_limit → move to p_bai;
      - the row also has independent evidence (probe-verified, models.dev
        $0 backfill, OpenRouter/HF free_limit text) → keep it where it
        is and strip the b.ai marker from the text.
    Runs before dedup so same-model rows merge. Returns rows moved."""
    BAI_MARKERS = ("b.ai $0/M verified", "via b.ai")
    INDEPENDENT_MARKERS = ("probe", "models.dev", "OpenRouter", "HF ")
    moved = 0
    by_key: dict[tuple[str, str], Model] = {}
    for m in snap.models:
        by_key.setdefault((m.provider_id, m.model_id.casefold()), m)
    for m in list(snap.models):
        if m.provider_id == "p_bai":
            continue
        limit = m.free_limit or ""
        if not any(k in limit for k in BAI_MARKERS):
            continue
        has_independent = (
            m.free_verified_at
            or "verified via models.dev" in limit
            or any(k in limit for k in INDEPENDENT_MARKERS)
        )
        if has_independent:
            # Keep the row; drop the b.ai marker so it stops polluting.
            new_limit = limit
            for marker in BAI_MARKERS:
                new_limit = new_limit.replace(marker, "").strip(" |;")
            m.free_limit = new_limit
            continue
        # Pure b.ai evidence → re-home on p_bai.
        existing = by_key.get(("p_bai", m.model_id.casefold()))
        if existing is None:
            m.provider_id = "p_bai"
            m.id = _model_id_for(snap, "p_bai", m.model_id)
            by_key[("p_bai", m.model_id.casefold())] = m
            moved += 1
        else:
            # Merge into the existing p_bai row and drop this one.
            if m.is_free and not existing.is_free:
                existing.is_free = True
                existing.free_kind = m.free_kind
                existing.free_limit = existing.free_limit or m.free_limit
            if existing.input_per_1m is None and m.input_per_1m is not None:
                existing.input_per_1m = m.input_per_1m
                existing.output_per_1m = m.output_per_1m
            existing.context_window = existing.context_window or m.context_window
            snap.models.remove(m)
            moved += 1
    if moved:
        snap.changelog.append(Change(
            kind="verified",
            text=f"migration: re-homed {moved} b.ai-catalog rows from upstream providers to b.ai",
        ))
    return moved


def _dedup_models(snap: Snapshot) -> int:
    """Merge model rows that differ only by model-id case.

    Sources list ids in their own case (GLM-5.3-Flash vs glm-5.3-flash
    vs the same model re-listed by an aggregator), and the old adders
    compared exactly — producing duplicate rows per provider. Model ids
    are case-insensitive in practice (OpenAI-compatible routers resolve
    them case-insensitively), so the case-folded (provider_id, id) pair
    is the identity.

    Merge policy: keep the first-seen row (stable id ordering),
    preferring the mixed-case display form; union the evidence — free
    flag wins if ANY duplicate claimed free, pricing wins if ANY
    duplicate carried it. Runs at load time and again after ingestion
    (the one-time repair lives here too, since load runs before
    everything else). Returns rows removed."""
    from collections import defaultdict
    groups: dict[tuple[str, str], list[Model]] = defaultdict(list)
    for m in snap.models:
        groups[(m.provider_id, m.model_id.casefold())].append(m)
    kept: list[Model] = []
    removed = 0
    for key, rows in groups.items():
        if len(rows) == 1:
            kept.append(rows[0])
            continue
        # Primary: prefer a row that doesn't look all-lowercase (better
        # display form), else first-seen.
        primary = next((r for r in rows if r.model_id != r.model_id.lower()), rows[0])
        for other in rows:
            if other is primary:
                continue
            if other.is_free and not primary.is_free:
                primary.is_free = True
                primary.free_kind = other.free_kind
                primary.free_limit = primary.free_limit or other.free_limit
                primary.free_verified_at = primary.free_verified_at or other.free_verified_at
                # Preserve the stronger evidence source
                primary.free_evidence_source = other.free_evidence_source or primary.free_evidence_source
                primary.free_evidence_timestamp = other.free_evidence_timestamp or primary.free_evidence_timestamp
            if primary.input_per_1m is None and other.input_per_1m is not None:
                primary.input_per_1m = other.input_per_1m
                primary.output_per_1m = other.output_per_1m
                primary.cache_read_per_1m = other.cache_read_per_1m
                primary.cache_write_per_1m = other.cache_write_per_1m
            if primary.context_window is None:
                primary.context_window = other.context_window
            if (other.catalog_source_url and other.catalog_checked_at
                    and (not primary.catalog_checked_at or other.catalog_checked_at > primary.catalog_checked_at)):
                primary.catalog_source_url = other.catalog_source_url
                primary.catalog_checked_at = other.catalog_checked_at
            primary.last_verified = max(primary.last_verified, other.last_verified)
        kept.append(primary)
        removed += len(rows) - 1
    if removed:
        snap.models = kept
        snap.changelog.append(Change(
            kind="verified",
            text=f"dedup: merged {removed} case-duplicate model rows",
        ))
    return removed


def write(snap: Snapshot) -> Path:
    f = _data_dir() / "snapshot.json"
    f.write_text(json.dumps(snap.model_dump(), indent=2))
    return f


def _model_id_for(snap: Snapshot, provider_id: str, model_id: str) -> str:
    # Row ids stay stable across sources: case-fold the model id so the
    # same model fetched twice in different casing maps to one row id.
    return f"m_{provider_id.lstrip('p_')}_{model_id.replace('/', '_').replace(':', '_').replace('.', '_').lower()}"


def _has_model(snap: Snapshot, provider_id: str, model_id: str) -> bool:
    mid = model_id.casefold()
    return any(m.provider_id == provider_id and m.model_id.casefold() == mid
               for m in snap.models)


def _add_model(snap: Snapshot, provider_id: str, model_id: str, display: str,
               modality: list[str], *, is_free: bool, free_kind: str, free_limit: str,
               context_window: int | None = None,
               free_evidence_source: str | None = None,
               free_evidence_timestamp: str | None = None) -> bool:
    """Add a model if not already present. Returns True if added."""
    if _has_model(snap, provider_id, model_id):
        return False
    snap.models.append(Model(
        id=_model_id_for(snap, provider_id, model_id),
        provider_id=provider_id,
        model_id=model_id,
        display_name=display or model_id,
        modality=modality,
        context_window=context_window,
        is_free=is_free,
        free_kind=free_kind,
        free_limit=free_limit,
        free_evidence_source=free_evidence_source,
        free_evidence_timestamp=free_evidence_timestamp,
    ))
    return True


_FREE_MODEL_HINTS = ("free", ":free", "trial", "community", "dev-preview",
                     "preview", "nemo", "flash-lite", "lite", "mini")


def _looks_free_model_id(model_id: str) -> bool:
    mid = model_id.lower()
    return any(h in mid for h in _FREE_MODEL_HINTS)


def _infer_free_from_models_dev(snap: Snapshot, raw: dict) -> tuple[int, int]:
    """Promote (and repair) is_free flags from models.dev — scoped to the
    SAME provider.

    Promotion rule: a model with no pricing signal of its own becomes
    free only when the models.dev entry of ITS OWN provider lists both
    input and output cost as exactly $0. An earlier version of this
    matcher ignored the provider and matched by bare model id across
    every models.dev entry, so e.g. DeepInfra's paid
    `zai-org/GLM-4.7-Flash` was flagged free because Hugging Face
    serves it free. Rows created by that bug carry the
    "verified via models.dev" marker in free_limit; they are
    re-validated here and demoted when the same-provider entry doesn't
    back the claim. Absent pricing in models.dev is never treated as
    $0 — only an explicit 0/0 cost.

    Models that carry their own pricing (b.ai etc.) are never touched.
    Returns (promoted, repaired)."""
    # Explicit-cost pricing per models.dev provider id.
    md_pricing: dict[str, dict[str, tuple[float, float]]] = {}
    for prov_id, prov in raw.items():
        for mid, mdl in ((prov or {}).get("models") or {}).items():
            cost = (mdl or {}).get("cost") or {}
            try:
                inp = float(cost["input"])
                out = float(cost["output"])
            except (KeyError, TypeError, ValueError):
                continue  # absent pricing is NOT evidence of $0
            md_pricing.setdefault(prov_id, {})[mid.lower()] = (inp, out)

    # Map each models.dev provider to our provider row (same matcher the
    # flagship leaderboard uses).
    md_ids_for_ours: dict[str, list[str]] = {}
    for prov_id, prov in raw.items():
        ours = _match_models_dev_provider(snap, prov_id, prov or {})
        if ours:
            md_ids_for_ours.setdefault(ours.id, []).append(prov_id)

    promoted = repaired = 0
    demoted: list[str] = []
    for m in snap.models:
        limit = m.free_limit or ""
        # Re-validate ANY free claim resting on a models.dev marker —
        # including rows seeded by an earlier buggy pass that matched a
        # subscription-plan entry (plan views price bundled models at $0).
        # Must run BEFORE the own-pricing skip: seeded rows carry a 0.0
        # price, which is exactly what we're correcting.
        if (m.is_free
                and "$0/M" in limit
                and "models.dev" in limit
                and not m.free_verified_at
                and "verified via models.dev" not in limit):
            price = None
            for md_id in md_ids_for_ours.get(m.provider_id, []):
                hit = md_pricing.get(md_id, {}).get(m.model_id.lower())
                if hit is not None:
                    price = hit
                    break
            if price is None or price != (0.0, 0.0):
                # No same-provider backing, or the same-provider entry
                # prices it — either way the free claim is unsupported.
                m.is_free = False
                m.free_kind = "byok_required"
                m.free_limit = ""
                m.free_evidence_source = None
                m.free_evidence_timestamp = None
                if price is not None:
                    m.input_per_1m, m.output_per_1m = price
                repaired += 1
                demoted.append(f"{m.provider_id}:{m.model_id}")
                continue
        # Skip models that already carry their own pricing — they're owned
        # by b.ai (or any future source that sets input_per_1m).
        if m.input_per_1m is not None:
            continue
        price = None
        for md_id in md_ids_for_ours.get(m.provider_id, []):
            hit = md_pricing.get(md_id, {}).get(m.model_id.lower())
            if hit is not None:
                price = hit
                break
        is_free_md = price == (0.0, 0.0)
        if is_free_md and not m.is_free:
            m.is_free = True
            if m.free_kind == "byok_required":
                m.free_kind = "free_tier"
            m.free_limit = "$0/M (verified via models.dev)"
            m.free_evidence_source = "models_dev"
            m.free_evidence_timestamp = now()
            promoted += 1
        elif (m.is_free
              and "verified via models.dev" in (m.free_limit or "")
              and not is_free_md
              and not m.model_id.lower().endswith(":free")):
            # Free flag came from this rule but the same-provider entry
            # doesn't (or no longer) back it — demote with the changelog
            # as the review trail. Never demote rows whose id itself
            # declares them free (":free" is the source's own claim, and
            # models.dev sometimes lags behind live free variants).
            m.is_free = False
            m.free_kind = "byok_required"
            m.free_limit = ""
            m.free_evidence_source = None
            m.free_evidence_timestamp = None
            repaired += 1
            demoted.append(f"{m.provider_id}:{m.model_id}")
    if demoted:
        sample = ", ".join(demoted[:5]) + ("…" if len(demoted) > 5 else "")
        snap.changelog.append(Change(
            kind="pricing",
            text=f"models.dev repair: demoted {repaired} false free flags ({sample})",
        ))
    return promoted, repaired


def _ensure_provider(snap: Snapshot, slug_hint: str, name: str, host: str,
                     taken_ids: set[str], taken_slugs: set[str]) -> Provider:
    """Get or create a provider row from a host hint."""
    for p in snap.providers:
        if host in (p.api_base or "").lower() or host in (p.homepage_host() if hasattr(p, "homepage_host") else ""):
            return p
    cand = {"host": host, "name": name, "source": "openrouter"}
    new = promote.make_provider(cand, taken_ids, taken_slugs)
    assert new is not None
    snap.providers.append(new)
    return new


# Monkey-patch Provider with a homepage_host() helper if not already present.
if not hasattr(Provider, "homepage_host"):
    def _homepage_host(self: Provider) -> str:
        base = self.api_base or ""
        if base.startswith("http"):
            return base.split("//", 1)[-1].split("/", 1)[0].lower()
        return ""
    Provider.homepage_host = _homepage_host  # type: ignore[attr-defined]


# ----------------------------- ingestion steps -----------------------------

def ingest_provider_endpoints(snap: Snapshot) -> int:
    """Hit /v1/models for every known provider and merge results.

    Every provider ends the loop with a fresh probe_status:
      "ok"        — endpoint returned a model list
      "needs_key" — endpoint is gated and no API key was configured;
                    the model list is UNKNOWN, not empty. Changelog
                    entry names the env var to set.
      "gated"     — a key was sent but rejected (expired/wrong scope)
      "error"     — network/5xx/non-JSON
      "skipped"   — no probeable api_base this run
    A provider only loses needs_key when a key shows up and works —
    the flag is recomputed from live evidence each run, never guessed."""
    added = 0
    for p in snap.providers:
        p.probe_status = ""
        if not p.api_base or "{account_id}" in p.api_base or p.id in SKIP_PROBE:
            p.probe_status = "skipped"
            continue
        # Use a per-provider API key if configured: env var first
        # (CI/Vercel path), then the Settings → Provider API keys file.
        key = provider_keys.get(p.api_key_env)
        status, rows = sources.openai_compat.fetch_models(p.api_base, api_key=key, timeout=10.0)
        p.probe_status = status
        if status != "ok":
            # Loud, not silent: the run log says exactly which providers
            # are gated and what credential would unblock them.
            env_hint = p.api_key_env or "a provider API key"
            if status == "needs_key":
                snap.changelog.append(Change(
                    kind="verified",
                    text=f"{p.slug}: model list gated behind login/API key — set {env_hint} to verify",
                ))
            elif status == "gated":
                snap.changelog.append(Change(
                    kind="verified",
                    text=f"{p.slug}: API key rejected by {p.api_base} (expired or missing scope?)",
                ))
            elif status == "error":
                snap.changelog.append(Change(
                    kind="verified",
                    text=f"{p.slug}: /v1/models unreachable this run (network/5xx)",
                ))
            continue
        p.last_verified = now()
        p.status = "active"
        for row in rows:
            mid = row.get("id") or row.get("name")
            if not mid:
                continue
            mid_str = str(mid)
            declared_free = mid_str.lower().endswith(":free")
            # IMPORTANT: Do NOT auto-set is_free=True from :free suffix alone.
            # Provider-declared free tiers need probe verification OR secondary
            # source confirmation (models.dev, OpenRouter, xkiro) to avoid
            # stale/unverified free claims. We record the declaration as
            # evidence so it can be upgraded later.
            if _add_model(snap, p.id, mid_str, row.get("name") or mid_str,
                          modality=p.modalities, is_free=False,
                          free_kind="byok_required",
                          free_limit="provider-declared (:free id)" if declared_free else "",
                          context_window=row.get("context_window") or None,
                          free_evidence_source="declared" if declared_free else None,
                          free_evidence_timestamp=now() if declared_free else None):
                added += 1
            if declared_free:
                # Upgrade existing rows' evidence (not is_free) — step 1 runs before
                # OpenRouter/b.ai feeds and may create the row first.
                for existing in snap.models:
                    if (existing.provider_id == p.id
                            and existing.model_id.casefold() == mid_str.casefold()
                            and not existing.free_evidence_source):
                        existing.free_evidence_source = "declared"
                        existing.free_evidence_timestamp = now()
                        existing.free_limit = "provider-declared (:free id)"
    return added


def enforce_pricing_consistency(snap: Snapshot) -> int:
    """Hard invariant, enforced on every run: a model with explicit
    positive pricing (input or output > 0 per 1M) is NOT free, no
    matter which source set the flag. Catches every drift path — a
    provider repricing a formerly-free model, merge artifacts, source
    disagreements — before the snapshot is written. Returns rows fixed."""
    fixed = 0
    fixed_names: list[str] = []
    for m in snap.models:
        if not m.is_free:
            continue
        if (m.input_per_1m or 0) > 0 or (m.output_per_1m or 0) > 0:
            m.is_free = False
            m.free_kind = "byok_required"
            if "probe" not in (m.free_limit or ""):
                m.free_limit = (m.free_limit or "") + " [repriced by provider]" if m.free_limit else "[repriced by provider]"
            fixed += 1
            fixed_names.append(f"{m.provider_id}:{m.model_id}")
    if fixed:
        sample = ", ".join(fixed_names[:5]) + ("…" if len(fixed_names) > 5 else "")
        snap.changelog.append(Change(
            kind="expired",
            text=f"consistency: {fixed} models repriced above $0 — free flags removed ({sample})",
        ))
    return fixed


def recompute_free_counts(snap: Snapshot) -> None:
    """After all ingestions, recompute every provider's free_model_count
    from the actual model list. This catches cases where a later step
    (e.g. the models.dev $0-cost cross-reference) flipped a row to
    is_free=True after the in-loop count was set.

    Also fills `pricing_status` with a small JSON stats object so the
    web UI can show pricing coverage without recomputing per page."""
    import json as _json
    for p in snap.providers:
        pms = [m for m in snap.models if m.provider_id == p.id]
        free = sum(1 for m in pms if m.is_free)
        paid = len(pms) - free
        paid_with_price = sum(
            1 for m in pms
            if (not m.is_free) and m.input_per_1m is not None and m.output_per_1m is not None
        )
        paid_no_price = paid - paid_with_price
        p.free_model_count = free
        p.pricing_status = _json.dumps({
            "free": free,
            "paid_with_price": paid_with_price,
            "paid_no_price": paid_no_price,
            "total": len(pms),
        })


def ingest_openrouter(snap: Snapshot, taken_ids: set[str], taken_slugs: set[str]) -> int:
    """Pull OpenRouter's /v1/models, add every :free variant, create providers for new upstreams.

    Also DELISTS: a free variant that disappears from OpenRouter's live
    list loses its free flag — an "OpenRouter free variant" claim can't
    outlive the listing it came from. Rows with independent ground truth
    (a 1-token probe, models.dev $0, b.ai/xkiro/HF evidence) are kept."""
    try:
        rows = sources.openrouter.fetch(timeout=30.0)
    except Exception as e:
        snap.changelog.append(Change(kind="verified", text=f"openrouter fetch failed: {e}"))
        return 0

    added = 0
    live_free_ids: set[str] = set()
    for m in rows:
        if not sources.openrouter.is_free(m):
            continue
        mid = str(m["id"])
        live_free_ids.add(mid.casefold())
        up = sources.openrouter.upstream(m)
        # Map upstream -> known provider by checking api_base host. The
        # upstream label is often a model series ("meta-llama", "deepseek")
        # rather than the host, so we just attach it to the most generic
        # slot: openrouter itself, with the upstream id preserved.
        prov = _ensure_provider_openrouter(snap, up, taken_ids, taken_slugs)
        ctx = sources.openrouter.context_window(m)
        display = str(m.get("name") or mid)
        if _add_model(snap, prov.id, mid, display,
                      modality=["chat"], is_free=True,
                      free_kind="free_tier", free_limit="OpenRouter free variant",
                      context_window=ctx,
                      free_evidence_source="openrouter",
                      free_evidence_timestamp=now()):
            added += 1
            continue
        # Already present — but if step 1 (ingest_provider_endpoints)
        # created it as a bare byok_required row, OpenRouter's own
        # :free declaration is the stronger evidence. Upgrade it.
        # Case-fold the id: sources list the same model in different
        # casing and step 1's existence check is case-insensitive.
        # Also bump the row's verified time so stale counts stay honest.
        mid_cf = mid.casefold()
        for existing in snap.models:
            if existing.provider_id != prov.id or existing.model_id.casefold() != mid_cf:
                continue
            if not existing.is_free:
                existing.is_free = True
                existing.free_kind = "free_tier"
                existing.free_limit = "OpenRouter free variant"
                existing.free_evidence_source = "openrouter"
                existing.free_evidence_timestamp = now()
                existing.context_window = existing.context_window or ctx
                added += 1
            existing.last_verified = now()
            break

    # Delisting pass: OpenRouter-sourced free claims whose model is gone
    # from the live listing (renamed upstream, promo ended, withdrawn).
    delisted: list[str] = []
    for existing in snap.models:
        if existing.provider_id != "p_openrouter":
            continue
        if not existing.is_free or existing.free_evidence_source != "openrouter":
            continue
        if existing.free_verified_at:
            continue  # independent ground truth (1-token probe) — keep
        if existing.model_id.casefold() in live_free_ids:
            continue
        existing.is_free = False
        existing.free_kind = "byok_required"
        existing.free_limit = "[delisted by OpenRouter]"
        existing.free_evidence_source = None
        existing.free_evidence_timestamp = None
        delisted.append(existing.model_id)
    if delisted:
        sample = ", ".join(delisted[:5]) + ("…" if len(delisted) > 5 else "")
        snap.changelog.append(Change(
            kind="expired",
            text=f"openrouter: {len(delisted)} free variants delisted — free flags removed ({sample})",
        ))
    return added


def _ensure_provider_openrouter(snap: Snapshot, upstream_label: str,
                                taken_ids: set[str], taken_slugs: set[str]) -> Provider:
    """Find or create a provider row for an OpenRouter upstream label.

    We treat OpenRouter itself as the host for unknown upstreams — the
    OpenRouter router can serve them even if we don't have the upstream's
    own API base."""
    for p in snap.providers:
        if p.id == "p_openrouter":
            return p
    return snap.providers[next(i for i, x in enumerate(snap.providers) if x.id == "p_openrouter")]


def seed_models_from_models_dev(snap: Snapshot, raw: dict) -> int:
    """Backfill catalog rows for providers whose live listing is gated
    or unreachable, from THEIR OWN models.dev entry (same-provider
    matching only — never cross-provider). Rows carry explicit pricing
    where models.dev has it, so they show as paid/unverified rather
    than dangling free claims. Skips providers whose live probe
    succeeded this run (their rows come from the authoritative feed).
    Returns rows added."""
    if not raw:
        return 0
    added = 0
    for p in snap.providers:
        if p.probe_status == "ok":
            continue  # live data already in
        md_ids = [mid for mid, prov in raw.items()
                  if _match_models_dev_provider(snap, mid, prov or {}) is p]
        for md_id in md_ids:
            for mid, mdl in ((raw.get(md_id) or {}).get("models") or {}).items():
                cost = (mdl or {}).get("cost") or {}
                try:
                    inp = float(cost["input"])
                    out = float(cost["output"])
                except (KeyError, TypeError, ValueError):
                    inp = out = None  # absent pricing is not zero
                ctx = None
                try:
                    ctx = int((mdl.get("limit") or {}).get("context"))
                except (TypeError, ValueError, AttributeError):
                    ctx = None
                is_free = (inp == 0 and out == 0)
                if _add_model(snap, p.id, mid, mdl.get("name") or mid,
                              modality=p.modalities, is_free=is_free,
                              free_kind="free_tier" if is_free else "byok_required",
                              free_limit="$0/M (models.dev)" if is_free else "",
                              context_window=ctx,
                              free_evidence_source="models_dev" if is_free else None,
                              free_evidence_timestamp=now() if is_free else None):
                    added += 1
                if inp is not None:
                    for m in snap.models:
                        if (m.provider_id == p.id
                                and m.model_id.casefold() == mid.casefold()
                                and m.input_per_1m is None):
                            m.input_per_1m = inp
                            m.output_per_1m = out
                            break
    return added


def ingest_public_catalog(snap: Snapshot) -> int:
    added = 0
    for provider in snap.providers:
        if provider.id not in sources.public_catalog.URLS or provider.probe_status not in {"needs_key", "gated", "error", "skipped"}:
            continue
        try:
            rows = sources.public_catalog.fetch(provider.id)
        except Exception as e:
            snap.changelog.append(Change(
                kind="verified",
                text=f"public catalog {provider.slug}: refresh failed ({type(e).__name__})",
            ))
            continue
        if not rows:
            continue
        checked_at = now()
        url = sources.public_catalog.URLS[provider.id]
        known = {m.model_id.casefold(): m for m in snap.models if m.provider_id == provider.id}
        docs_owned = {mid for mid, m in known.items()
                      if m.free_evidence_source == "docs" and m.catalog_source_url == url}
        listed = {row.model_id.casefold(): row for row in rows}
        for mid, row in listed.items():
            model = known.get(mid)
            if model is None:
                model = Model(
                    id=_model_id_for(snap, provider.id, row.model_id),
                    provider_id=provider.id, model_id=row.model_id,
                    display_name=row.model_id, modality=provider.modalities,
                    last_verified="",
                )
                snap.models.append(model)
                known[mid] = model
                added += 1
            if model.catalog_checked_at and model.catalog_checked_at > checked_at:
                continue
            model.catalog_source_url = url
            model.catalog_checked_at = checked_at
            if (model.input_per_1m or 0) > 0 or (model.output_per_1m or 0) > 0:
                model.is_free = False
                model.free_kind = "byok_required"
                continue
            if (not row.free_limit or model.free_verified_at
                    or model.free_evidence_source not in {None, "declared", "docs"}
                    or (model.free_evidence_timestamp and model.free_evidence_timestamp > checked_at)):
                continue
            model.is_free = True
            model.free_kind = "free_tier"
            model.free_limit = row.free_limit
            model.free_evidence_source = "docs"
            model.free_evidence_timestamp = checked_at
        if provider.id == "p_groq":
            for mid, model in known.items():
                row = listed.get(mid)
                if (mid in docs_owned and model.is_free and model.free_evidence_source == "docs"
                        and model.catalog_source_url == url and not model.free_verified_at
                        and (not model.catalog_checked_at or model.catalog_checked_at <= checked_at)
                        and (not model.free_evidence_timestamp or model.free_evidence_timestamp <= checked_at)
                        and (row is None or not row.free_limit)):
                    model.is_free = False
                    model.free_kind = "byok_required"
                    model.free_limit = ""
                    model.free_evidence_source = None
                    model.free_evidence_timestamp = None
                    snap.changelog.append(Change(
                        kind="expired",
                        text=f"public catalog {provider.slug}: free plan no longer backs {model.model_id}",
                    ))
    return added


def ingest_openrouter_providers(snap: Snapshot, taken_ids: set[str],
                                taken_slugs: set[str], md_raw: dict | None) -> int:
    """Mine https://openrouter.ai/providers for upstream providers that
    advertise free models we don't catalog yet.

    For each unknown card with freeModelCount > 0:
      1. resolve a direct API base via models.dev's provider entry
         (`api` field), if one exists;
      2. probe `<base>/models`:
         - public JSON list → promoted and its models ingested next run;
         - gated (401/403 / login page) → still promoted, flagged
           probe_status="needs_key" so the UI shows the KEY? badge and
           the changelog names the env var to set (same treatment as
           experiential-labs);
         - anything else (dead, non-OpenAI-compatible) → logged as a
           candidate for human review instead.
    Never removes anything."""
    try:
        cards = sources.openrouter_providers.fetch(timeout=25.0)
    except Exception as e:
        snap.changelog.append(Change(kind="verified", text=f"openrouter-providers fetch failed: {e}"))
        return 0
    if not cards:
        return 0

    # models.dev provider lookup by slug/id -> api base + key env name
    md_by_id: dict[str, dict] = {}
    for prov_id, prov in (md_raw or {}).items():
        md_by_id[prov_id.lower()] = prov or {}

    promoted = 0
    candidates: list[str] = []
    for card in cards:
        if card.get("free", 0) <= 0:
            continue
        slug, name = card["slug"], card["name"]
        if sources.openrouter_providers.match_known(slug, name, snap.providers):
            continue
        label = f"{name} (openrouter upstream, {card['free']} free models)"
        md_entry = md_by_id.get(slug.lower()) or md_by_id.get(slug.replace("-", "").lower()) or {}
        base = md_entry.get("api")
        if not base:
            candidates.append(label)
            continue
        status, rows = sources.openai_compat.fetch_models(base, timeout=10.0)
        if status not in ("ok", "needs_key", "gated") or (status == "ok" and not rows):
            candidates.append(f"{label} — endpoint {base} answered '{status}'")
            continue
        host = base.split("//", 1)[-1].split("/", 1)[0]
        prov = promote.make_provider(
            {"host": host, "name": name, "source": "openrouter providers directory"},
            taken_ids, taken_slugs,
        )
        if not prov:
            continue
        prov.api_base = base
        prov.homepage = promote.homepage_from_host(base)
        env_names = md_entry.get("env") or []
        prov.api_key_env = env_names[0] if env_names else None
        if status != "ok":
            prov.probe_status = "needs_key"
        snap.providers.append(prov)
        promoted += 1
        if status == "ok":
            snap.changelog.append(Change(
                kind="added",
                text=f"promoted {prov.name} from openrouter providers directory ({len(rows)} models at {base})",
            ))
        else:
            env_hint = prov.api_key_env or "a provider API key"
            snap.changelog.append(Change(
                kind="added",
                text=f"promoted {prov.name} (gated) from openrouter providers directory — "
                     f"{card['free']} free models advertised; set {env_hint} to verify",
            ))
    if candidates:
        sample = "; ".join(candidates[:6]) + ("…" if len(candidates) > 6 else "")
        snap.changelog.append(Change(
            kind="verified",
            text=f"openrouter-providers candidates for review: {sample}",
        ))
    return promoted


def ingest_xkiro(snap: Snapshot) -> int:
    """Pull Xkiro's public tiered /v1/models. Free classification is
    source-declared (access_tier=free or pricing 0/0), paid rows carry
    explicit per-1M pricing which is backfilled onto the row."""
    try:
        rows = sources.xkiro.fetch(timeout=20.0)
    except Exception as e:
        snap.changelog.append(Change(kind="verified", text=f"xkiro fetch failed: {e}"))
        return 0
    added = 0
    free_n = 0
    live_free: set[str] = set()
    for row in rows:
        mid = str(row.get("id") or "")
        if not mid:
            continue
        is_f = sources.xkiro.is_free(row)
        if is_f:
            live_free.add(mid.casefold())
        ctx = sources.xkiro.context_window(row)
        if _add_model(snap, "p_xkiro", mid, sources.xkiro.display_name(row),
                      modality=["chat"], is_free=is_f,
                      free_kind="free_tier" if is_f else "byok_required",
                      free_limit="xkiro free tier (source-declared)" if is_f else "",
                      context_window=ctx,
                      free_evidence_source="xkiro" if is_f else None,
                      free_evidence_timestamp=now() if is_f else None):
            added += 1
        if is_f:
            free_n += 1
        # Backfill explicit pricing for paid rows (unit is per-1M tokens).
        if sources.xkiro.is_paid(row):
            for m in snap.models:
                if (m.provider_id == "p_xkiro"
                        and m.model_id.casefold() == mid.casefold()):
                    pr = row.get("pricing") or {}
                    try:
                        m.input_per_1m = float(pr.get("input"))
                        m.output_per_1m = float(pr.get("output"))
                        m.cache_read_per_1m = float(pr["cache_read"])
                    except (KeyError, TypeError, ValueError):
                        pass
                    break
    # A source-declared xkiro free claim can't outlive the live tier
    # listing either; probe-verified rows are kept.
    delisted = _demote_missing_free(snap, "p_xkiro", "xkiro", live_free,
                                    "[delisted by Xkiro]")
    if delisted:
        snap.changelog.append(Change(
            kind="expired",
            text=f"xkiro: {len(delisted)} free models delisted — free flags removed",
        ))
    snap.changelog.append(Change(
        kind="verified",
        text=f"xkiro: {free_n} free (source-declared), {len(rows) - free_n} paid/premium listed",
    ))
    return added


def ingest_bai(snap: Snapshot) -> int:
    """Ingest b.ai's published catalog. Every row stays on the b.ai
    provider — the prices and free tier are b.ai's gateway offer, and
    mapping rows onto upstream providers (a DeepSeek row landing on
    p_deepseek) wrongly presented them as api.deepseek.com offerings.

    Note: b.ai's `/v1/models` is gated. We use the static CATALOG from
    the bai source unless BAI_API_KEY is set, in which case the live
    list is fetched and takes precedence."""
    rows = sources.bai.all_rows()
    if not rows:
        return 0

    added = 0
    for row in rows:
        mid = sources.bai.to_model_id(row)
        is_f = sources.bai.is_free(row)
        if _add_model(
            snap,
            "p_bai",
            mid,
            row.get("display") or mid,
            modality=row.get("modalities") or ["chat"],
            is_free=is_f,
            free_kind="free_tier" if is_f else "byok_required",
            free_limit="b.ai $0/M verified" if is_f else "via b.ai",
            context_window=row.get("context_window"),
            free_evidence_source="bai" if is_f else None,
            free_evidence_timestamp=now() if is_f else None,
        ):
            added += 1
        # Attach pricing to the just-added (or existing) row — and make
        # the free flag follow the current evidence. b.ai reprices its
        # catalog; a model free last month may be paid today, so the
        # flag can never outlive the prices it was based on.
        for m in snap.models:
            if m.provider_id == "p_bai" and m.model_id.casefold() == mid.casefold():
                # None prices (repriced/credit-gated rows) stay None — the
                # model renders as unverified instead of a fake $0.
                m.input_per_1m = float(row["input"]) if row.get("input") is not None else None
                m.output_per_1m = float(row["output"]) if row.get("output") is not None else None
                m.cache_read_per_1m = float(row["cache_read"]) if row.get("cache_read") is not None else None
                m.cache_write_per_1m = float(row["cache_write"]) if row.get("cache_write") is not None else None
                now_free = sources.bai.is_free(row)
                if now_free != m.is_free:
                    m.is_free = now_free
                    m.free_kind = "free_tier" if now_free else "byok_required"
                    m.free_limit = "b.ai $0/M verified" if now_free else "via b.ai"
                    if now_free:
                        m.free_evidence_source = "bai"
                        m.free_evidence_timestamp = now()
                    else:
                        m.free_evidence_source = None
                        m.free_evidence_timestamp = None
                break
    return added


def _extend_flagships_from_bai(snap: Snapshot) -> None:
    """For every model that has b.ai-supplied pricing (input > 0 and
    output > 0), add it to the cheap-flagships leaderboard if it's
    below the $20/M-out ceiling."""
    from .models import CheapFlagship
    existing = {(f.model_id, f.provider) for f in snap.cheap_flagships}
    for m in snap.models:
        if m.input_per_1m is None or m.output_per_1m is None:
            continue
        if m.input_per_1m == 0 and m.output_per_1m == 0:
            continue
        if m.output_per_1m > 20.0:
            continue
        provider = next((p for p in snap.providers if p.id == m.provider_id), None)
        if not provider:
            continue
        if (m.model_id, provider.name) in existing:
            continue
        snap.cheap_flagships.append(CheapFlagship(
            rank=0,
            model_id=m.model_id,
            display_name=m.display_name,
            provider=provider.name,
            input_per_1m=m.input_per_1m,
            output_per_1m=m.output_per_1m,
            context_window=m.context_window,
        ))
    # Re-rank and trim.
    snap.cheap_flagships.sort(key=lambda f: (f.input_per_1m + 3 * f.output_per_1m, f.output_per_1m))
    for i, f in enumerate(snap.cheap_flagships[:50], start=1):
        f.rank = i
    snap.cheap_flagships = snap.cheap_flagships[:50]


def ingest_huggingface(snap: Snapshot) -> int:
    try:
        rows = sources.huggingface.fetch(timeout=30.0)
    except Exception as e:
        snap.changelog.append(Change(kind="verified", text=f"huggingface fetch failed: {e}"))
        return 0
    added = 0
    live_free: set[str] = set()
    for m in rows:
        if not sources.huggingface.is_free_via_provider(m):
            continue
        mid = str(m.get("id") or m.get("name") or "")
        if not mid:
            continue
        live_free.add(mid.casefold())
        ctx = sources.huggingface.context_window(m)
        if _add_model(snap, "p_hf", mid, mid, modality=["chat"],
                      is_free=True, free_kind="free_tier",
                      free_limit="HF free tier (token-gated)",
                      context_window=ctx,
                      free_evidence_source="huggingface",
                      free_evidence_timestamp=now()):
            added += 1
    # Same invariant as OpenRouter: an HF free claim can't outlive the
    # live listing. Probe-verified rows are kept.
    delisted = _demote_missing_free(snap, "p_hf", "huggingface", live_free,
                                    "[delisted by HuggingFace]")
    if delisted:
        snap.changelog.append(Change(
            kind="expired",
            text=f"huggingface: {len(delisted)} free models delisted — free flags removed",
        ))
    return added


def _demote_missing_free(snap: Snapshot, provider_id: str, evidence: str,
                         live_ids: set[str], note: str) -> list[str]:
    """Flip is_free off for rows whose free claim rests on `evidence` but
    whose model id is absent from the source's live listing this run.
    Rows with independent ground truth (1-token probe) are never touched.
    Returns the demoted model ids (for the changelog)."""
    demoted: list[str] = []
    for m in snap.models:
        if m.provider_id != provider_id or not m.is_free:
            continue
        if m.free_evidence_source != evidence or m.free_verified_at:
            continue
        if m.model_id.casefold() in live_ids:
            continue
        m.is_free = False
        m.free_kind = "byok_required"
        m.free_limit = note
        m.free_evidence_source = None
        m.free_evidence_timestamp = None
        demoted.append(m.model_id)
    return demoted


def ingest_models_dev(snap: Snapshot) -> tuple[int, list[CheapFlagship], dict]:
    """Cross-reference pricing and build the cheap-flagships leaderboard."""
    try:
        raw = sources.models_dev.fetch(timeout=30.0)
    except Exception as e:
        snap.changelog.append(Change(kind="verified", text=f"models.dev fetch failed: {e}"))
        return 0, [], {}

    # Build a quick lookup: provider_id -> set of known model_ids.
    known_models: dict[str, set[str]] = {}
    for m in snap.models:
        known_models.setdefault(m.provider_id, set()).add(m.model_id.lower())

    flagships: list[CheapFlagship] = []
    backfilled = 0
    for prov_id, prov in raw.items():
        prov_models = (prov or {}).get("models") or {}
        # Match models.dev provider to our catalog by name or by id.
        ours = _match_models_dev_provider(snap, prov_id, prov)
        for mid, mdl in prov_models.items():
            cost = (mdl or {}).get("cost") or {}
            try:
                inp = float(cost.get("input") or 0)
                out = float(cost.get("output") or 0)
            except (TypeError, ValueError):
                continue
            # Backfill context window for known models.
            if ours:
                for m in snap.models:
                    if m.provider_id == ours.id and m.model_id.lower() == mid.lower():
                        if not m.context_window and mdl.get("limit"):
                            try:
                                m.context_window = int(mdl["limit"].get("context"))
                            except (TypeError, ValueError, KeyError, AttributeError):
                                pass
                        backfilled += 1
            # Cheap-flagship candidate.
            if ours and sources.models_dev.is_cheap_flagship(mdl):
                ctx = None
                try:
                    ctx = int(((mdl.get("limit") or {}).get("context")))
                except (TypeError, ValueError):
                    ctx = None
                flagships.append(CheapFlagship(
                    rank=0,  # rank assigned after sort
                    model_id=mid,
                    display_name=mdl.get("name") or mid,
                    provider=ours.name,
                    input_per_1m=inp,
                    output_per_1m=out,
                    context_window=ctx,
                ))
    # Rank and trim the leaderboard.
    flagships.sort(key=lambda f: (f.input_per_1m + 3 * f.output_per_1m, f.output_per_1m))
    for i, f in enumerate(flagships[:25], start=1):
        f.rank = i
    return backfilled, flagships[:25], raw


def _match_models_dev_provider(snap: Snapshot, models_dev_id: str, models_dev_obj: dict):
    """Return our Provider row that corresponds to a models.dev provider, or None.

    Excludes subscription-PLAN entries ("...-coding-plan", names containing
    "plan"): models.dev prices their models at $0 because the models are
    bundled in a paid plan — that's not a free API tier, and matching them
    to our open-API providers wrongly promoted paid models to free."""
    name = (models_dev_obj or {}).get("name", models_dev_id).lower()
    if "plan" in name or models_dev_id.endswith("-plan") or "coding-plan" in models_dev_id:
        return None
    for p in snap.providers:
        if p.name.lower().split(" ")[0] in name or models_dev_id in p.id.lower():
            return p
        if p.name.lower() == name:
            return p
    return None


def ingest_community_lists(snap: Snapshot, taken_ids: set[str], taken_slugs: set[str]) -> int:
    """Reap GitHub READMEs and probe each candidate's /v1/models."""
    items = sources.community_lists.fetch_all()
    if not items:
        return 0
    cands = sources.community_lists.extract_candidates(items)
    known_hosts = {p.homepage_host() for p in snap.providers}
    promoted = 0
    for c in cands:
        host = c["host"]
        if host in known_hosts:
            continue
        # Probe: does it have a /v1/models endpoint?
        ok = sources.openai_compat.verify_openai_compatible(f"https://{host}/v1", timeout=4.0)
        if not ok:
            continue
        prov = promote.make_provider(c, taken_ids, taken_slugs)
        if not prov:
            continue
        snap.providers.append(prov)
        known_hosts.add(host)
        promoted += 1
        snap.changelog.append(Change(kind="added", text=f"auto-promoted {prov.name} (host={host}) from {c.get('source')}"))
    return promoted


def ingest_submissions(snap: Snapshot) -> int:
    f = _data_dir() / "submissions.jsonl"
    if not f.exists():
        return 0
    processed = 0
    new_lines: list[str] = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("{"):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                new_lines.append(line)
                continue
            if obj.get("_note"):
                # placeholder line we wrote ourselves
                new_lines.append(line)
                continue
            if obj.get("_processed"):
                new_lines.append(line)
                continue
            snap.changelog.append(Change(
                kind="submit",
                text=f"submission: {obj.get('provider_name','?')} ({obj.get('source_url','')})",
            ))
            processed += 1
            obj["_processed"] = True
            new_lines.append(json.dumps(obj))
        else:
            new_lines.append(line)
    f.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))
    return processed


def ingest_search(snap: Snapshot) -> int:
    if not any(os.environ.get(k) for k in ("BRAVE_SEARCH_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY")):
        return 0
    queries = [
        "new free LLM API 2026 launch",
        "free AI API tier launch",
        "OpenAI compatible free API provider",
    ]
    noted = 0
    for q in queries:
        hits = sources.search.search_new_free_apis(q)
        for h in hits[:3]:
            url = h.get("url") or h.get("link") or h.get("href") or ""
            title = h.get("title") or ""
            if url:
                snap.changelog.append(Change(kind="submit", text=f"search hit: {title} — {url}"))
                noted += 1
    return noted


# ----------------------------- verifier step -------------------------------

def ingest_verifier(snap: Snapshot, cfg_verifier: dict | None = None) -> tuple[int, int, int]:
    """Run the LLM verifier over candidate models/providers and (gated by
    cross-check + budget) apply the only mutation the verifier is allowed
    to make: flipping is_free True → False on a Model whose free tier
    expired.

    Provider credentials are read from data/.verifier-secrets.json by name
    (primary_provider / secondary_provider in cfg_verifier). If neither
    is set, falls back to env vars. The per-run budget is the env var
    OPENRADAR_VERIFIER_BUDGET_PER_RUN (default 50); no longer configurable
    from the UI by design.

    Every verdict is recorded as a Change(kind="verifier", ...) with the
    JSON payload in text — the snapshot mutation is the side effect of a
    verdict=expire on a model that was already is_free=True, AND only
    when cfg_verifier["auto_apply_expire"] is true.

    Returns (n_verdicts, n_expired, n_rebranded).
    """
    import json as _json

    cv = cfg_verifier or {}
    auto_apply = bool(cv.get("auto_apply_expire", True))
    try:
        threshold = float(cv.get("expire_confidence_threshold", 0.7))
    except (TypeError, ValueError):
        threshold = 0.7

    primary_name = (cv.get("primary_provider") or "").strip()
    secondary_name = (cv.get("secondary_provider") or "").strip()

    client = sources.verifier.LLMClient(
        cfg_verifier=cv,
        provider_name=primary_name or None,
    )
    if not client.has_key():
        snap.changelog.append(Change(
            kind="verifier",
            text="verifier disabled: no LLM key configured "
                 "(add a provider in Settings → Intelligence, "
                 "or set OPENAI_API_KEY / ANTHROPIC_API_KEY on the server)",
        ))
        return (0, 0, 0)

    # Build a secondary client for the cross-check pass — different
    # provider if the operator picked one, otherwise the same client.
    if secondary_name and secondary_name.lower() != primary_name.lower():
        secondary_client = sources.verifier.LLMClient(
            cfg_verifier=cv,
            provider_name=secondary_name,
        )
    else:
        secondary_client = None  # cross_check will reuse the primary

    budget = sources.verifier._budget()
    if budget <= 0:
        snap.changelog.append(Change(
            kind="verifier",
            text="verifier disabled: OPENRADAR_VERIFIER_BUDGET_PER_RUN is 0",
        ))
        return (0, 0, 0)

    n_verdicts = n_expired = n_rebranded = 0

    # Build a quick lookup: provider_id -> Provider
    providers_by_id = {p.id: p for p in snap.providers}

    # 1. Free-tier audits: every model that the snapshot currently
    # believes is free. Skip ones that already have explicit
    # free_kind=trial_card (we don't second-guess operator-set values).
    free_models = [m for m in snap.models if m.is_free and m.free_kind != "trial_card"]

    for m in free_models:
        if budget <= 0:
            snap.changelog.append(Change(
                kind="verifier",
                text="verifier budget exhausted; remaining candidates skipped",
            ))
            return (n_verdicts, n_expired, n_rebranded)
        provider = providers_by_id.get(m.provider_id)
        if not provider or not provider.api_base:
            continue
        budget -= 1
        verdict = sources.verifier.judge_free_tier(m, provider, client=client)
        verdict = sources.verifier.cross_check(verdict, model=m, provider=provider,
                                               client=client, cfg_verifier=cv,
                                               secondary_client=secondary_client)
        n_verdicts += 1
        snap.changelog.append(Change(kind="verifier", text=_json.dumps(verdict.model_dump(), ensure_ascii=False)))
        if (verdict.verdict == "expire"
                and verdict.confidence >= threshold
                and auto_apply):
            m.is_free = False
            m.free_kind = "trial_card"
            m.free_limit = (m.free_limit or "") + " [verifier: expired]"
            m.free_evidence_source = "verifier"
            m.free_evidence_timestamp = now()
            n_expired += 1
        elif verdict.verdict == "expire" and not auto_apply:
            # Recorded in changelog above; no mutation because policy is advisory.
            pass

    # 2. Liveness audits: only providers that are already flagged stale.
    stale_providers = [p for p in snap.providers if p.status == "stale"]
    for p in stale_providers:
        if budget <= 0:
            snap.changelog.append(Change(
                kind="verifier",
                text="verifier budget exhausted; remaining liveness candidates skipped",
            ))
            return (n_verdicts, n_expired, n_rebranded)
        budget -= 1
        verdict = sources.verifier.judge_liveness(p, client=client)
        verdict = sources.verifier.cross_check(verdict, provider=p,
                                               client=client, cfg_verifier=cv,
                                               secondary_client=secondary_client)
        n_verdicts += 1
        snap.changelog.append(Change(kind="verifier", text=_json.dumps(verdict.model_dump(), ensure_ascii=False)))
        # Liveness verdicts are advisory only — we never auto-remove or
        # auto-rebrand. Only "expire" is recorded as a rebrand candidate
        # for human review.
        if verdict.verdict == "rebrand" and verdict.proposed_delta:
            n_rebranded += 1

    return (n_verdicts, n_expired, n_rebranded)


# ----------------------------- 1-token probe step ---------------------------

def ingest_probe(snap: Snapshot, cfg: dict) -> tuple[int, int, int]:
    """Ground-truth free classification via 1-token completions.

    For every provider with a configured API key, probe models whose
    free status is unverified or unknown (never rows with explicit
    pricing, never already-verified rows). Success upgrades the row to
    is_free=True with free_verified_at set; a 402/403/404 on a
    claimed-free row flips it off and logs the overturn.

    Budget: cfg sources.probe.max_probes_per_provider (default 40) and
    agent.probe_budget_per_run (default 300) — a probe costs at most a
    token or two, but the cap keeps a bad config from burning a paid key.
    Returns (n_free_verified, n_overturned, n_inconclusive)."""
    per_provider_cap = int(cfg["sources"].get("probe", {}).get("max_probes_per_provider", 40))
    budget = int(cfg["agent"].get("probe_budget_per_run", 300))
    if budget <= 0 or per_provider_cap <= 0:
        return (0, 0, 0)

    tot_free = tot_overturn = tot_inconclusive = 0
    for p in snap.providers:
        if budget <= 0:
            snap.changelog.append(Change(
                kind="verified",
                text=f"probe: run budget exhausted; {p.slug} and later providers skipped",
            ))
            break
        if p.probe_status != "ok" or not p.api_key_env:
            # No working authenticated session with this provider —
            # probes would 401 across the board.
            continue
        key = provider_keys.get(p.api_key_env)
        if not key:
            continue
        pms = [m for m in snap.models if m.provider_id == p.id]
        candidates_before = sum(
            1 for m in pms
            if sources.probe._is_probe_candidate(m)
            and not (m.is_free and m.free_verified_at)
            and m.input_per_1m is None and m.output_per_1m is None
        )
        if candidates_before == 0:
            continue
        cap = min(per_provider_cap, budget)
        n_free, n_paid, n_inc = sources.probe.probe_provider_models(
            pms, p, key, max_probes=cap,
        )
        budget -= n_free + n_paid  # inconclusive probes don't burn budget
        tot_free += n_free
        tot_overturn += n_paid
        tot_inconclusive += n_inc
        if n_free or n_paid:
            snap.changelog.append(Change(
                kind="verified",
                text=f"probe {p.slug}: {n_free} verified free (1-token), "
                     f"{n_paid} confirmed paid/gone, {n_inc} inconclusive",
            ))
    return (tot_free, tot_overturn, tot_inconclusive)


# ----------------------------- main loop -----------------------------------

def _mark_stale_providers(snap: Snapshot) -> int:
    """Mark providers as stale after consecutive runs with 0 models + error probe.
    
    A provider is marked stale when:
    - It has 0 models in the snapshot
    - Its probe_status is 'error' (not just 'needs_key' or 'gated')
    - This has persisted for STALE_THRESHOLD_RUNS consecutive runs
    
    We track this via a hidden field in provider.notes (stale_count:N).
    Returns number of providers newly marked stale."""
    marked = 0
    for p in snap.providers:
        if p.status != "active":
            continue
        # Count models for this provider
        model_count = sum(1 for m in snap.models if m.provider_id == p.id)
        if model_count > 0:
            # Reset counter if provider has models
            if "stale_count:" in (p.notes or ""):
                import re
                p.notes = re.sub(r"stale_count:\d+", "stale_count:0", p.notes)
            continue
        if p.probe_status != "error":
            # Not an error (could be needs_key, gated, ok, skipped) - don't mark stale
            continue
        # Increment stale counter
        import re
        notes = p.notes or ""
        match = re.search(r"stale_count:(\d+)", notes)
        count = int(match.group(1)) + 1 if match else 1
        if match:
            notes = re.sub(r"stale_count:\d+", f"stale_count:{count}", notes)
        else:
            notes = (notes + f" | stale_count:{count}").strip(" |")
        p.notes = notes
        if count >= STALE_THRESHOLD_RUNS:
            p.status = "stale"
            snap.changelog.append(Change(
                kind="verified",
                text=f"provider {p.slug} marked stale after {count} consecutive runs with 0 models + error probe",
            ))
            marked += 1
    return marked


def run(once: bool = False) -> Snapshot:
    started = time.time()
    snap = load_existing()
    snap.snapshot_at = now()
    cfg = agent_config.load()
    taken_ids = {p.id for p in snap.providers}
    taken_slugs = {p.slug for p in snap.providers}

    snap.changelog.append(Change(kind="verified", text="agent run started"))

    # 1. Per-provider /v1/models — known providers
    if cfg["sources"].get("provider_endpoints", {}).get("enabled", True):
        n1 = ingest_provider_endpoints(snap)
        snap.changelog.append(Change(kind="verified", text=f"per-provider /v1/models: merged {n1} new models"))
    else:
        n1 = 0

    # 2. OpenRouter :free harvest
    if cfg["sources"].get("openrouter", {}).get("enabled", True):
        n2 = ingest_openrouter(snap, taken_ids, taken_slugs)
        snap.changelog.append(Change(kind="verified", text=f"openrouter :free: added {n2} models"))
    else:
        n2 = 0

    # 3. Hugging Face router
    if cfg["sources"].get("huggingface", {}).get("enabled", True):
        n3 = ingest_huggingface(snap)
        snap.changelog.append(Change(kind="verified", text=f"huggingface free: added {n3} models"))
    else:
        n3 = 0

    # 3b. b.ai catalog
    if cfg["sources"].get("bai_static", {}).get("enabled", True):
        n3b = ingest_bai(snap)
        snap.changelog.append(Change(kind="verified", text=f"b.ai: added {n3b} models"))
    else:
        n3b = 0

    # 3c. Xkiro tiered gateway
    if cfg["sources"].get("xkiro", {}).get("enabled", True):
        ingest_xkiro(snap)
    n3c = 0

    # 4. models.dev cross-reference + cheap-flagships leaderboard
    if cfg["sources"].get("models_dev", {}).get("enabled", True):
        n4, flagships, raw_md = ingest_models_dev(snap)
        snap.cheap_flagships = flagships
        # 4b. Promote $0-cost models to is_free=True based on models.dev,
        # scoped to the same provider; repair false free flags from the
        # old cross-provider matcher.
        n4b, n4c = _infer_free_from_models_dev(snap, raw_md)
        snap.changelog.append(Change(kind="pricing", text=f"models.dev: backfilled {n4} models, promoted {n4b} to free, repaired {n4c} false free flags, leaderboard has {len(flagships)} entries"))

        # 4c. Add b.ai-priced models to the cheap-flagships leaderboard.
        _extend_flagships_from_bai(snap)

        # 4d. OpenRouter providers-directory discovery — new upstreams
        # advertising free models. Needs models.dev raw for endpoint hints.
        if cfg["sources"].get("openrouter_providers", {}).get("enabled", True):
            n_orp = ingest_openrouter_providers(snap, taken_ids, taken_slugs, raw_md)
            if n_orp:
                snap.changelog.append(Change(
                    kind="added",
                    text=f"openrouter providers directory: promoted {n_orp} new providers",
                ))

        # 4e. models.dev catalog seeding: for providers we can't list
        # live (gated / unreachable), pull the same-provider models.dev
        # entries as rows with explicit pricing. These are catalog
        # listings, not free claims — is_free stays False unless the
        # entry itself prices at 0/0 (handled by 4b's promotion pass).
        n_seed = seed_models_from_models_dev(snap, raw_md)
        if n_seed:
            snap.changelog.append(Change(
                kind="added",
                text=f"models.dev seeding: added {n_seed} catalog rows for gated/unreachable providers",
            ))
    else:
        snap.changelog.append(Change(kind="pricing", text="models.dev source disabled by config"))

    ingest_public_catalog(snap)

    # 5. Community list promotion
    if cfg["agent"].get("include_community_lists", True) and \
       cfg["sources"].get("community_lists", {}).get("enabled", True):
        n5 = ingest_community_lists(snap, taken_ids, taken_slugs)
        snap.changelog.append(Change(kind="added", text=f"community-list promotion: {n5} new providers"))
    else:
        n5 = 0

    # 5a. LLM orchestrator — when enabled, the LLM decides what to
    # investigate this run and dispatches scraper/judge tasks. Default
    # off; same opt-in posture as the verifier.
    if cfg["agent"].get("llm_orchestration_enabled", False):
        from . import orchestrator
        primary = (cfg.get("verifier", {}) or {}).get("primary_provider", "")
        secondary = (cfg.get("verifier", {}) or {}).get("secondary_provider", "")
        orchestrator.run_orchestrator(snap, primary_provider=primary, secondary_provider=secondary)

    # 5b. LLM verifier — re-checks claims made by earlier steps.
    # Default off in config; only runs if explicitly enabled and a key is set.
    # The new top-level `verifier.enabled` flag is authoritative; the legacy
    # `sources.verifier.enabled` still works for older config.json files.
    cv = cfg.get("verifier", {}) or {}
    legacy_enabled = cfg.get("sources", {}).get("verifier", {}).get("enabled", False)
    verifier_enabled = bool(cv.get("enabled", legacy_enabled))
    if verifier_enabled:
        n_verifier, n_expired, n_rebranded = ingest_verifier(snap, cfg_verifier=cv)
        snap.changelog.append(Change(
            kind="verifier",
            text=f"verifier: {n_verifier} verdicts ({n_expired} expired, {n_rebranded} rebranded)",
        ))
    else:
        pass  # noop: verifier off

    # 6. Submissions inbox
    n6 = ingest_submissions(snap)
    if n6:
        snap.changelog.append(Change(kind="submit", text=f"processed {n6} public submissions"))

    # 7. Search APIs (optional)
    if cfg["agent"].get("include_search_apis", True) and \
       cfg["sources"].get("search_apis", {}).get("enabled", True):
        n7 = ingest_search(snap)
    else:
        n7 = 0

    # 7b. 1-token probe — ground-truth free classification for providers
    # whose /v1/models is gated behind a key. Runs after all ingestion
    # so it sees every discovered row; before the final recompute so
    # counts reflect probe verdicts.
    if cfg["sources"].get("probe", {}).get("enabled", True):
        n_free, n_over, n_inc = ingest_probe(snap, cfg)
        if n_free or n_over or n_inc:
            snap.changelog.append(Change(
                kind="verified",
                text=f"1-token probe: {n_free} verified free, {n_over} overturned, {n_inc} inconclusive",
            ))

    # 8. Mark stale providers: consecutive runs with 0 models + error probe
    _mark_stale_providers(snap)

    # 9. Hard invariant first: paid prices must never coexist with a
    # free flag — then recompute every provider's free_model_count from
    # the actual model list. This catches cases where a later step
    # flipped a row to is_free=True after the in-loop count was set.
    enforce_pricing_consistency(snap)
    recompute_free_counts(snap)

    snap.changelog.append(Change(kind="verified", text=f"agent run finished in {time.time()-started:.1f}s"))

    write(snap)
    return snap


def main() -> int:
    snap = run()
    print(
        f"wrote {len(snap.providers)} providers, {len(snap.models)} models, "
        f"{len(snap.cheap_flagships)} flagships, {len(snap.changelog)} changelog entries"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
