"""Safe health classification and rotation isolation; no external calls."""

import json

import pytest

from credentials import CredentialStore
from provider_health import classify_probe, diagnostic, error_diagnostic, NoProbeRedirect


@pytest.mark.parametrize(
    "provider,code,body,status",
    [
        ("openai", 401, {"error": {"message": "secret-key-fragment"}}, "invalid_key"),
        (
            "google",
            400,
            {
                "error": {
                    "details": [{"reason": "API_KEY_INVALID"}],
                    "message": "secret-key-fragment",
                }
            },
            "invalid_key",
        ),
        ("openai", 403, {"error": {}}, "permission_denied"),
        ("openai", 429, {"error": {"code": "insufficient_quota"}}, "quota_exceeded"),
        ("openai", 429, {}, "rate_limited"),
        ("google", 200, {"models": []}, "ok"),
        ("btc", 404, {}, "unsupported"),
        ("openai", 200, {"message": "secret-key-fragment"}, "request_failed"),
    ],
)
def test_probe_classification_does_not_echo_provider_body(provider, code, body, status):
    result = classify_probe(provider, code, json.dumps(body))
    assert result["status"] == status
    assert result["provider"] == provider
    assert "secret-key-fragment" not in json.dumps(result)


def test_pipeline_unknown_errors_do_not_escape_in_diagnostics():
    result = error_diagnostic("openai", "planner", ValueError("secret-key-fragment"))
    assert result["status"] == "request_failed"
    assert result["key_label"] == "OPENAI_API_KEY"
    assert "secret-key-fragment" not in json.dumps(result)


def test_health_is_bound_to_key_version_and_reset_clears_it(tmp_path):
    store = CredentialStore(tmp_path)
    store.put("openai", "test-old-key-not-sent")
    old = store.snapshot("openai")
    result = diagnostic("openai", "planner", "invalid_key", "HTTP_401")
    assert store.record_check("openai", old["version"], result)
    assert store.summary()["providers"][1]["connection_status"] == "invalid_key"
    store.put("openai", "test-new-key-not-sent")
    assert not store.record_check("openai", old["version"], result)
    assert store.summary()["providers"][1]["checks"] == {}
    current = store.snapshot("openai")
    assert store.record_check(
        "openai", current["version"], diagnostic("openai", "authentication", "ok", "HTTP_200")
    )
    assert "test-new-key-not-sent" not in json.dumps(store.summary())
    store.reset()
    assert not store.record_check("openai", current["version"], result)
    assert store.summary()["providers"][1]["checks"] == {}
    assert not store.summary()["providers"][1]["configured"]


def test_key_probe_never_follows_redirects():
    with pytest.raises(ValueError, match="redirect blocked"):
        NoProbeRedirect().redirect_request(None, None, 302, "", {}, "https://example.com/")


def test_check_api_requires_session_and_reports_missing_provider_key(tmp_path):
    from app import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        path = "/api/credentials/openai/check"
        assert client.post(path, json={}).status_code == 403
        client.headers["x-csrf-token"] = client.get("/api/config").json()["csrf_token"]
        response = client.post(path, json={})
        assert response.status_code == 422
        assert "openai" in response.json()["detail"]
        assert client.post("/api/credentials/unknown/check", json={}).status_code == 422
