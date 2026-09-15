"""Unit tests for the new ingestion pipeline.

We mock out the network calls so the tests are deterministic and run
without internet."""
from __future__ import annotations
from unittest.mock import patch

from openradar.models import Snapshot, Change
from openradar.catalog import PROVIDERS
from openradar.cli import run
from openradar import sources


def _empty_snapshot(**kwargs) -> Snapshot:
    return Snapshot(providers=list(PROVIDERS), models=[], cheap_flagships=[], changelog=[])


def test_openrouter_free_filter():
    m = {"id": "meta-llama/llama-3.3-70b:free"}
    assert sources.openrouter.is_free(m) is True
    m2 = {"id": "openai/gpt-5", "pricing": {"prompt": "0.000005", "completion": "0.000015"}}
    assert sources.openrouter.is_free(m2) is False
    m3 = {"id": "some/free-thing", "pricing": {"prompt": "0", "completion": "0"}}
    assert sources.openrouter.is_free(m3) is True


def test_models_dev_cheap_flagship():
    # Cheap + tools + image input = flagship candidate
    m = {"cost": {"input": 0.2, "output": 0.6}, "tool_call": True,
         "modalities": {"input": ["text", "image"], "output": ["text"]}}
    assert sources.models_dev.is_cheap_flagship(m) is True
    # Zero-cost is not a "flagship" — it's free.
    m2 = {"cost": {"input": 0, "output": 0}, "tool_call": True,
          "modalities": {"input": ["text"], "output": ["text"]}}
    assert sources.models_dev.is_cheap_flagship(m2) is False
    # Too expensive
    m3 = {"cost": {"input": 5.0, "output": 25.0}, "tool_call": True,
          "modalities": {"input": ["text"], "output": ["text"]}}
    assert sources.models_dev.is_cheap_flagship(m3) is False


def test_community_list_extraction():
    text = """
    | [Some AI](https://some.ai) | free tier | yes |
    | [Another](https://another.dev) | signup credit | no |
    Random reference to [docs](https://docs.example.com/foo).
    See also https://b.ai for a thing.
    Also [HF](https://huggingface.co/foo).
    And a badge: ![GitHub stars](https://img.shields.io/github/stars/foo/bar).
    And a Wikipedia link: [wiki](https://en.wikipedia.org/wiki/AI).
    """
    items = [("test/readme", text)]
    cands = sources.community_lists.extract_candidates(items)
    hosts = {c["host"] for c in cands}
    assert "some.ai" in hosts
    assert "another.dev" in hosts
    assert "docs.example.com" in hosts
    assert "b.ai" in hosts
    # These must be excluded.
    assert "huggingface.co" not in hosts
    assert "img.shields.io" not in hosts
    assert "en.wikipedia.org" not in hosts
    # Names that came from markdown images should not be `![GitHub stars]`
    for c in cands:
        assert not c["name"].startswith("!"), f"name leaked markdown image syntax: {c['name']}"


def test_run_merges_openrouter_and_hf():
    """A full run with all network sources stubbed should produce a non-empty
    snapshot and a populated cheap-flagships list."""
    fake_or = [
        {"id": "meta-llama/llama-3.3-70b:free", "name": "Llama 3.3 70B :free",
         "context_length": 128000, "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "deepseek/deepseek-chat:free", "name": "DeepSeek :free",
         "context_length": 64000, "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "openai/gpt-5", "name": "GPT-5",
         "context_length": 256000, "pricing": {"prompt": "0.000005", "completion": "0.000015"}},
    ]
    fake_hf = [
        {"id": "openai/gpt-oss-120b", "name": "GPT-OSS 120B",
         "max_context_length": 128000,
         "providers": [{"price": 0}, {"price": 0.0001}]},
        {"id": "meta-llama/Llama-3.1-8B", "name": "Llama 3.1 8B",
         "max_context_length": 16000,
         "providers": [{"price": 0}]},
    ]
    fake_md = {
        "deepseek": {"name": "DeepSeek", "models": {
            "deepseek-chat": {"name": "DeepSeek-V3", "cost": {"input": 0.14, "output": 0.28},
                              "tool_call": True, "limit": {"context": 64000},
                              "modalities": {"input": ["text"], "output": ["text"]}},
        }},
        "groq": {"name": "Groq", "models": {
            "llama-3.3-70b": {"name": "Llama 3.3 70B", "cost": {"input": 0.0, "output": 0.0},
                              "tool_call": True, "limit": {"context": 128000},
                              "modalities": {"input": ["text"], "output": ["text"]}},
        }},
    }

    with patch.object(sources.openrouter, "fetch", return_value=fake_or), \
         patch.object(sources.huggingface, "fetch", return_value=fake_hf), \
         patch.object(sources.models_dev, "fetch", return_value=fake_md), \
         patch.object(sources.openai_compat, "list_models", return_value=[]), \
         patch.object(sources.openai_compat, "verify_openai_compatible", return_value=False), \
         patch.object(sources.community_lists, "fetch_all", return_value=[]):
        snap = run()

    # OpenRouter: 2 free models added under p_openrouter
    or_models = [m for m in snap.models if m.provider_id == "p_openrouter" and m.is_free]
    assert len(or_models) >= 2

    # HF: at least the seeded gpt-oss plus the new llama-3.1 free model
    hf_models = [m for m in snap.models if m.provider_id == "p_hf" and m.is_free]
    assert any("Llama-3.1-8B" in m.model_id for m in hf_models)

    # Flagships: DeepSeek-V3 should appear since input+output > 0 and < threshold
    flagship_names = [f.display_name for f in snap.cheap_flagships]
    assert any("DeepSeek" in n for n in flagship_names)

    # Groq's $0 model should NOT appear (free is not flagship).
    assert not any("Groq" in n for n in flagship_names)
