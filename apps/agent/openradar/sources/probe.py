"""1-token live probe: the ground-truth free-tier classifier.

`/v1/models` lists what exists; it does not say what a free account can
actually call without paying. The only reliable way to know — behind a
login wall or not — is to send a minimal chat completion and look at the
billing signal in the response:

  HTTP 200 + usage tokens  → the model served the request → free to call
                             on this account → is_free = True (verified)
  402 / 403 (quota/billing)→ the model exists but costs money → paid
  404 / model_not_found    → the model id is gone from the live API
  network/5xx/429          → inconclusive; leave the row untouched

Every probe uses max_tokens=1 and a trivial prompt, so a successful call
costs a fraction of a cent on paid tiers and nothing on free ones. The
whole step is capped (provider cap + global budget) so a runaway run
can't burn through a paid key.
"""
from __future__ import annotations
import httpx

from ..models import Model, Provider, now

PROBE_TIMEOUT = 20.0
# An inconclusive result (network error, 429, 5xx) is retried once before
# we give up and leave the model untouched.
RETRY_INCONCLUSIVE = 1

# Response shapes that mean "no such model" rather than "not free".
_MODEL_NOT_FOUND_MARKERS = (
    "model_not_found",
    "does not exist",
    "not found",
    "unknown model",
    "invalid model",
    "no such model",
    "decommissioned",
)


class ProbeResult:
    __slots__ = ("outcome", "detail")

    def __init__(self, outcome: str, detail: str = ""):
        self.outcome = outcome  # free | paid | missing | inconclusive
        self.detail = detail


def probe_model(base_url: str, model_id: str, api_key: str,
                *, timeout: float = PROBE_TIMEOUT) -> ProbeResult:
    """Send one 1-token chat completion. Classify the billing outcome."""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }
    for attempt in range(RETRY_INCONCLUSIVE + 1):
        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        except httpx.HTTPError:
            return ProbeResult("inconclusive", "network error")
        if r.status_code == 200:
            # Confirm the body looks like a completion, not an error
            # envelope dressed up as 200.
            try:
                body = r.json()
            except Exception:
                return ProbeResult("inconclusive", "non-JSON 200")
            if isinstance(body, dict) and body.get("error"):
                return ProbeResult("inconclusive", str(body["error"])[:120])
            return ProbeResult("free", "1-token completion succeeded")
        if r.status_code == 404:
            text = (r.text or "").lower()
            return ProbeResult("missing", text[:120])
        if r.status_code in (402, 403):
            return ProbeResult("paid", (r.text or "")[:120])
        if r.status_code == 401:
            # Key rejected entirely — every further probe on this
            # provider would say the same thing.
            return ProbeResult("inconclusive", "401 unauthorized")
        if r.status_code == 400:
            # Some gateways (b.ai) reject an unaffordable model with a
            # 400 instead of a 402: "credit insufficient balance ...
            # required=102" / "Deposit required to unlock premium
            # models". That's a definitive paywall verdict, not a bad
            # request shape — without this, repriced models stay
            # "inconclusive" forever and stale free claims survive.
            text = (r.text or "").lower()
            if any(k in text for k in ("insufficient balance", "credit", "deposit", "balance=")):
                return ProbeResult("paid", (r.text or "")[:120])
        if r.status_code == 429 or r.status_code >= 500:
            if attempt < RETRY_INCONCLUSIVE:
                continue
            return ProbeResult("inconclusive", f"HTTP {r.status_code}")
        # 400 etc — provider rejected the request shape; can't classify.
        return ProbeResult("inconclusive", f"HTTP {r.status_code}: {(r.text or '')[:120]}")
    return ProbeResult("inconclusive", "unreachable")


def probe_provider_models(models: list[Model], provider: Provider, api_key: str,
                          *, max_probes: int) -> tuple[int, int, int]:
    """Probe up to max_probes unclassified models on one provider, in place.

    Only rows whose free status is unknown or unverified are probed:
      - is_free=True without free_verified_at (claim from docs/lists —
        the 1-token result upgrades it to verified or overturns it)
      - is_free=False with no pricing (the /v1/models default — the
        probe is the only signal these rows will ever get)
    Rows with explicit pricing, or is_free=True already probe-verified,
    are never touched (respect_b_ai_pricing discipline).

    Returns (n_free_verified, n_confirmed_paid_or_missing, n_inconclusive).
    """
    n_free = n_paid = n_inconclusive = 0
    for m in models:
        if n_free + n_paid >= max_probes:
            break
        already_verified = m.is_free and m.free_verified_at
        has_pricing = m.input_per_1m is not None or m.output_per_1m is not None
        if already_verified or has_pricing:
            continue
        if not _is_probe_candidate(m):
            continue
        res = probe_model(provider.api_base, m.model_id, api_key)
        if res.outcome == "free":
            m.is_free = True
            m.free_verified_at = now()
            m.free_evidence_source = "probe"
            m.free_evidence_timestamp = now()
            if m.free_kind in ("byok_required", "free_tier"):
                m.free_kind = "free_tier"
            m.free_limit = (m.free_limit or "") + " [1-token probe verified]".strip()
            n_free += 1
        elif res.outcome in ("paid", "missing"):
            if m.is_free:
                # A claimed-free model that answers 402/403/404 — record
                # the overturn in the row itself; the changelog entry is
                # written by the caller.
                m.is_free = False
                m.free_kind = "trial_card"
                m.free_evidence_source = "probe"
                m.free_evidence_timestamp = now()
            m.free_limit = (m.free_limit or "") + f" [probe: {res.outcome}]".strip()
            n_paid += 1
        else:
            n_inconclusive += 1
    return n_free, n_paid, n_inconclusive


def _is_probe_candidate(m: Model) -> bool:
    """Rows worth spending a probe on must include the chat modality —
    the 1-token probe is a chat completion and can't classify
    embeddings/image/audio endpoints."""
    return "chat" in (m.modality or [])

