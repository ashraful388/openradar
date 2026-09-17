from __future__ import annotations
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

from openradar import cli
from openradar.models import Model, Provider, Snapshot
from openradar.sources import public_catalog as catalog

OLD = "2026-01-01T00:00:00Z"
NOW = "2026-09-17T00:00:00Z"
FUTURE = "2027-01-01T00:00:00Z"


def groq_html(mid="openai/gpt-oss-120b", limits=None, selected="free"):
    limits = limits or ["30", "1K", "8K", "200K", "-", "-"]
    free_class = "happy bg-black" if selected == "free" else ""
    developer_class = "happy bg-black" if selected == "developer" else ""
    headers = "".join(f'<th data-column-index="{i}"><span>{h}</span></th>' for i, h in enumerate(catalog.HEADERS))
    cells = "".join(f"<td><div>{v}</div></td>" for v in [mid, *limits])
    return (
        '<div class="w-full"><div class="sticky"><div><table><thead>'
        '<tr data-role="legend"><th colspan="6"><nav><ul><li>'
        f'<button class="{free_class}">Free Plan Limits</button></li><li>'
        f'<button class="{developer_class}">Developer Plan Limits</button>'
        f'</li></ul></nav></th><th></th></tr><tr>{headers}</tr></thead></table></div></div>'
        f'<div><div><table><tbody><tr>{cells}</tr></tbody></table></div></div></div>'
    )


def token_html(mid="openai/example:free"):
    return (
        '<html><head><title>Models | TokenRouter</title></head><body>'
        '<p>Free models available</p><ul class="tr-seo-grid"><li class="tr-seo-card">'
        f'<h2><a href="/models/{mid}/">{mid}</a></h2><p>Provider: OpenAI</p>'
        '</li></ul></body></html>'
    )


def token_noscript_html(mid="openai/example:free"):
    grid = token_html(mid).split('<ul class="tr-seo-grid">', 1)[1].split('</ul>', 1)[0]
    return (
        '<!doctype html><html><head><title>Models | TokenRouter</title></head><body>'
        '<noscript><iframe src="https://www.googletagmanager.com/ns.html"></iframe></noscript>'
        '<div id="root"></div><noscript><div><main class="tr-seo-main"><article>'
        '<h1>Models</h1><p class="tr-seo-lead">Browse currently available AI models.</p>'
        f'<div class="tr-seo-content"><ul class="tr-seo-grid">{grid}</ul></div>'
        '</article></main></div></noscript>'
        '<script>document.getElementById("root").innerHTML = "Loading";</script>'
        '</body></html>'
    )


def test_tokenrouter_noscript_public_catalog_regression():
    rows = catalog.parse_tokenrouter(token_noscript_html())
    assert rows == [catalog.CatalogRow("openai/example:free")]
    assert rows[0].free_limit == ""


@pytest.mark.parametrize("tag", ["script", "style", "template"])
def test_tokenrouter_excludes_non_catalog_payloads(tag):
    fake = token_html("fake/model:free")
    html = token_noscript_html().replace('</body>', f'<{tag}>{fake}</{tag}></body>')
    assert catalog.parse_tokenrouter(html) == [catalog.CatalogRow("openai/example:free")]
    with pytest.raises(ValueError, match="missing TokenRouter public catalog"):
        catalog.parse_tokenrouter(f'<html><body><{tag}>{fake}</{tag}></body></html>')


def test_tokenrouter_shell_with_script_catalog_fails_closed():
    html = '<html><body><div id="root"></div><script>' + token_html() + '</script></body></html>'
    with pytest.raises(ValueError, match="missing TokenRouter public catalog"):
        catalog.parse_tokenrouter(html)


def test_tokenrouter_ambiguous_visible_and_noscript_catalog_fails_closed():
    with pytest.raises(ValueError, match="missing TokenRouter public catalog"):
        catalog.parse_tokenrouter(token_html() + token_noscript_html())


def test_groq_does_not_read_noscript_catalog():
    with pytest.raises(ValueError, match="missing or ambiguous Groq plan controls"):
        catalog.parse_groq('<noscript>' + groq_html() + '</noscript>')


def test_tokenrouter_fetch_noscript_catalog_regression():
    calls = []
    responses = [(308, {"location": "/models/"}, b""),
                 (200, {"content-type": "text/html; charset=utf-8"}, token_noscript_html().encode())]
    with patch.object(httpx, "stream", side_effect=mock_stream(responses, calls)):
        assert catalog.fetch("p_tokenrouter") == [catalog.CatalogRow("openai/example:free")]
    assert len(calls) == 2


def snapshot(*provider_ids):
    return Snapshot(
        providers=[Provider(id=pid, slug=pid[2:], name=pid[2:], region="Global",
                            probe_status="needs_key", status="stale", last_verified=OLD)
                   for pid in provider_ids],
        models=[], cheap_flagships=[],
    )


def model(pid="p_groq", mid="openai/gpt-oss-120b", **kwargs):
    return Model(id=f"{pid}:{mid}", provider_id=pid, model_id=mid,
                 display_name="Existing name", modality=["chat"], last_verified=OLD, **kwargs)


@pytest.fixture(autouse=True)
def isolated():
    with patch.object(httpx, "stream", side_effect=AssertionError("unexpected network")), \
         patch.object(httpx, "get", side_effect=AssertionError("unexpected network")), \
         patch.object(httpx.Client, "send", side_effect=AssertionError("unexpected network")), \
         patch.object(cli, "now", return_value=NOW), \
         patch.object(cli, "_data_dir", side_effect=AssertionError("unexpected data access")), \
         patch.object(cli.provider_keys, "get", side_effect=AssertionError("unexpected credential access")):
        yield


def test_groq_selected_free_plan_only():
    html = groq_html() + groq_html("developer-only", selected="developer").replace("Free Plan Limits", "Other Plan")
    html += '<script>"free": ["fake-model"]</script><table><tr><td>unrelated-free</td></tr></table>'
    rows = catalog.parse_groq(html)
    assert [r.model_id for r in rows] == ["openai/gpt-oss-120b"]
    assert rows[0].free_limit == "Groq Free Plan Limits (RPM: 30, RPD: 1K, TPM: 8K, TPD: 200K, ASH: -, ASD: -)"


@pytest.mark.parametrize("html", [
    "", "Free Plan Limits developer-only", "<html><body><div id='root'></div></body></html>",
    groq_html(selected="developer"), groq_html(selected="none"),
    groq_html().replace("Free Plan Limits", "Free trial"),
    groq_html().replace("MODEL ID", "MODEL"), groq_html().replace("</tbody>", ""),
    groq_html().replace("<td><div>30</div></td>", ""),
    groq_html(limits=["unknown", "1K", "8K", "200K", "-", "-"]),
    groq_html(mid="not a model"), groq_html() + groq_html(),
    groq_html().replace("<tr><td>", "<tr><td colspan='2'>").replace("</table></div></div></div>", "</table><table></table></div></div></div>"),
])
def test_groq_invalid_markup_fails_closed(html):
    with pytest.raises(ValueError):
        catalog.parse_groq(html)


def test_groq_zero_capacity_is_listing_only():
    assert catalog.parse_groq(groq_html(limits=["0", "1K", "8K", "200K", "-", "-"]))[0].free_limit == ""


def test_tokenrouter_listing_is_not_free_evidence():
    rows = catalog.parse_tokenrouter(token_html())
    assert rows == [catalog.CatalogRow("openai/example:free")]


@pytest.mark.parametrize("html", [
    "", '<div id="root"></div>', '<a href="/models/guess:free/">guess:free</a>',
    token_html().replace("tr-seo-grid", "new-grid"),
    token_html().replace('href="/models/', 'href="https://other.example/models/'),
    token_html().replace("</li>", ""), token_html(mid="../escape"),
    token_html().replace('>openai/example:free</a>', '>Different ID</a>'),
])
def test_tokenrouter_invalid_markup_fails_closed(html):
    with pytest.raises(ValueError):
        catalog.parse_tokenrouter(html)


@pytest.mark.parametrize("status", ["needs_key", "gated", "error", "skipped"])
def test_gated_repeat_merge_and_schema_roundtrip(status):
    snap = snapshot("p_groq", "p_tokenrouter")
    snap.providers[0].probe_status = status
    before = [p.model_dump() for p in snap.providers]
    snap.models.append(model(context_window=12345))
    original = snap.models[0]
    with patch.object(catalog, "fetch", side_effect=lambda pid: catalog.parse_groq(groq_html()) if pid == "p_groq" else catalog.parse_tokenrouter(token_html())):
        assert cli.ingest_public_catalog(snap) == 1
        assert cli.ingest_public_catalog(snap) == 0
    assert len(snap.models) == 2
    assert original.display_name == "Existing name"
    assert original.context_window == 12345
    assert original.last_verified == OLD
    assert original.is_free and original.free_evidence_source == "docs"
    assert original.free_evidence_timestamp == NOW
    assert original.catalog_checked_at == NOW
    assert original.catalog_source_url == catalog.URLS["p_groq"]
    assert original.input_per_1m is None and original.output_per_1m is None
    assert original.free_verified_at is None
    listing = snap.models[1]
    assert not listing.is_free and listing.free_evidence_source is None
    assert listing.input_per_1m is None and listing.output_per_1m is None
    assert listing.last_verified == "" and listing.free_verified_at is None
    assert listing.catalog_source_url == catalog.URLS["p_tokenrouter"]
    assert [p.model_dump() for p in snap.providers] == before
    assert Snapshot.model_validate_json(snap.model_dump_json()) == snap
    assert cli._cleanup_legacy_free_claims(snap) == 0


@pytest.mark.parametrize("prices", [{"input_per_1m": 1.2}, {"output_per_1m": 2.4}, {"input_per_1m": 0, "output_per_1m": 3}])
@pytest.mark.parametrize("is_free", [False, True])
def test_positive_prices_never_free(prices, is_free):
    snap = snapshot("p_groq")
    snap.models.append(model(is_free=is_free, cache_read_per_1m=0.3, **prices))
    with patch.object(catalog, "fetch", return_value=catalog.parse_groq(groq_html())):
        cli.ingest_public_catalog(snap)
    m = snap.models[0]
    assert not m.is_free
    assert m.free_kind == "byok_required"
    for key, value in prices.items():
        assert getattr(m, key) == value
    assert m.cache_read_per_1m == 0.3
    assert m.catalog_checked_at == NOW


@pytest.mark.parametrize("source", ["probe", "verifier", "models_dev", "openrouter", "bai", "xkiro", "huggingface"])
@pytest.mark.parametrize("is_free", [False, True])
def test_stronger_evidence_preserved(source, is_free):
    snap = snapshot("p_groq")
    m = model(is_free=is_free, free_evidence_source=source, free_evidence_timestamp=OLD,
              free_kind="trial_card", free_limit="existing evidence")
    snap.models.append(m)
    before = m.model_dump(exclude={"catalog_source_url", "catalog_checked_at"})
    with patch.object(catalog, "fetch", return_value=catalog.parse_groq(groq_html())):
        cli.ingest_public_catalog(snap)
    assert m.model_dump(exclude={"catalog_source_url", "catalog_checked_at"}) == before


@pytest.mark.parametrize("extra", [
    {"free_evidence_source": "declared", "free_evidence_timestamp": FUTURE},
    {"free_evidence_source": "docs", "free_evidence_timestamp": FUTURE},
    {"free_verified_at": OLD},
])
def test_newer_or_probe_evidence_preserved(extra):
    snap = snapshot("p_groq")
    m = model(**extra)
    snap.models.append(m)
    before = m.model_dump(exclude={"catalog_source_url", "catalog_checked_at"})
    with patch.object(catalog, "fetch", return_value=catalog.parse_groq(groq_html())):
        cli.ingest_public_catalog(snap)
    assert m.model_dump(exclude={"catalog_source_url", "catalog_checked_at"}) == before


def test_declared_evidence_upgraded_and_case_merge():
    snap = snapshot("p_groq")
    snap.models.append(model(mid="OPENAI/GPT-OSS-120B", free_evidence_source="declared", free_evidence_timestamp=OLD))
    with patch.object(catalog, "fetch", return_value=catalog.parse_groq(groq_html())):
        assert cli.ingest_public_catalog(snap) == 0
    assert snap.models[0].free_evidence_source == "docs"


def test_success_demotes_only_docs_owned_claims():
    snap = snapshot("p_groq", "p_tokenrouter")
    for mid, extra in [
        ("gone", {}), ("probe", {"free_verified_at": OLD}),
        ("newer", {"free_evidence_timestamp": FUTURE}),
        ("other-source", {"free_evidence_source": "verifier"}),
        ("other-url", {"catalog_source_url": "https://other.example/models"}),
    ]:
        values = dict(is_free=True, free_kind="free_tier", free_limit="old docs",
                      free_evidence_source="docs", free_evidence_timestamp=OLD,
                      catalog_source_url=catalog.URLS["p_groq"], catalog_checked_at=OLD)
        values.update(extra)
        snap.models.append(model(mid=mid, **values))
    snap.models.append(model(pid="p_tokenrouter", mid="gone", is_free=True, free_evidence_source="docs"))
    with patch.object(catalog, "fetch", side_effect=lambda pid: catalog.parse_groq(groq_html()) if pid == "p_groq" else catalog.parse_tokenrouter(token_html())):
        cli.ingest_public_catalog(snap)
    gone = snap.models[0]
    assert not gone.is_free and gone.free_evidence_source is None
    assert gone.free_evidence_timestamp is None and gone.free_limit == ""
    assert gone.catalog_source_url == catalog.URLS["p_groq"]
    assert gone.catalog_checked_at == OLD
    assert all(m.is_free for m in snap.models[1:6])
    assert any(c.kind == "expired" for c in snap.changelog)


@pytest.mark.parametrize("failure", [ValueError("bad markup"), httpx.ReadTimeout("timeout")])
def test_provider_failure_is_independent_and_never_demotes(failure):
    snap = snapshot("p_groq", "p_tokenrouter")
    snap.models.append(model(is_free=True, free_evidence_source="docs",
                             catalog_source_url=catalog.URLS["p_groq"], catalog_checked_at=OLD))
    before = snap.models[0].model_dump()
    with patch.object(catalog, "fetch", side_effect=[failure, catalog.parse_tokenrouter(token_html())]) as fetch:
        assert cli.ingest_public_catalog(snap) == 1
    assert fetch.call_count == 2
    assert snap.models[0].model_dump() == before
    assert "refresh failed" in snap.changelog[0].text


def test_absent_live_unknown_and_cross_provider_attribution():
    snap = snapshot("p_openai", "p_groq", "p_tokenrouter")
    snap.providers[1].probe_status = "ok"
    snap.providers[2].probe_status = ""
    with patch.object(catalog, "fetch") as fetch:
        assert cli.ingest_public_catalog(snap) == 0
        fetch.assert_not_called()
    snap = snapshot("p_openai", "p_tokenrouter")
    snap.models.append(model(pid="p_openai", mid="openai/example:free"))
    with patch.object(catalog, "fetch", return_value=catalog.parse_tokenrouter(token_html())) as fetch:
        assert cli.ingest_public_catalog(snap) == 1
        fetch.assert_called_once_with("p_tokenrouter")
    assert snap.models[0].catalog_source_url is None
    assert not any(m.is_free for m in snap.models)
    assert snap.models[1].provider_id == "p_tokenrouter"


def mock_stream(responses, calls):
    @contextmanager
    def stream(method, url, **kwargs):
        calls.append((method, url, kwargs))
        status, headers, content = responses.pop(0)
        response = httpx.Response(status, headers=headers, content=content,
                                  request=httpx.Request(method, url))
        try:
            yield response
        finally:
            response.close()
    return stream


def test_public_fetch_allowlisted_redirect_and_no_credentials():
    calls = []
    responses = [(308, {"location": "/models/"}, b""),
                 (200, {"content-type": "text/html; charset=utf-8"}, token_html().encode())]
    with patch.object(httpx, "stream", side_effect=mock_stream(responses, calls)):
        assert catalog.fetch("p_tokenrouter") == [catalog.CatalogRow("openai/example:free")]
    assert [c[1] for c in calls] == [catalog.URLS["p_tokenrouter"], catalog.URLS["p_tokenrouter"] + "/"]
    for method, url, kwargs in calls:
        assert method == "GET"
        assert kwargs["headers"] == {"Accept": "text/html"}
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        assert 0 < kwargs["timeout"] <= 10


@pytest.mark.parametrize("status,headers,content", [
    (302, {"location": "https://other.example/models"}, b""),
    (403, {"content-type": "text/html"}, b"blocked"),
    (200, {"content-type": "application/json"}, b"{}"),
    (200, {"content-type": "text/html"}, b"x" * (catalog.MAX_BYTES + 1)),
    (200, {"content-type": "text/html"}, b"<div id='root'></div>"),
], ids=["redirect", "forbidden", "json", "oversized", "shell"])
def test_public_fetch_fails_closed(status, headers, content):
    calls = []
    with patch.object(httpx, "stream", side_effect=mock_stream([(status, headers, content)], calls)):
        with pytest.raises((ValueError, httpx.HTTPError)):
            catalog.fetch("p_groq")
    assert len(calls) == 1


def test_spa_shell_has_no_fabricated_models():
    calls = []
    responses = [(200, {"content-type": "text/html"}, b"<html><body><div id='root'></div></body></html>")]
    snap = snapshot("p_tabitoken")
    with patch.object(httpx, "stream", side_effect=mock_stream(responses, calls)):
        assert cli.ingest_public_catalog(snap) == 0
    assert snap.models == []
    assert len(calls) == 1


def test_unknown_provider_cannot_fetch_arbitrary_url():
    with pytest.raises(KeyError):
        catalog.fetch("https://other.example")


def test_groq_fetch_parses_public_html():
    calls = []
    responses = [(200, {"content-type": "text/html"}, groq_html().encode())]
    with patch.object(httpx, "stream", side_effect=mock_stream(responses, calls)):
        rows = catalog.fetch("p_groq")
    assert rows[0].free_limit.startswith("Groq Free Plan Limits")
    assert len(calls) == 1


def test_successful_refresh_with_zero_capacity_demotes_docs_claim():
    snap = snapshot("p_groq")
    m = model(is_free=True, free_evidence_source="docs", free_evidence_timestamp=OLD,
              catalog_source_url=catalog.URLS["p_groq"], catalog_checked_at=OLD)
    snap.models.append(m)
    rows = catalog.parse_groq(groq_html(limits=["0.0K", "1K", "8K", "200K", "-", "-"]))
    with patch.object(catalog, "fetch", return_value=rows):
        cli.ingest_public_catalog(snap)
    assert not m.is_free and m.free_evidence_source is None
    assert m.catalog_checked_at == NOW


def test_empty_refresh_does_not_demote():
    snap = snapshot("p_groq")
    snap.models.append(model(is_free=True, free_evidence_source="docs"))
    before = snap.models[0].model_dump()
    with patch.object(catalog, "fetch", return_value=[]):
        assert cli.ingest_public_catalog(snap) == 0
    assert snap.models[0].model_dump() == before


def test_newer_catalog_preserved():
    snap = snapshot("p_groq")
    m = model(is_free=True, free_evidence_source="docs", free_evidence_timestamp=OLD,
              catalog_source_url=catalog.URLS["p_groq"], catalog_checked_at=FUTURE)
    snap.models.append(m)
    before = m.model_dump()
    with patch.object(catalog, "fetch", return_value=catalog.parse_groq(groq_html())):
        cli.ingest_public_catalog(snap)
    assert m.model_dump() == before


def test_redirect_loop_is_bounded():
    calls = []
    responses = [(308, {"location": "/models/"}, b"")] * 2
    with patch.object(httpx, "stream", side_effect=mock_stream(responses, calls)):
        with pytest.raises(ValueError):
            catalog.fetch("p_tokenrouter")
    assert len(calls) == 2


def test_public_fetch_deadline_is_bounded():
    with patch.object(catalog.time, "monotonic", side_effect=[0, 21]):
        with pytest.raises(ValueError, match="timed out"):
            catalog.fetch("p_groq")


def test_dedup_retains_catalog_provenance():
    snap = snapshot("p_groq")
    snap.models = [model(mid="OPENAI/GPT-OSS-120B"), model(catalog_source_url=catalog.URLS["p_groq"], catalog_checked_at=NOW)]
    assert cli._dedup_models(snap) == 1
    assert snap.models[0].catalog_checked_at == NOW
    assert snap.models[0].catalog_source_url == catalog.URLS["p_groq"]
