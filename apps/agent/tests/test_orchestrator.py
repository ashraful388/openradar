"""Unit tests for the LLM orchestrator and the new verifier judges.

These mock the LLM client and the network so the tests are deterministic
and run without an API key.
"""
from __future__ import annotations
import json
from unittest.mock import patch, MagicMock

from openradar.models import Snapshot, Provider, Model
from openradar.catalog import PROVIDERS
from openradar import sources, orchestrator
from openradar.sources.verifier import (
    LLMClient,
    Verdict,
    judge_pricing,
    judge_paid_status,
    cross_check_pricing,
)


# ----------------------------- helpers -------------------------------------

def _empty_snapshot() -> Snapshot:
    return Snapshot(providers=list(PROVIDERS), models=[], cheap_flagships=[], changelog=[])


def _stub_provider(pid: str = "p_test", api_base: str = "https://test.example.com/v1") -> Provider:
    return Provider(id=pid, slug=pid.lstrip("p_"), name="TestProvider", region="global",
                    api_base=api_base, openai_compatible=True)


def _stub_model(mid: str = "m_test", pid: str = "p_test", is_free: bool = True) -> Model:
    return Model(id=mid, provider_id=pid, model_id="test-model", display_name="Test Model",
                 modality=["chat"], is_free=is_free, free_kind="free_tier",
                 free_limit="test free tier")


# ----------------------------- judge_pricing -------------------------------

def test_judge_pricing_no_key_returns_unverified():
    with patch.dict("os.environ", {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""}, clear=False):
        v = judge_pricing(_stub_model(), _stub_provider())
    assert v.verdict == "unverified"
    assert "no LLM key" in v.notes


def test_judge_pricing_no_api_base_returns_unverified():
    client = MagicMock(spec=LLMClient)
    client.has_key.return_value = True
    p = _stub_provider(api_base="")
    v = judge_pricing(_stub_model(), p, client=client)
    assert v.verdict == "unverified"
    assert "no provider api_base" in v.notes


def test_judge_pricing_happy_path_proposed_delta():
    """A confirm verdict with proposed_delta carries the parsed prices."""
    client = MagicMock(spec=LLMClient)
    client.has_key.return_value = True
    client.chat.return_value = json.dumps({
        "verdict": "confirm",
        "confidence": 0.9,
        "evidence_urls": ["https://test.example.com/pricing"],
        "notes": "page lists per-M prices",
        "proposed_delta": {"input_per_1m": 0.15, "output_per_1m": 0.6},
    })
    with patch.object(sources.verifier, "fetch_page_text", return_value="...pricing content..."):
        v = judge_pricing(_stub_model(), _stub_provider(), client=client)
    assert v.verdict == "confirm"
    assert v.proposed_delta == {"input_per_1m": 0.15, "output_per_1m": 0.6}


def test_judge_pricing_no_evidence_forces_unverified():
    """Same rule as judge_free_tier: no evidence_urls = unverified,
    even if the LLM says 'confirm'."""
    client = MagicMock(spec=LLMClient)
    client.has_key.return_value = True
    client.chat.return_value = json.dumps({
        "verdict": "confirm",
        "confidence": 0.95,
        "evidence_urls": [],
        "notes": "I'm sure",
        "proposed_delta": {"input_per_1m": 0.1, "output_per_1m": 0.4},
    })
    with patch.object(sources.verifier, "fetch_page_text", return_value="x"):
        v = judge_pricing(_stub_model(), _stub_provider(), client=client)
    assert v.verdict == "unverified"
    assert "no_evidence_urls" in v.notes


# ----------------------------- judge_paid_status ---------------------------

def test_judge_paid_status_happy_path():
    client = MagicMock(spec=LLMClient)
    client.has_key.return_value = True
    client.chat.return_value = json.dumps({
        "verdict": "confirm",  # still free
        "confidence": 0.88,
        "evidence_urls": ["https://test.example.com/pricing"],
        "notes": "free tier still listed",
        "proposed_delta": None,
    })
    with patch.object(sources.verifier, "fetch_page_text", return_value="...free tier still listed..."):
        v = judge_paid_status(_stub_model(), _stub_provider(), client=client)
    assert v.verdict == "confirm"
    assert v.confidence == 0.88


def test_judge_paid_status_finds_paid():
    client = MagicMock(spec=LLMClient)
    client.has_key.return_value = True
    client.chat.return_value = json.dumps({
        "verdict": "expire",
        "confidence": 0.92,
        "evidence_urls": ["https://test.example.com/pricing"],
        "notes": "free tier moved behind signup credits",
        "proposed_delta": None,
    })
    with patch.object(sources.verifier, "fetch_page_text", return_value="x"):
        v = judge_paid_status(_stub_model(), _stub_provider(), client=client)
    assert v.verdict == "expire"
    assert v.confidence == 0.92


# ----------------------------- cross_check_pricing ------------------------

def test_cross_check_pricing_agreement_keeps_delta():
    v = Verdict(subject_kind="model", subject_id="m_x", verdict="confirm",
                confidence=0.8, evidence_urls=["https://a"],
                proposed_delta={"input_per_1m": 0.1, "output_per_1m": 0.4})
    c = MagicMock(spec=LLMClient)
    c.has_key.return_value = True
    c.model = "primary"
    with patch.object(sources.verifier, "judge_pricing",
                      return_value=Verdict(subject_kind="model", subject_id="m_x",
                                           verdict="confirm", confidence=0.9,
                                           evidence_urls=["https://a"],
                                           proposed_delta={"input_per_1m": 0.1, "output_per_1m": 0.4})):
        out = cross_check_pricing(v, model=_stub_model(), provider=_stub_provider(), client=c)
    assert out.verdict == "confirm"
    assert out.proposed_delta == {"input_per_1m": 0.1, "output_per_1m": 0.4}


def test_cross_check_pricing_disagreement_marks_disputed():
    v = Verdict(subject_kind="model", subject_id="m_x", verdict="confirm",
                confidence=0.8, evidence_urls=["https://a"],
                proposed_delta={"input_per_1m": 0.1, "output_per_1m": 0.4})
    c = MagicMock(spec=LLMClient)
    c.has_key.return_value = True
    c.model = "primary"
    with patch.object(sources.verifier, "judge_pricing",
                      return_value=Verdict(subject_kind="model", subject_id="m_x",
                                           verdict="unverified", confidence=0.0,
                                           evidence_urls=[])):
        out = cross_check_pricing(v, model=_stub_model(), provider=_stub_provider(), client=c)
    assert out.verdict == "disputed"
    assert out.confidence == 0.0
    assert "disagreed" in out.notes


# ----------------------------- Orchestrator --------------------------------

def test_orchestrator_no_key_emits_disabled_changelog():
    snap = _empty_snapshot()
    p = _stub_provider()
    m = _stub_model()
    snap.providers = [p]
    snap.models = [m]
    with patch.dict("os.environ", {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""}, clear=False):
        out = orchestrator.run_orchestrator(snap, primary_provider="")
    assert out == {"planned": 0, "executed": 0, "mutated": 0, "skipped": 0}
    assert any("orchestrator disabled" in c.text for c in snap.changelog)


def test_orchestrator_planner_no_plan_falls_back():
    """If the LLM returns no parseable plan, the orchestrator must
    emit a 'no plan' changelog entry and not crash."""
    snap = _empty_snapshot()
    p = _stub_provider()
    snap.providers = [p]
    snap.models = [_stub_model()]

    primary = MagicMock(spec=LLMClient)
    primary.has_key.return_value = True
    primary.chat.return_value = "not json at all"

    with patch.object(sources.verifier, "LLMClient", return_value=primary):
        out = orchestrator.run_orchestrator(snap, primary_provider="openai-main")

    assert out == {"planned": 0, "executed": 0, "mutated": 0, "skipped": 0}
    assert any("no plan" in c.text for c in snap.changelog)


def test_orchestrator_executes_judge_pricing_task_and_mutates():
    """A planner that picks a judge_pricing task must execute it
    and, on confirm + cross-check agreement, fill the model's
    input/output_per_1m."""
    snap = _empty_snapshot()
    p = _stub_provider()
    m = _stub_model(mid="m_priced", is_free=False)
    # Wipe pricing so the fill is observable.
    m.input_per_1m = None
    m.output_per_1m = None
    snap.providers = [p]
    snap.models = [m]

    primary = MagicMock(spec=LLMClient)
    primary.has_key.return_value = True
    primary.chat.side_effect = [
        # First call: the plan. Pick a judge_pricing task.
        json.dumps({"tasks": [{"tool": "judge_pricing", "subject_id": m.id,
                               "reason": "model has no pricing"}]}),
        # Subsequent calls: judge_pricing returns confirm with prices.
        json.dumps({"verdict": "confirm", "confidence": 0.9,
                    "evidence_urls": ["https://test.example.com/pricing"],
                    "notes": "n", "proposed_delta":
                    {"input_per_1m": 0.15, "output_per_1m": 0.6}}),
    ]

    with patch.object(sources.verifier, "LLMClient", return_value=primary), \
         patch.object(sources.verifier, "cross_check_pricing",
                      side_effect=lambda v, **kw: v):
        out = orchestrator.run_orchestrator(snap, primary_provider="openai-main")

    assert out["planned"] == 1
    assert out["executed"] == 1
    assert out["mutated"] == 1
    assert m.input_per_1m == 0.15
    assert m.output_per_1m == 0.6


def test_orchestrator_pricing_no_proposed_delta_no_mutation():
    """If the LLM says confirm but doesn't carry proposed_delta, the
    orchestrator must NOT invent prices — it just records the verdict."""
    snap = _empty_snapshot()
    p = _stub_provider()
    m = _stub_model(mid="m_p", is_free=False)
    m.input_per_1m = None
    m.output_per_1m = None
    snap.providers = [p]
    snap.models = [m]

    primary = MagicMock(spec=LLMClient)
    primary.has_key.return_value = True
    primary.chat.side_effect = [
        json.dumps({"tasks": [{"tool": "judge_pricing", "subject_id": m.id, "reason": "r"}]}),
        json.dumps({"verdict": "confirm", "confidence": 0.9,
                    "evidence_urls": ["https://p"], "notes": "n",
                    "proposed_delta": None}),
    ]

    with patch.object(sources.verifier, "LLMClient", return_value=primary), \
         patch.object(sources.verifier, "cross_check_pricing",
                      side_effect=lambda v, **kw: v):
        out = orchestrator.run_orchestrator(snap, primary_provider="openai-main")

    assert out["executed"] == 1
    assert out["mutated"] == 0  # not filled
    assert m.input_per_1m is None
    assert m.output_per_1m is None


def test_orchestrator_judge_free_tier_expire_mutates():
    """On verdict=expire with confidence >= 0.7, is_free flips False."""
    snap = _empty_snapshot()
    p = _stub_provider()
    m = _stub_model()
    snap.providers = [p]
    snap.models = [m]

    primary = MagicMock(spec=LLMClient)
    primary.has_key.return_value = True
    primary.chat.side_effect = [
        json.dumps({"tasks": [{"tool": "judge_free_tier", "subject_id": m.id, "reason": "r"}]}),
        # judge_free_tier's cross_check sees this as the second pass.
        json.dumps({"verdict": "expire", "confidence": 0.9,
                    "evidence_urls": ["https://p"], "notes": "n",
                    "proposed_delta": None}),
    ]

    with patch.object(sources.verifier, "LLMClient", return_value=primary), \
         patch.object(sources.verifier, "cross_check",
                      side_effect=lambda v, **kw: v):  # agree
        out = orchestrator.run_orchestrator(snap, primary_provider="openai-main")

    assert out["mutated"] == 1
    assert m.is_free is False
    assert m.free_kind == "trial_card"


def test_orchestrator_judge_liveness_advisory_only():
    """Liveness verdicts never auto-remove. The status stays unchanged."""
    snap = _empty_snapshot()
    p = _stub_provider()
    p.status = "stale"
    snap.providers = [p]
    snap.models = []

    primary = MagicMock(spec=LLMClient)
    primary.has_key.return_value = True
    primary.chat.side_effect = [
        json.dumps({"tasks": [{"tool": "judge_liveness", "subject_id": p.id, "reason": "r"}]}),
        json.dumps({"verdict": "rebrand", "confidence": 0.9,
                    "evidence_urls": ["https://p"], "notes": "n",
                    "proposed_delta": {"successor_id": "p_new"}}),
    ]

    with patch.object(sources.verifier, "LLMClient", return_value=primary), \
         patch.object(sources.verifier, "cross_check",
                      side_effect=lambda v, **kw: v):
        out = orchestrator.run_orchestrator(snap, primary_provider="openai-main")

    assert out["executed"] == 1
    assert out["mutated"] == 0  # liveness is advisory
    assert p.status == "stale"  # unchanged


def test_orchestrator_budget_enforced():
    """OPENRADAR_VERIFIER_BUDGET_PER_RUN=2 caps the orchestrator to 2 tasks
    even if the LLM plans 5."""
    snap = _empty_snapshot()
    p = _stub_provider()
    snap.providers = [p]
    snap.models = [_stub_model(mid=f"m_{i}") for i in range(5)]

    tasks = [{"tool": "scrape_provider", "subject_id": p.id, "reason": "r"}] * 5
    primary = MagicMock(spec=LLMClient)
    primary.has_key.return_value = True
    primary.chat.side_effect = [
        json.dumps({"tasks": tasks}),
    ] + ["nope"] * 5  # any scrape output

    with patch.object(sources.verifier, "LLMClient", return_value=primary), \
         patch.dict("os.environ", {"OPENRADAR_VERIFIER_BUDGET_PER_RUN": "2"}, clear=False), \
         patch.object(sources.openai_compat, "list_models", return_value=[]):
        out = orchestrator.run_orchestrator(snap, primary_provider="openai-main")

    assert out["planned"] == 5
    assert out["executed"] == 2
    assert out["skipped"] >= 3
    assert any("budget exhausted" in c.text for c in snap.changelog)


def test_orchestrator_handles_task_exception_gracefully():
    """A single tool-call that raises must NOT abort the rest of the
    plan; the orchestrator records the error and moves on."""
    snap = _empty_snapshot()
    p = _stub_provider()
    p2 = _stub_provider(pid="p_test2", api_base="https://t2.example/v1")
    snap.providers = [p, p2]
    snap.models = []

    primary = MagicMock(spec=LLMClient)
    primary.has_key.return_value = True
    primary.chat.side_effect = [
        json.dumps({"tasks": [
            {"tool": "scrape_provider", "subject_id": p.id, "reason": "r"},
            {"tool": "scrape_provider", "subject_id": p2.id, "reason": "r"},
        ]}),
    ]

    def flaky_scrape(api_base, **kwargs):
        # First call raises, second succeeds. The patch is on
        # list_models(api_base, api_key=..., timeout=...), so we look
        # at the api_base to tell them apart.
        if "test.example.com" in api_base:
            raise RuntimeError("network down")
        return [{"id": "m_ok", "name": "m_ok"}]

    with patch.object(sources.verifier, "LLMClient", return_value=primary), \
         patch.object(sources.openai_compat, "list_models", side_effect=flaky_scrape):
        out = orchestrator.run_orchestrator(snap, primary_provider="openai-main")

    assert out["executed"] == 1
    assert out["skipped"] == 1
    # No unhandled exception; just a recorded changelog entry.
    assert any("raised" in c.text for c in snap.changelog)
