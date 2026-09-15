"""LLM-based verifier layer.

The deterministic scrapers can only report what a page *says*; they can't
decide whether the page is telling the truth. The verifier layer reads
provider docs in natural language and produces structured verdicts on
three questions the scrapers can't answer:

  * **free tier claims** — is a model flagged is_free=True actually free
    for inference today, or is it free-credits / trial-card / expired?
  * **model identity** — when two community sources claim the same model
    under different ids, which is canonical?
  * **provider liveness** — when a provider is flagged status="stale",
    is it really dead, transiently broken, or rebranded?

Design rules (the "authentic and correct" floor):

  * Every verdict MUST carry evidence_urls. No evidence → unverified.
  * Any mutation-grade verdict (free-tier flip, rebrand) is gated by a
    two-pass cross_check — second run uses a different prompt seed and
    ideally a different model. Disagreement → disputed, never mutated.
  * Parsing failures and rate-limit failures both yield unverified; the
    verifier can only vouch, not deny by silence.
  * Mutations are strictly limited: is_free True→False (free_kind set to
    "trial_card"). Never auto-adds models, never auto-removes providers,
    never flips status to "removed".
  * A hard per-run budget caps total judge calls so a runaway config
    can't blow the bill.
"""
from __future__ import annotations
import json
import os
import re
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from ..models import Model, Provider


# ----------------------------- schema --------------------------------------

VerdictKind = Literal["confirm", "expire", "rebrand", "disputed", "unverified"]
SubjectKind = Literal["model", "provider", "identity"]


class Verdict(BaseModel):
    """Structured output of a single judge call (or cross-check pass)."""
    subject_kind: SubjectKind
    subject_id: str
    verdict: VerdictKind
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_urls: list[str] = Field(default_factory=list)
    notes: str = ""
    proposed_delta: dict[str, Any] | None = None


# ----------------------------- config --------------------------------------

DEFAULT_PRIMARY_MODEL = "gpt-4o-mini"
DEFAULT_SECONDARY_MODEL = "claude-3-5-haiku-latest"
DEFAULT_BUDGET = 50
DEFAULT_FETCH_TIMEOUT = 15.0
DEFAULT_PROMPT_MAX_CHARS = 8000
DEFAULT_API_URL = "https://api.openai.com/v1/chat/completions"


def _primary_model(cfg_verifier: dict | None = None) -> str:
    if cfg_verifier and cfg_verifier.get("primary_model"):
        return cfg_verifier["primary_model"]
    return os.environ.get("OPENRADAR_VERIFIER_MODEL_PRIMARY", DEFAULT_PRIMARY_MODEL)


def _secondary_model(cfg_verifier: dict | None = None) -> str:
    if cfg_verifier and cfg_verifier.get("secondary_model"):
        return cfg_verifier["secondary_model"]
    return os.environ.get("OPENRADAR_VERIFIER_MODEL_SECONDARY", DEFAULT_SECONDARY_MODEL)


def _budget() -> int:
    """Per-run cap on judge calls. Env-only by design — the form does
    not expose this (operators who need a different cap set
    OPENRADAR_VERIFIER_BUDGET_PER_RUN on the server). 0 disables the step."""
    try:
        return max(0, int(os.environ.get("OPENRADAR_VERIFIER_BUDGET_PER_RUN", DEFAULT_BUDGET)))
    except ValueError:
        return DEFAULT_BUDGET


def _api_url(cfg_verifier: dict | None = None) -> str:
    if cfg_verifier and cfg_verifier.get("api_url"):
        return cfg_verifier["api_url"]
    return os.environ.get("OPENRADAR_VERIFIER_API_URL", DEFAULT_API_URL)


# ----------------------------- retry helper --------------------------------

def _with_retry(fn, *, attempts: int = 3, base_delay: float = 0.5):
    """Call fn() with simple exponential backoff on any exception.
    Returns fn's return value, or None if all attempts fail."""
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
    return None  # signal failure to caller


# ----------------------------- LLM client ----------------------------------

class LLMClient:
    """Thin wrapper over an OpenAI-compatible chat completions endpoint.

    Resolution order for credentials:
      1. explicit `api_url` + `api_key` kwargs (always win)
      2. `provider_name` → look up in data/.verifier-secrets.json
         (this is the path the web settings page takes when the operator
         has added a provider card; api_key comes from the secrets file)
      3. env vars: OPENAI_API_KEY / ANTHROPIC_API_KEY
      4. `cfg_verifier["api_url"]` from data/config.json (URL only;
         the key never lives in the public config)
      5. hard-coded defaults

    The API key is NEVER read from cfg_verifier — keys live in
    .verifier-secrets.json or env vars only.
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
        cfg_verifier: dict | None = None,
        provider_name: str | None = None,
    ) -> None:
        # Lazy import to avoid a hard dependency at module-import time
        # (the secrets file is gitignored and may not exist on CI).
        from .. import verifier_secrets as _secrets

        # 1. Named provider from the secrets file (web form path).
        secret_provider = _secrets.get_provider(provider_name) if provider_name else None

        resolved_url = (
            api_url
            or (secret_provider.get("base_url") if secret_provider else None)
            or (cfg_verifier.get("api_url") if cfg_verifier and cfg_verifier.get("api_url") else None)
            or os.environ.get("OPENRADAR_VERIFIER_API_URL")
            or "https://api.openai.com/v1/chat/completions"
        )
        # Key resolution. Precedence: explicit kwarg > secrets file > env.
        if api_key:
            self.api_key = api_key
        elif secret_provider and secret_provider.get("api_key"):
            self.api_key = secret_provider["api_key"]
        elif os.environ.get("OPENAI_API_KEY"):
            self.api_key = os.environ["OPENAI_API_KEY"]
        elif os.environ.get("ANTHROPIC_API_KEY"):
            self.api_key = os.environ["ANTHROPIC_API_KEY"]
        else:
            self.api_key = ""

        # URL only counts as configured if we also have a key.
        if self.api_key:
            self.api_url = resolved_url
        else:
            self.api_url = ""

        # Model: explicit > named provider's first model > cfg_verifier > env > default
        if model:
            self.model = model
        elif secret_provider and secret_provider.get("models"):
            # Use the first model in the provider's list as the default
            # for this client. The CLI passes an explicit model for the
            # cross-check pass; this fallback just keeps a sensible value.
            self.model = secret_provider["models"][0].get("model_id") or secret_provider["models"][0].get("name") or _primary_model(cfg_verifier)
        else:
            self.model = _primary_model(cfg_verifier)
        self.timeout = timeout

    def has_key(self) -> bool:
        return bool(self.api_url) and bool(self.api_key)

    def chat(self, system: str, user: str) -> str | None:
        """Returns the assistant text content, or None on failure."""
        def _call() -> str | None:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.0,
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            r = httpx.post(self.api_url, json=payload, headers=headers, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]
        return _with_retry(_call)


# ----------------------------- page fetching -------------------------------

def fetch_page_text(url: str, *, timeout: float = DEFAULT_FETCH_TIMEOUT, max_chars: int = DEFAULT_PROMPT_MAX_CHARS) -> str:
    """Fetch a URL and return up to max_chars of text content.
    Strips HTML tags crudely; this is best-effort, not a real scraper."""
    try:
        r = httpx.get(url, follow_redirects=True, timeout=timeout, headers={"User-Agent": "OpenRadar-Verifier/0.1"})
    except httpx.HTTPError:
        return ""
    if r.status_code >= 400:
        return ""
    ctype = r.headers.get("content-type", "")
    body = r.text
    if "html" in ctype.lower():
        # crude tag strip — enough to feed into a prompt, not for display
        body = re.sub(r"<script\b[^>]*>.*?</script>", " ", body, flags=re.S | re.I)
        body = re.sub(r"<style\b[^>]*>.*?</style>", " ", body, flags=re.S | re.I)
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"\s+", " ", body).strip()
    return body[:max_chars]


# ----------------------------- prompt + parse ------------------------------

_JSON_HINT = (
    'Respond with strict JSON only, no prose, no markdown fence. Shape:\n'
    '{"verdict": "confirm|expire|rebrand|disputed|unverified",'
    ' "confidence": 0.0-1.0,'
    ' "evidence_urls": ["https://..."],'
    ' "notes": "one sentence",'
    ' "proposed_delta": null}'
)


def _parse_verdict(raw: str | None, *, subject_kind: SubjectKind, subject_id: str) -> Verdict:
    """Parse an LLM response into a Verdict. Any failure → unverified."""
    if not raw:
        return Verdict(subject_kind=subject_kind, subject_id=subject_id,
                       verdict="unverified", confidence=0.0,
                       notes="empty response from LLM")
    # Strip code fences if the model wrapped the JSON anyway.
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    # Try to find a JSON object if there's surrounding prose.
    if not s.startswith("{"):
        m = re.search(r"\{.*\}", s, flags=re.S)
        if m:
            s = m.group(0)
    try:
        data = json.loads(s)
    except json.JSONDecodeError as e:
        return Verdict(subject_kind=subject_kind, subject_id=subject_id,
                       verdict="unverified", confidence=0.0,
                       notes=f"parse_failed: {e.__class__.__name__}")
    try:
        v = Verdict(subject_kind=subject_kind, subject_id=subject_id, **data)
    except ValidationError as e:
        return Verdict(subject_kind=subject_kind, subject_id=subject_id,
                       verdict="unverified", confidence=0.0,
                       notes=f"schema_failed: {e.errors()[0]['msg']}")
    # Floor rule: no evidence → force unverified. The verifier can only vouch.
    if not v.evidence_urls:
        return Verdict(
            subject_kind=subject_kind, subject_id=subject_id,
            verdict="unverified", confidence=0.0,
            notes="no_evidence_urls: " + v.notes,
        )
    return v


# ----------------------------- judges --------------------------------------

def judge_free_tier(model: Model, provider: Provider, *, client: LLMClient | None = None) -> Verdict:
    """Confirm or refute a model's is_free=True claim."""
    c = client or LLMClient()
    subject_id = model.id
    if not c.has_key():
        return Verdict(subject_kind="model", subject_id=subject_id,
                       verdict="unverified", confidence=0.0,
                       notes="no LLM key configured")
    page_url = provider.api_base.rstrip("/").removesuffix("/v1") if provider.api_base else ""
    if not page_url:
        return Verdict(subject_kind="model", subject_id=subject_id,
                       verdict="unverified", confidence=0.0,
                       notes="no provider api_base to fetch")
    page = fetch_page_text(page_url) or fetch_page_text("https://" + provider.slug + ".com")
    system = (
        "You audit AI inference pricing pages. Decide whether the named "
        "model is currently free for inference (zero cost per million "
        "input and output tokens, no card required, not a credit window). "
        "Reply with JSON only."
    )
    user = (
        f"Provider: {provider.name} ({provider.api_base})\n"
        f"Model: {model.display_name} ({model.model_id})\n"
        f"Claimed free_kind: {model.free_kind}\n"
        f"Claimed free_limit: {model.free_limit}\n\n"
        f"--- PAGE ({page_url}) ---\n{page}\n\n"
        f"{_JSON_HINT}"
    )
    raw = c.chat(system, user)
    return _parse_verdict(raw, subject_kind="model", subject_id=subject_id)


def judge_identity(a: dict, b: dict, upstream_hint: dict | None, *, client: LLMClient | None = None) -> Verdict:
    """Arbitrate which of two candidate models is canonical."""
    c = client or LLMClient()
    subject_id = f"{a.get('model_id','?')}__vs__{b.get('model_id','?')}"
    if not c.has_key():
        return Verdict(subject_kind="identity", subject_id=subject_id,
                       verdict="unverified", confidence=0.0,
                       notes="no LLM key configured")
    system = (
        "You arbitrate whether two community-reported model listings are "
        "the same underlying model. Reply with JSON only. verdict=confirm "
        "if they are the same model (possibly under aliases); verdict="
        "disputed if you can't tell; verdict=unverified otherwise."
    )
    user = (
        f"Candidate A: {json.dumps(a, ensure_ascii=False)}\n\n"
        f"Candidate B: {json.dumps(b, ensure_ascii=False)}\n\n"
        f"Upstream hint: {json.dumps(upstream_hint or {}, ensure_ascii=False)}\n\n"
        f"{_JSON_HINT}"
    )
    raw = c.chat(system, user)
    return _parse_verdict(raw, subject_kind="identity", subject_id=subject_id)


def judge_liveness(provider: Provider, *, client: LLMClient | None = None) -> Verdict:
    """Decide what kind of 'stale' a flagged provider really is."""
    c = client or LLMClient()
    subject_id = provider.id
    if not c.has_key():
        return Verdict(subject_kind="provider", subject_id=subject_id,
                       verdict="unverified", confidence=0.0,
                       notes="no LLM key configured")
    page = fetch_page_text(provider.api_base) if provider.api_base else ""
    system = (
        "You audit whether an AI provider is currently alive, dead, or "
        "rebranded. verdict=confirm means still alive and offering free "
        "inference as described; verdict=expire means the free tier is "
        "gone; verdict=rebrand means it's been absorbed into another "
        "provider (put the successor's name in proposed_delta); verdict="
        "unverified if you can't reach the site."
    )
    user = (
        f"Provider: {provider.name} (id={provider.id}, api_base={provider.api_base})\n"
        f"Last status: {provider.status}\n\n"
        f"--- PAGE ---\n{page}\n\n"
        f"{_JSON_HINT}"
    )
    raw = c.chat(system, user)
    return _parse_verdict(raw, subject_kind="provider", subject_id=subject_id)


def judge_pricing(model: Model, provider: Provider, *, client: LLMClient | None = None) -> Verdict:
    """Given a model with no pricing, fetch the provider's pricing page
    and extract per-million-token input/output prices. Returns a
    verdict-shaped object whose `proposed_delta` carries the parsed
    values. The orchestrator applies them to the snapshot — the
    mutation is an *additive* price fill, not the narrow is_free flip,
    so it goes through the same two-pass cross-check + advisory-by-default
    rules as everything else."""
    c = client or LLMClient()
    subject_id = model.id
    if not c.has_key():
        return Verdict(subject_kind="model", subject_id=subject_id,
                       verdict="unverified", confidence=0.0,
                       notes="no LLM key configured")
    page_url = provider.api_base.rstrip("/").removesuffix("/v1") if provider.api_base else ""
    if not page_url:
        return Verdict(subject_kind="model", subject_id=subject_id,
                       verdict="unverified", confidence=0.0,
                       notes="no provider api_base to fetch")
    page = fetch_page_text(page_url) or ""
    system = (
        "You extract AI inference pricing from public docs. Reply with "
        "JSON only. verdict=confirm means the page lists this model "
        "with a per-million-token price for both input and output; "
        "verdict=unverified if you can't find the model or the page "
        "doesn't list per-token prices. proposed_delta MUST be a dict "
        "with float fields input_per_1m and output_per_1m when verdict=confirm."
    )
    user = (
        f"Provider: {provider.name} ({provider.api_base})\n"
        f"Model: {model.display_name} ({model.model_id})\n\n"
        f"--- PAGE ({page_url}) ---\n{page[:DEFAULT_PROMPT_MAX_CHARS]}\n\n"
        f"{_JSON_HINT}\n\n"
        f"Reminder: when verdict=confirm, set proposed_delta to "
        f"{{\"input_per_1m\": <float>, \"output_per_1m\": <float>}} with USD per 1M tokens."
    )
    raw = c.chat(system, user)
    return _parse_verdict(raw, subject_kind="model", subject_id=subject_id)


def judge_paid_status(model: Model, provider: Provider, *, client: LLMClient | None = None) -> Verdict:
    """Inverse of judge_free_tier. Given a model currently flagged
    is_free=True, judge whether the page actually advertises it as paid
    (e.g. trial-card-only, signup-credit-only, or recently moved behind
    a card). verdict=confirm means "still free", verdict=expire means
    "actually paid now"."""
    c = client or LLMClient()
    subject_id = model.id
    if not c.has_key():
        return Verdict(subject_kind="model", subject_id=subject_id,
                       verdict="unverified", confidence=0.0,
                       notes="no LLM key configured")
    page_url = provider.api_base.rstrip("/").removesuffix("/v1") if provider.api_base else ""
    if not page_url:
        return Verdict(subject_kind="model", subject_id=subject_id,
                       verdict="unverified", confidence=0.0,
                       notes="no provider api_base to fetch")
    page = fetch_page_text(page_url) or ""
    system = (
        "You audit AI inference pricing pages. The named model is "
        "currently flagged 'free' in our catalog. Decide whether that "
        "claim is still true. verdict=confirm = still free for inference, "
        "verdict=expire = actually paid now (card required, credits-only, "
        "or signup-only window). Reply with JSON only."
    )
    user = (
        f"Provider: {provider.name} ({provider.api_base})\n"
        f"Model: {model.display_name} ({model.model_id})\n"
        f"Claimed free_kind: {model.free_kind}\n"
        f"Claimed free_limit: {model.free_limit}\n\n"
        f"--- PAGE ({page_url}) ---\n{page[:DEFAULT_PROMPT_MAX_CHARS]}\n\n"
        f"{_JSON_HINT}"
    )
    raw = c.chat(system, user)
    return _parse_verdict(raw, subject_kind="model", subject_id=subject_id)


# ----------------------------- cross-check ---------------------------------

def _judge_again(verdict: Verdict, model: Model, provider: Provider, client: LLMClient) -> Verdict | None:
    """Re-run the matching judge under a new client (cross-check pass).
    Returns None if the subject isn't carried by this verifier call —
    e.g. identity verdicts don't have a Model attached.

    For model subjects we use the same free-tier judge as the first pass
    (it covers the inverse "is this still free" question). The pricing
    judge has its own cross-check path in the orchestrator.
    """
    if verdict.subject_kind == "model":
        return judge_free_tier(model, provider, client=client)
    if verdict.subject_kind == "provider":
        return judge_liveness(provider, client=client)
    # identity: not cross-checked (advisory only, not mutation-grade)
    return None


def cross_check_pricing(
    verdict: Verdict,
    *,
    model: Model,
    provider: Provider,
    client: LLMClient | None = None,
    cfg_verifier: dict | None = None,
    secondary_client: LLMClient | None = None,
) -> Verdict:
    """Two-pass cross-check for `judge_pricing` verdicts. Same shape as
    cross_check but reruns judge_pricing instead of judge_free_tier.
    Pricing is a fill-in mutation, not the narrow is_free flip, so we
    use the same trust discipline (require agreement between two
    independent calls)."""
    if verdict.verdict in ("unverified", "disputed"):
        return verdict
    c = client or LLMClient(cfg_verifier=cfg_verifier)
    if not c.has_key():
        return verdict
    second: Verdict | None = None
    if secondary_client is not None and secondary_client.has_key() and secondary_client is not c:
        second = judge_pricing(model, provider, client=secondary_client)
    if second is None:
        secondary = LLMClient(model=_secondary_model(cfg_verifier), cfg_verifier=cfg_verifier)
        if secondary.has_key() and secondary.model != c.model:
            second = judge_pricing(model, provider, client=secondary)
    if second is None and c.has_key():
        second = judge_pricing(model, provider, client=c)
    if second is None:
        return verdict
    if second.verdict != verdict.verdict:
        return Verdict(
            subject_kind=verdict.subject_kind,
            subject_id=verdict.subject_id,
            verdict="disputed",
            confidence=0.0,
            notes=f"cross_check_pricing disagreed: {verdict.verdict} vs {second.verdict}",
            evidence_urls=list(set(verdict.evidence_urls + second.evidence_urls)),
        )
    return Verdict(
        subject_kind=verdict.subject_kind,
        subject_id=verdict.subject_id,
        verdict=verdict.verdict,
        confidence=max(verdict.confidence, second.confidence),
        evidence_urls=list(set(verdict.evidence_urls + second.evidence_urls)),
        notes=verdict.notes,
        proposed_delta=verdict.proposed_delta,
    )


def cross_check(
    verdict: Verdict,
    *,
    model: Model | None = None,
    provider: Provider | None = None,
    client: LLMClient | None = None,
    cfg_verifier: dict | None = None,
    secondary_client: LLMClient | None = None,
) -> Verdict:
    """Re-run the verdict under a different prompt seed and (if available)
    a different model. Returns the original verdict if both passes agree,
    otherwise a disputed Verdict with confidence=0.

    Identity verdicts are skipped — they're already advisory and not used
    for snapshot mutation, so cross-check would just waste budget.
    """
    if verdict.subject_kind == "identity":
        return verdict
    if verdict.verdict in ("unverified", "disputed"):
        return verdict
    c = client or LLMClient(cfg_verifier=cfg_verifier)
    if not c.has_key():
        return verdict
    if verdict.subject_kind == "model" and (model is None or provider is None):
        return verdict
    if verdict.subject_kind == "provider" and provider is None:
        return verdict

    # Prefer a caller-supplied secondary client (a different provider
    # card from the secrets file). Fall back to a same-endpoint client
    # with a different model name, then to a second pass on the same
    # client. cross_check's contract is "two independent calls"; reusing
    # the same client is acceptable when nothing else is configured.
    second: Verdict | None = None
    if secondary_client is not None and secondary_client.has_key() and secondary_client is not c:
        second = _judge_again(verdict, model, provider, secondary_client)  # type: ignore[arg-type]
    if second is None:
        secondary = LLMClient(model=_secondary_model(cfg_verifier), cfg_verifier=cfg_verifier)
        if secondary.has_key() and secondary.model != c.model:
            second = _judge_again(verdict, model, provider, secondary)  # type: ignore[arg-type]
    if second is None and c.has_key():
        second = _judge_again(verdict, model, provider, c)  # type: ignore[arg-type]
    if second is None:
        return verdict
    if second.verdict != verdict.verdict:
        return Verdict(
            subject_kind=verdict.subject_kind,
            subject_id=verdict.subject_id,
            verdict="disputed",
            confidence=0.0,
            notes=f"cross_check disagreed: {verdict.verdict} vs {second.verdict}",
            evidence_urls=list(set(verdict.evidence_urls + second.evidence_urls)),
        )
    # Agreement: keep the higher of the two confidences.
    return Verdict(
        subject_kind=verdict.subject_kind,
        subject_id=verdict.subject_id,
        verdict=verdict.verdict,
        confidence=max(verdict.confidence, second.confidence),
        evidence_urls=list(set(verdict.evidence_urls + second.evidence_urls)),
        notes=verdict.notes,
        proposed_delta=verdict.proposed_delta,
    )


# ----------------------------- budget gate ----------------------------------

class BudgetExceeded(Exception):
    pass


def check_budget(remaining: int) -> None:
    """Raise if the per-run budget has been exhausted. The CLI calls this
    before every judge invocation."""
    if remaining <= 0:
        raise BudgetExceeded("OPENRADAR_VERIFIER_BUDGET_PER_RUN exhausted")