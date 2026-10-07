"""Search candidates require provider grounding, never URLs in generated prose."""

import hashlib
import io
import json
from types import SimpleNamespace

import pytest

from model_gateway import ModelGateway
from provider_health import ProviderError


def response(*, annotations=(), sources=(), search_status="completed", text=""):
    return {
        "status": "completed",
        "model": "gpt-4.1-mini-2025-04-14",
        "output": [
            {
                "type": "web_search_call",
                "status": search_status,
                "action": {"type": "search", "sources": list(sources)},
            },
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": text, "annotations": list(annotations)}
                ],
            },
        ],
    }


def gateway_response(monkeypatch, payload):
    gateway = ModelGateway({"search": "openai"}, {"search": "gpt-4.1-mini"}, {})
    raw = json.dumps(payload).encode()
    monkeypatch.setattr(gateway, "request", lambda stage, body: (payload, raw))
    return gateway


def test_search_sends_utf8_query_separately_and_requests_tool_sources(monkeypatch, tmp_path):
    source = {"type": "url", "url": "https://example.org/economy", "title": "Economy"}
    raw = json.dumps(response(sources=[source])).encode()
    requests = []

    def open_request(request, **kwargs):
        requests.append(request)
        return io.BytesIO(raw)

    monkeypatch.setattr(
        "model_gateway.urllib.request.build_opener",
        lambda *handlers: SimpleNamespace(open=open_request),
    )
    gateway = ModelGateway(
        {"search": "openai"},
        {"search": "gpt-4.1-mini"},
        {"openai": {"key": "fixture-secret"}},
    )
    query = "báo cáo kinh tế tỉnh Hà Nam từ 2016 đến 2026"
    constraints = {"scope": "Văn hóa và kinh tế Hà Nam 2016–2026"}
    results, evidence = gateway.search(query, tmp_path, 1, constraints)

    request = requests[0]
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert query.encode() in request.data
    assert b"\\u00e0" not in request.data
    body = json.loads(request.data)
    assert body["input"][-1] == {"role": "user", "content": query}
    assert body["input"][0]["role"] == "system"
    assert constraints["scope"] in body["input"][0]["content"]
    assert body["tool_choice"] == "required"
    assert body["include"] == ["web_search_call.action.sources"]
    assert results == [{"url": source["url"], "title": "Economy"}]
    assert evidence["web_search_calls"] == 1
    assert evidence["sha256"] == hashlib.sha256(raw).hexdigest()
    assert (tmp_path / "gateway-search-1.json").read_bytes() == raw
    assert b"fixture-secret" not in raw


def test_cited_urls_are_prioritized_and_tool_sources_are_deduplicated(monkeypatch, tmp_path):
    cited = "https://example.org/cited"
    additional = "https://example.org/consulted"
    payload = response(
        annotations=[{"type": "url_citation", "url": cited, "title": "Cited page"}],
        sources=[{"type": "url", "url": cited}, {"type": "url", "url": additional}],
        text="An invented URL must not become a candidate: https://example.org/invented",
    )
    gateway = gateway_response(monkeypatch, payload)
    results, _ = gateway.search("query", tmp_path, 1)
    assert results == [
        {"url": cited, "title": "Cited page"},
        {"url": additional, "title": additional},
    ]


@pytest.mark.parametrize(
    "payload",
    [
        response(),
        response(text="Source: https://example.org/unverified"),
        response(annotations=[{"url": "https://example.org/untyped"}]),
        response(annotations=[{"type": "file_citation", "url": "https://example.org/file"}]),
        response(sources=[{"type": "unknown", "url": "https://example.org/unknown"}]),
        response(sources=[{"type": "url", "url": "file:///tmp/source"}]),
        response(
            sources=[{"type": "url", "url": "https://example.org/failed"}],
            search_status="failed",
        ),
        response(
            annotations=[{"type": "url_citation", "url": "https://example.org/unsearched"}],
            search_status="failed",
        ),
    ],
)
def test_empty_or_untrusted_search_evidence_is_rejected(monkeypatch, tmp_path, payload):
    gateway = gateway_response(monkeypatch, payload)
    with pytest.raises(ProviderError) as caught:
        gateway.search("query", tmp_path, 1)
    assert caught.value.code == "NO_SEARCH_CITATIONS"
    assert (tmp_path / "gateway-search-1.json").is_file()


def test_sources_from_failed_call_are_not_attributed_to_completed_call(monkeypatch, tmp_path):
    payload = response(
        sources=[{"type": "url", "url": "https://example.org/failed"}],
        search_status="failed",
    )
    payload["output"].insert(0, {"type": "web_search_call", "status": "completed"})
    gateway = gateway_response(monkeypatch, payload)
    with pytest.raises(ProviderError) as caught:
        gateway.search("query", tmp_path, 1)
    assert caught.value.code == "NO_SEARCH_CITATIONS"


def test_incomplete_response_cannot_supply_candidates(monkeypatch, tmp_path):
    payload = response(sources=[{"type": "url", "url": "https://example.org/source"}])
    payload["status"] = "incomplete"
    gateway = gateway_response(monkeypatch, payload)
    with pytest.raises(ProviderError) as caught:
        gateway.search("query", tmp_path, 1)
    assert caught.value.code == "INCOMPLETE_OUTPUT"
