from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field

Modality = Literal["chat", "embedding", "image", "audio_tts", "audio_stt", "video", "rerank", "vision", "code", "ocr"]
FreeKind = Literal["free_tier", "free_credits", "promo", "trial_card", "byok_required", "community"]
FreeEvidenceSource = Literal["declared", "openrouter", "models_dev", "bai", "probe", "verifier", "xkiro", "huggingface"]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Provider(BaseModel):
    id: str
    slug: str
    name: str
    region: str
    api_base: str = ""
    openai_compatible: bool = False
    api_key_env: str | None = None
    # The provider's public website (docs, signup, key console). Derived
    # from the api_base host at run time when not set explicitly in the
    # catalog — so catalog rows can pin the canonical URL (e.g. z.ai
    # instead of api.z.ai) and discovered rows still get a sane link.
    homepage: str = ""
    signup_friction: str = "email"
    modalities: list[Modality] = Field(default_factory=lambda: ["chat"])
    tagline: str = ""
    notes: str = ""
    catch: str = ""
    free_model_count: int = 0
    # Derived pricing-coverage stats, recomputed every run. Stored as
    # JSON-in-string so the snapshot.json schema doesn't need a bump —
    # the web UI only reads these as stats, never as filters.
    pricing_status: str = ""
    # needs_key: the /v1/models endpoint is gated behind a login/API key
    # and no key was configured, so the model list is unknown this run.
    # It is derived each run from the endpoint probe, never persisted as
    # an operator decision. Web UI renders a "set <env var>" badge.
    probe_status: Literal["ok", "needs_key", "gated", "error", "skipped", ""] = ""
    status: Literal["active", "stale", "removed"] = "active"
    first_seen: str = Field(default_factory=now)
    last_verified: str = Field(default_factory=now)


class Model(BaseModel):
    id: str
    provider_id: str
    model_id: str
    display_name: str
    modality: list[Modality]
    context_window: int | None = None
    is_free: bool = False
    free_kind: FreeKind = "byok_required"
    free_limit: str = ""
    # Set when is_free=True was confirmed by a live 1-token completion
    # against the provider API (ground truth), as opposed to inferred
    # from docs, community lists, or aggregators.
    free_verified_at: str | None = None
    # Evidence provenance: which source classified this model as free
    free_evidence_source: FreeEvidenceSource | None = None
    # Timestamp when the free evidence was recorded
    free_evidence_timestamp: str | None = None
    # Per-million-token pricing. Optional — most models discovered by
    # `/v1/models` probes don't expose it, but aggregators like b.ai and
    # models.dev do.
    input_per_1m: float | None = None
    output_per_1m: float | None = None
    cache_read_per_1m: float | None = None
    cache_write_per_1m: float | None = None
    last_verified: str = Field(default_factory=now)


class CheapFlagship(BaseModel):
    rank: int
    model_id: str
    display_name: str
    provider: str
    input_per_1m: float
    output_per_1m: float
    context_window: int | None = None


class Change(BaseModel):
    at: str = Field(default_factory=now)
    kind: Literal["added", "expired", "pricing", "verified", "submit", "verifier"]
    text: str


class CreditProvider(BaseModel):
    """Providers that offer free credits/money on signup, not free inference."""
    provider_id: str
    name: str
    # None = the site advertises signup credits but doesn't publish a fixed
    # amount (or we couldn't verify one) — the UI renders "Varies".
    signup_bonus_usd: float | None
    credit_expiry_days: int | None
    models_available: list[str]
    signup_friction: str  # email, phone, github, trial_card
    homepage: str
    notes: str = ""


class Snapshot(BaseModel):
    snapshot_at: str = Field(default_factory=now)
    schema_version: int = 1
    providers: list[Provider]
    models: list[Model]
    cheap_flagships: list[CheapFlagship]
    changelog: list[Change] = Field(default_factory=list)
    credit_providers: list[CreditProvider] = Field(default_factory=list)
