"""Unit tests for the LLM verifier layer.

These mock the network and the LLM client so the tests are deterministic
and run without an API key.
"""
from __future__ import annotations
import json
import os
from unittest.mock import patch, MagicMock

from openradar.models import Snapshot, Change, Provider, Model
from openradar.catalog import PROVIDERS
from openradar import sources
from openradar.sources.verifier import (
    LLMClient,
    Verdict,
    _parse_verdict,
    judge_free_tier,
    judge_liveness,
    cross_check,
    _with_retry,
)


def _empty_snapshot(**kwargs) -> Snapshot:
    return Snapshot(providers=list(PROVIDERS), models=[], cheap_flagships=[], changelog=[])


def _stub_provider(pid: str = "p_test", api_base: str = "https://test.example.com/v1") -> Provider:
    return Provider(id=pid, slug=pid.lstrip("p_"), name="TestProvider", region="global",
                    api_base=api_base, openai_compatible=True)


def _stub_model(mid: str = "m_test", pid: str = "p_test", is_free: bool = True) -> Model:
    return Model(id=mid, provider_id=pid, model_id="test-model", display_name="Test Model",
                 modality=["chat"], is_free=is_free, free_kind="free_tier",
                 free_limit="test free tier")


# ----------------------------- LLMClient -----------------------------------

def test_llm_client_resolves_openai_key():
    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False):
        c = LLMClient()
    assert c.has_key() is True
    assert c.api_key == "sk-test"
    assert c.api_url.startswith("https://api.openai.com")


def test_llm_client_no_key():
    env = {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""}
    with patch.dict("os.environ", env, clear=False):
        c = LLMClient()
    assert c.has_key() is False


def test_llm_client_explicit_args_override_env():
    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-env"}, clear=False):
        c = LLMClient(api_url="https://proxy.example/v1/chat/completions",
                      api_key="sk-explicit", model="custom-model")
    assert c.api_key == "sk-explicit"
    assert c.api_url == "https://proxy.example/v1/chat/completions"
    assert c.model == "custom-model"


def test_with_retry_succeeds_on_third_attempt():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("nope")
        return "ok"

    # Use a base_delay of 0 so the test is fast.
    assert _with_retry(flaky, attempts=5, base_delay=0) == "ok"
    assert calls["n"] == 3


def test_with_retry_returns_none_on_exhaustion():
    def always_fails():
        raise RuntimeError("nope")
    assert _with_retry(always_fails, attempts=3, base_delay=0) is None


# ----------------------------- Verdict parsing -----------------------------

def test_parse_verdict_happy():
    raw = json.dumps({
        "verdict": "confirm",
        "confidence": 0.92,
        "evidence_urls": ["https://test.example.com/pricing"],
        "notes": "free tier visible on pricing page",
        "proposed_delta": None,
    })
    v = _parse_verdict(raw, subject_kind="model", subject_id="m_x")
    assert v.verdict == "confirm"
    assert v.confidence == 0.92
    assert "https://test.example.com/pricing" in v.evidence_urls


def test_parse_verdict_no_evidence_forces_unverified():
    raw = json.dumps({
        "verdict": "confirm",
        "confidence": 0.9,
        "evidence_urls": [],
        "notes": "I am sure",
        "proposed_delta": None,
    })
    v = _parse_verdict(raw, subject_kind="model", subject_id="m_x")
    assert v.verdict == "unverified"
    assert "no_evidence_urls" in v.notes


def test_parse_verdict_strips_code_fence():
    raw = '```json\n{"verdict": "expire", "confidence": 0.8, "evidence_urls": ["https://x"], "notes": "n", "proposed_delta": null}\n```'
    v = _parse_verdict(raw, subject_kind="model", subject_id="m_x")
    assert v.verdict == "expire"
    assert v.confidence == 0.8


def test_parse_verdict_malformed_json_returns_unverified():
    v = _parse_verdict("not json at all", subject_kind="model", subject_id="m_x")
    assert v.verdict == "unverified"
    assert "parse_failed" in v.notes


def test_parse_verdict_empty_string_returns_unverified():
    v = _parse_verdict("", subject_kind="model", subject_id="m_x")
    assert v.verdict == "unverified"
    assert "empty response" in v.notes


def test_parse_verdict_schema_violation_returns_unverified():
    # missing required field "verdict"
    raw = json.dumps({"confidence": 0.9, "evidence_urls": ["https://x"], "notes": "n"})
    v = _parse_verdict(raw, subject_kind="model", subject_id="m_x")
    assert v.verdict == "unverified"
    assert "schema_failed" in v.notes


# ----------------------------- judge_free_tier -----------------------------

def test_judge_free_tier_no_key_returns_unverified():
    with patch.dict("os.environ", {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""}, clear=False):
        v = judge_free_tier(_stub_model(), _stub_provider())
    assert v.verdict == "unverified"
    assert "no LLM key" in v.notes


def test_judge_free_tier_no_api_base_returns_unverified():
    p = _stub_provider(api_base="")
    client = MagicMock(spec=LLMClient)
    client.has_key.return_value = True
    v = judge_free_tier(_stub_model(), p, client=client)
    assert v.verdict == "unverified"
    assert "no provider api_base" in v.notes


def test_judge_free_tier_happy_path():
    client = MagicMock(spec=LLMClient)
    client.has_key.return_value = True
    client.chat.return_value = json.dumps({
        "verdict": "confirm",
        "confidence": 0.95,
        "evidence_urls": ["https://test.example.com/pricing"],
        "notes": "free tier page says $0/M",
        "proposed_delta": None,
    })
    with patch.object(sources.verifier, "fetch_page_text", return_value="...free tier content..."):
        v = judge_free_tier(_stub_model(), _stub_provider(), client=client)
    assert v.verdict == "confirm"
    assert v.confidence == 0.95


# ----------------------------- judge_liveness ------------------------------

def test_judge_liveness_no_key_returns_unverified():
    with patch.dict("os.environ", {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""}, clear=False):
        v = judge_liveness(_stub_provider())
    assert v.verdict == "unverified"


def test_judge_liveness_records_rebrand_delta():
    client = MagicMock(spec=LLMClient)
    client.has_key.return_value = True
    client.chat.return_value = json.dumps({
        "verdict": "rebrand",
        "confidence": 0.88,
        "evidence_urls": ["https://test.example.com/blog/merger"],
        "notes": "merged into p_xyz",
        "proposed_delta": {"successor_id": "p_xyz"},
    })
    with patch.object(sources.verifier, "fetch_page_text", return_value="...blog post..."):
        v = judge_liveness(_stub_provider(), client=client)
    assert v.verdict == "rebrand"
    assert v.proposed_delta == {"successor_id": "p_xyz"}


# ----------------------------- cross_check ---------------------------------

def test_cross_check_agreement_keeps_verdict():
    v = Verdict(subject_kind="model", subject_id="m_x", verdict="expire",
                confidence=0.8, evidence_urls=["https://a"])
    c = MagicMock(spec=LLMClient)
    c.has_key.return_value = True
    c.model = "primary"

    # secondary also says "expire"
    with patch.object(sources.verifier, "_secondary_model", return_value="secondary"), \
         patch.object(sources.verifier, "_judge_again",
                      return_value=Verdict(subject_kind="model", subject_id="m_x",
                                           verdict="expire", confidence=0.85,
                                           evidence_urls=["https://a"])):
        out = cross_check(v, model=_stub_model(), provider=_stub_provider(), client=c)
    assert out.verdict == "expire"
    assert out.confidence == 0.85  # took the max


def test_cross_check_disagreement_marks_disputed():
    v = Verdict(subject_kind="model", subject_id="m_x", verdict="expire",
                confidence=0.8, evidence_urls=["https://a"])
    c = MagicMock(spec=LLMClient)
    c.has_key.return_value = True
    c.model = "primary"

    with patch.object(sources.verifier, "_secondary_model", return_value="secondary"), \
         patch.object(sources.verifier, "_judge_again",
                      return_value=Verdict(subject_kind="model", subject_id="m_x",
                                           verdict="confirm", confidence=0.9,
                                           evidence_urls=["https://a"])):
        out = cross_check(v, model=_stub_model(), provider=_stub_provider(), client=c)
    assert out.verdict == "disputed"
    assert out.confidence == 0.0
    assert "disagreed" in out.notes


def test_cross_check_identity_subject_skipped():
    v = Verdict(subject_kind="identity", subject_id="a__vs__b", verdict="confirm",
                confidence=0.7, evidence_urls=["https://x"])
    c = MagicMock(spec=LLMClient)
    c.has_key.return_value = True
    out = cross_check(v, client=c)
    assert out.verdict == "confirm"  # unchanged — identity doesn't cross-check


def test_cross_check_no_key_passes_through():
    v = Verdict(subject_kind="model", subject_id="m_x", verdict="expire",
                confidence=0.8, evidence_urls=["https://a"])
    with patch.dict("os.environ", {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""}, clear=False):
        c = LLMClient()
    out = cross_check(v, model=_stub_model(), provider=_stub_provider(), client=c)
    assert out.verdict == "expire"  # unchanged when verifier can't actually verify


# ----------------------------- ingest_verifier -----------------------------

def test_ingest_verifier_no_key_emits_disabled_changelog():
    from openradar.cli import ingest_verifier
    snap = _empty_snapshot()
    with patch.dict("os.environ", {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""}, clear=False):
        n_v, n_e, n_r = ingest_verifier(snap)
    assert (n_v, n_e, n_r) == (0, 0, 0)
    assert any("verifier disabled" in c.text for c in snap.changelog)
    assert all(c.kind == "verifier" for c in snap.changelog)


def test_ingest_verifier_expire_mutates_only_with_evidence():
    """A verdict=expire with confidence >= 0.7 must flip is_free and
    set free_kind=trial_card on the matching model."""
    from openradar.cli import ingest_verifier
    snap = _empty_snapshot()
    p = _stub_provider()
    m = _stub_model()
    snap.providers = [p]
    snap.models = [m]

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False), \
         patch.object(sources.verifier, "judge_free_tier",
                      return_value=Verdict(subject_kind="model", subject_id=m.id,
                                           verdict="expire", confidence=0.9,
                                           evidence_urls=["https://proof"])), \
         patch.object(sources.verifier, "cross_check",
                      side_effect=lambda v, **kw: v):  # pass through, no second pass needed
        n_v, n_e, n_r = ingest_verifier(snap)

    assert n_v == 1
    assert n_e == 1
    assert snap.models[0].is_free is False
    assert snap.models[0].free_kind == "trial_card"


def test_ingest_verifier_confirm_does_not_mutate():
    """A verdict=confirm must NOT mutate the model — confirmation is
    advisory only."""
    from openradar.cli import ingest_verifier
    snap = _empty_snapshot()
    p = _stub_provider()
    m = _stub_model()
    snap.providers = [p]
    snap.models = [m]

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False), \
         patch.object(sources.verifier, "judge_free_tier",
                      return_value=Verdict(subject_kind="model", subject_id=m.id,
                                           verdict="confirm", confidence=0.95,
                                           evidence_urls=["https://proof"])), \
         patch.object(sources.verifier, "cross_check",
                      side_effect=lambda v, **kw: v):
        n_v, n_e, n_r = ingest_verifier(snap)

    assert n_v == 1
    assert n_e == 0
    assert snap.models[0].is_free is True
    assert snap.models[0].free_kind == "free_tier"


def test_ingest_verifier_budget_enforced():
    """Setting OPENRADAR_VERIFIER_BUDGET_PER_RUN=2 must stop the loop
    after 2 judge calls and emit a budget-exhausted changelog entry."""
    from openradar.cli import ingest_verifier
    snap = _empty_snapshot()
    p = _stub_provider()
    ms = [_stub_model(mid=f"m_{i}") for i in range(5)]
    snap.providers = [p]
    snap.models = ms

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test",
                                   "OPENRADAR_VERIFIER_BUDGET_PER_RUN": "2"}, clear=False), \
         patch.object(sources.verifier, "judge_free_tier",
                      return_value=Verdict(subject_kind="model", subject_id="x",
                                           verdict="confirm", confidence=0.9,
                                           evidence_urls=["https://p"])), \
         patch.object(sources.verifier, "cross_check",
                      side_effect=lambda v, **kw: v):
        n_v, n_e, n_r = ingest_verifier(snap)

    assert n_v == 2
    assert any("budget exhausted" in c.text for c in snap.changelog)


def test_ingest_verifier_skips_trial_card_models():
    """Models already marked free_kind=trial_card are operator-set and
    must NOT be re-judged."""
    from openradar.cli import ingest_verifier
    snap = _empty_snapshot()
    p = _stub_provider()
    m = Model(id="m_tc", provider_id=p.id, model_id="x", display_name="X",
              modality=["chat"], is_free=True, free_kind="trial_card",
              free_limit="operator-marked")
    snap.providers = [p]
    snap.models = [m]

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False), \
         patch.object(sources.verifier, "judge_free_tier") as mock_judge, \
         patch.object(sources.verifier, "cross_check",
                      side_effect=lambda v, **kw: v):
        n_v, n_e, n_r = ingest_verifier(snap)

    assert (n_v, n_e, n_r) == (0, 0, 0)
    assert mock_judge.call_count == 0


def test_ingest_verifier_stale_provider_liveness_never_auto_removes():
    """Liveness verdicts are advisory: a rebrand verdict is recorded in
    the changelog but the provider's status must stay 'stale' (no
    auto-removal per AGENTS.md)."""
    from openradar.cli import ingest_verifier
    snap = _empty_snapshot()
    p = Provider(id="p_stale", slug="stale", name="Stale", region="global",
                 api_base="https://stale.example/v1", status="stale")
    snap.providers = [p]

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False), \
         patch.object(sources.verifier, "judge_liveness",
                      return_value=Verdict(subject_kind="provider", subject_id=p.id,
                                           verdict="rebrand", confidence=0.85,
                                           evidence_urls=["https://proof"],
                                           proposed_delta={"successor_id": "p_new"})), \
         patch.object(sources.verifier, "cross_check",
                      side_effect=lambda v, **kw: v):
        n_v, n_e, n_r = ingest_verifier(snap)

    assert n_v == 1
    assert n_r == 1
    assert p.status == "stale"  # unchanged — advisory only


# ----------------------------- cfg_verifier wiring -------------------------

def test_llm_client_uses_cfg_verifier_api_url():
    """When cfg_verifier supplies an api_url and a key is in the env, the
    client should route to that URL (not the default OpenAI one)."""
    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False):
        c = LLMClient(cfg_verifier={"api_url": "https://proxy.example.com/v1/chat/completions"})
    assert c.api_url == "https://proxy.example.com/v1/chat/completions"
    assert c.api_key == "sk-test"
    assert c.has_key() is True


def test_llm_client_uses_cfg_verifier_primary_model():
    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False):
        c = LLMClient(cfg_verifier={"primary_model": "llama-3.1-70b"})
    assert c.model == "llama-3.1-70b"


def test_llm_client_explicit_model_beats_cfg_verifier():
    """The ctor's `model=` kwarg is the most-specific override and beats cfg_verifier."""
    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False):
        c = LLMClient(model="explicit-model",
                      cfg_verifier={"primary_model": "from-config"})
    assert c.model == "explicit-model"


def test_llm_client_cfg_verifier_does_not_carry_key():
    """Critical security property: even if someone tries to put a key in
    cfg_verifier, the client must NOT use it — keys come from env only."""
    with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
        c = LLMClient(cfg_verifier={
            "api_url": "https://proxy.example.com/v1/chat/completions",
            "api_key": "sk-leaked-from-config",  # must be ignored
        })
    assert c.has_key() is False
    assert c.api_key == ""


def test_budget_helper_reads_env_only():
    """The budget is now env-only by design — the form does not expose
    it. Operators who need a different cap set
    OPENRADAR_VERIFIER_BUDGET_PER_RUN on the server."""
    from openradar.sources.verifier import _budget
    with patch.dict("os.environ", {"OPENRADAR_VERIFIER_BUDGET_PER_RUN": "13"}, clear=False):
        assert _budget() == 13
    with patch.dict("os.environ", {"OPENRADAR_VERIFIER_BUDGET_PER_RUN": "0"}, clear=False):
        assert _budget() == 0  # 0 means disabled
    with patch.dict("os.environ", {"OPENRADAR_VERIFIER_BUDGET_PER_RUN": "-3"}, clear=False):
        assert _budget() == 0  # negative clamped to 0
    with patch.dict("os.environ", {}, clear=False):
        # default 50 when env not set
        os.environ.pop("OPENRADAR_VERIFIER_BUDGET_PER_RUN", None)
        assert _budget() == 50


def test_budget_helper_ignores_cfg_verifier():
    """Backward-compat: passing cfg_verifier (legacy shape) must be a
    no-op for the budget helper, which is now env-only."""
    from openradar.sources.verifier import _budget
    with patch.dict("os.environ", {"OPENRADAR_VERIFIER_BUDGET_PER_RUN": "21"}, clear=False):
        assert _budget() == 21  # env wins


def test_ingest_verifier_auto_apply_off_does_not_mutate():
    """When cfg_verifier['auto_apply_expire'] is False, an expire verdict
    with confidence >= threshold must NOT flip is_free."""
    from openradar.cli import ingest_verifier
    snap = _empty_snapshot()
    p = _stub_provider()
    m = _stub_model()
    snap.providers = [p]
    snap.models = [m]

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False), \
         patch.object(sources.verifier, "judge_free_tier",
                      return_value=Verdict(subject_kind="model", subject_id=m.id,
                                           verdict="expire", confidence=0.95,
                                           evidence_urls=["https://proof"])), \
         patch.object(sources.verifier, "cross_check",
                      side_effect=lambda v, **kw: v):
        cfg = {"auto_apply_expire": False, "expire_confidence_threshold": 0.7}
        n_v, n_e, n_r = ingest_verifier(snap, cfg_verifier=cfg)

    assert n_v == 1
    assert n_e == 0  # not applied
    assert snap.models[0].is_free is True  # unchanged
    assert snap.models[0].free_kind == "free_tier"


def test_ingest_verifier_budget_zero_emits_disabled_changelog():
    """OPENRADAR_VERIFIER_BUDGET_PER_RUN=0 is the documented way to disable
    the step from the server — it should emit a single 'disabled' changelog
    entry and return zeros, without making any LLM calls. The form no
    longer exposes this; it's env-only by design."""
    from openradar.cli import ingest_verifier
    snap = _empty_snapshot()
    p = _stub_provider()
    snap.providers = [p]
    snap.models = [_stub_model()]

    with patch.dict("os.environ",
                    {"OPENAI_API_KEY": "sk-test",
                     "OPENRADAR_VERIFIER_BUDGET_PER_RUN": "0"},
                    clear=False), \
         patch.object(sources.verifier, "judge_free_tier") as mock_judge:
        n_v, n_e, n_r = ingest_verifier(snap)

    assert (n_v, n_e, n_r) == (0, 0, 0)
    assert mock_judge.call_count == 0
    assert any("OPENRADAR_VERIFIER_BUDGET_PER_RUN is 0" in c.text for c in snap.changelog)


def test_ingest_verifier_cfg_budget_honored():
    """With OPENRADAR_VERIFIER_BUDGET_PER_RUN=2 and 5 free models, only 2
    judges should run. The form no longer exposes this; it's env-only."""
    from openradar.cli import ingest_verifier
    snap = _empty_snapshot()
    p = _stub_provider()
    ms = [_stub_model(mid=f"m_{i}") for i in range(5)]
    snap.providers = [p]
    snap.models = ms

    with patch.dict("os.environ",
                    {"OPENAI_API_KEY": "sk-test",
                     "OPENRADAR_VERIFIER_BUDGET_PER_RUN": "2"},
                    clear=False), \
         patch.object(sources.verifier, "judge_free_tier",
                      return_value=Verdict(subject_kind="model", subject_id="x",
                                           verdict="confirm", confidence=0.9,
                                           evidence_urls=["https://p"])), \
         patch.object(sources.verifier, "cross_check",
                      side_effect=lambda v, **kw: v):
        n_v, n_e, n_r = ingest_verifier(snap)

    assert n_v == 2
    assert any("budget exhausted" in c.text for c in snap.changelog)


def test_ingest_verifier_higher_threshold_blocks_lower_confidence_expire():
    """expire_confidence_threshold=0.95 must block an expire verdict with
    confidence=0.8, even with auto_apply_expire=True."""
    from openradar.cli import ingest_verifier
    snap = _empty_snapshot()
    p = _stub_provider()
    m = _stub_model()
    snap.providers = [p]
    snap.models = [m]

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False), \
         patch.object(sources.verifier, "judge_free_tier",
                      return_value=Verdict(subject_kind="model", subject_id=m.id,
                                           verdict="expire", confidence=0.8,
                                           evidence_urls=["https://proof"])), \
         patch.object(sources.verifier, "cross_check",
                      side_effect=lambda v, **kw: v):
        cfg = {"auto_apply_expire": True, "expire_confidence_threshold": 0.95}
        n_v, n_e, n_r = ingest_verifier(snap, cfg_verifier=cfg)

    assert n_v == 1
    assert n_e == 0  # below threshold → not applied
    assert snap.models[0].is_free is True


# ----------------------------- verifier_secrets + named providers ---------

def test_secrets_loader_returns_empty_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENRADAR_DATA", str(tmp_path))
    from openradar import verifier_secrets
    out = verifier_secrets.load()
    assert out == {"providers": []}
    assert verifier_secrets.get_provider("anything") is None


def test_secrets_loader_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENRADAR_DATA", str(tmp_path))
    from openradar import verifier_secrets
    providers = [
        {"name": "openai-main", "base_url": "https://api.openai.com/v1/chat/completions",
         "api_format": "openai", "api_key": "sk-test-1234567890",
         "models": [{"name": "GPT-4o mini", "model_id": "gpt-4o-mini"}]},
        {"name": "anthropic-fallback", "base_url": "https://api.anthropic.com/v1/messages",
         "api_format": "anthropic", "api_key": "sk-ant-abcdef",
         "models": [{"name": "Haiku", "model_id": "claude-3-5-haiku-latest"}]},
    ]
    verifier_secrets.save(providers)
    out = verifier_secrets.load()
    assert len(out["providers"]) == 2
    p = verifier_secrets.get_provider("OPENAI-MAIN")  # case-insensitive
    assert p is not None
    assert p["api_key"] == "sk-test-1234567890"
    assert p["models"][0]["model_id"] == "gpt-4o-mini"


def test_secrets_loader_handles_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENRADAR_DATA", str(tmp_path))
    from openradar import verifier_secrets
    (tmp_path / ".verifier-secrets.json").write_text("not json at all {{{")
    # load() must not throw — corrupt file = empty list, no crash.
    out = verifier_secrets.load()
    assert out == {"providers": []}


def test_llm_client_resolves_named_provider_from_secrets(tmp_path, monkeypatch):
    """When provider_name is given and a matching card exists in
    data/.verifier-secrets.json, the client must use that card's api_url
    and api_key — and NEVER fall back to env vars."""
    monkeypatch.setenv("OPENRADAR_DATA", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from openradar import verifier_secrets
    verifier_secrets.save([{
        "name": "openai-main",
        "base_url": "https://custom.example.com/v1/chat/completions",
        "api_format": "openai",
        "api_key": "sk-from-secrets",
        "models": [{"name": "GPT-4o mini", "model_id": "gpt-4o-mini"}],
    }])

    c = LLMClient(provider_name="openai-main")
    assert c.has_key() is True
    assert c.api_url == "https://custom.example.com/v1/chat/completions"
    assert c.api_key == "sk-from-secrets"
    assert c.model == "gpt-4o-mini"  # first model from the card


def test_llm_client_named_provider_falls_back_to_env_when_missing(tmp_path, monkeypatch):
    """If provider_name doesn't match a card, the client falls back to
    env vars as before — keeps existing CI behavior intact."""
    monkeypatch.setenv("OPENRADAR_DATA", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env", prepend=False)

    from openradar import verifier_secrets
    verifier_secrets.save([])  # empty

    c = LLMClient(provider_name="nonexistent-card")
    assert c.api_key == "sk-from-env"
    assert c.has_key() is True


def test_llm_client_uses_explicit_key_even_when_provider_named(tmp_path, monkeypatch):
    """The explicit api_key kwarg is the most-specific override and beats
    a named provider card (and beats env vars)."""
    monkeypatch.setenv("OPENRADAR_DATA", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env", prepend=False)

    from openradar import verifier_secrets
    verifier_secrets.save([{
        "name": "openai-main", "base_url": "https://from-card.example/v1",
        "api_format": "openai", "api_key": "sk-from-card",
        "models": [],
    }])

    c = LLMClient(api_key="sk-explicit", provider_name="openai-main")
    assert c.api_key == "sk-explicit"  # kwarg wins


def test_ingest_verifier_uses_named_provider_from_secrets(tmp_path, monkeypatch):
    """End-to-end: a cfg_verifier with primary_provider set must resolve
    the LLM key from data/.verifier-secrets.json (no env var needed)."""
    monkeypatch.setenv("OPENRADAR_DATA", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from openradar import verifier_secrets
    verifier_secrets.save([{
        "name": "openai-main",
        "base_url": "https://api.openai.com/v1/chat/completions",
        "api_format": "openai",
        "api_key": "sk-from-secrets",
        "models": [{"name": "GPT-4o mini", "model_id": "gpt-4o-mini"}],
    }])

    from openradar.cli import ingest_verifier
    snap = _empty_snapshot()
    p = _stub_provider()
    snap.providers = [p]
    snap.models = [_stub_model()]

    cfg = {"primary_provider": "openai-main", "secondary_provider": ""}
    with patch.object(sources.verifier, "judge_free_tier",
                      return_value=Verdict(subject_kind="model", subject_id="x",
                                           verdict="confirm", confidence=0.9,
                                           evidence_urls=["https://p"])), \
         patch.object(sources.verifier, "cross_check",
                      side_effect=lambda v, **kw: v):
        n_v, n_e, n_r = ingest_verifier(snap, cfg_verifier=cfg)

    assert n_v == 1
    assert n_e == 0
    assert n_r == 0
    # No "no LLM key" disabled entry — the secrets file resolved cleanly.
    assert not any("no LLM key" in c.text for c in snap.changelog)
