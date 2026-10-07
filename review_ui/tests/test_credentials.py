"""Credential boundaries use generated test-only strings, never operator keys."""

import json
import stat
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import create_app
from credentials import CredentialStore


def client_for(folder):
    client = TestClient(create_app(folder), base_url="http://127.0.0.1")
    client.headers["x-csrf-token"] = client.get("/api/config").json()["csrf_token"]
    return client


def key_fixture():
    return "test-only-" + uuid4().hex


def test_keys_persist_separately_and_responses_never_return_secrets(tmp_path):
    keys = {provider: key_fixture() for provider in ("btc", "openai", "google")}
    with client_for(tmp_path) as client:
        for provider, key in keys.items():
            response = client.put(f"/api/credentials/{provider}", json={"api_key": key})
            assert response.status_code == 200
            assert all(secret not in response.text for secret in keys.values())
        for url in (
            "/api/credentials",
            "/api/config",
            "/api/export",
            "/api/documents",
            "/openapi.json",
        ):
            response = client.get(url)
            assert response.status_code == 200
            assert all(secret not in response.text for secret in keys.values())
    with client_for(tmp_path) as restarted:
        providers = restarted.get("/api/credentials").json()["providers"]
        assert {p["id"] for p in providers if p["configured"]} == set(keys)
        assert {p["group"] for p in providers if p["id"] == "btc"} == {"btc"}
        assert all(p["connection_status"] == "not_tested" for p in providers)
    path = tmp_path / "credentials/providers.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    record = json.loads(path.read_text())
    assert {provider: item["api_key"] for provider, item in record.items()} == keys
    assert all(
        secret.encode() not in (tmp_path / "review.sqlite").read_bytes() for secret in keys.values()
    )


def test_replacement_and_removal_affect_only_selected_provider(tmp_path):
    store = CredentialStore(tmp_path)
    store.put("btc", key_fixture())
    store.put("openai", key_fixture())
    replacement = key_fixture()
    store.put("openai", replacement)
    assert json.loads(store.path.read_text())["openai"]["api_key"] == replacement
    store.remove("openai")
    assert set(json.loads(store.path.read_text())) == {"btc"}


def test_invalid_requests_cannot_echo_keys(tmp_path):
    secret = key_fixture()
    with client_for(tmp_path) as client:
        for body in (
            [secret],
            {"api_key": [secret]},
            {"api_key": secret + " invalid"},
            {"api_key": secret, "extra": secret},
        ):
            response = client.put("/api/credentials/openai", json=body)
            assert response.status_code == 422
            assert secret not in response.text
        assert not (tmp_path / "credentials/providers.json").exists()


def test_credential_mutations_require_session_and_same_origin(tmp_path):
    with client_for(tmp_path) as client:
        secret = key_fixture()
        for headers in ({"x-csrf-token": "wrong"}, {"origin": "https://untrusted.example"}):
            response = client.put("/api/credentials/btc", json={"api_key": secret}, headers=headers)
            assert response.status_code == 403
            assert secret not in response.text
        assert not (tmp_path / "credentials/providers.json").exists()


def test_unknown_provider_and_corrupt_vault_fail_without_overwrite(tmp_path):
    store = CredentialStore(tmp_path)
    with pytest.raises(ValueError):
        store.put("unsupported", key_fixture())
    store.path.write_text("corrupt-test-vault")
    with pytest.raises(ValueError, match="Không đọc được"):
        store.put("btc", key_fixture())
    assert store.path.read_text() == "corrupt-test-vault"


def test_reset_clears_every_provider_persists_and_allows_new_btc(tmp_path):
    store = CredentialStore(tmp_path)
    for provider in ("btc", "openai", "google", "anthropic", "deepseek"):
        store.put(provider, key_fixture())
    with client_for(tmp_path) as client:
        documents_before = client.get("/api/documents").json()
        for _ in range(2):
            response = client.post("/api/credentials/reset", json={"confirm": True})
            assert response.status_code == 200
            assert all(
                not p["configured"] and p["updated_at"] is None
                for p in response.json()["providers"]
            )
        assert client.get("/api/documents").json() == documents_before
    assert json.loads(store.path.read_text()) == {}
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    with client_for(tmp_path) as restarted:
        assert not any(
            p["configured"] for p in restarted.get("/api/credentials").json()["providers"]
        )
        response = restarted.put("/api/credentials/btc", json={"api_key": key_fixture()})
        assert {p["id"] for p in response.json()["providers"] if p["configured"]} == {"btc"}


def test_reset_requires_explicit_confirmation_and_valid_session(tmp_path):
    store = CredentialStore(tmp_path)
    store.put("openai", key_fixture())
    before = store.path.read_bytes()
    with client_for(tmp_path) as client:
        for body in (
            {},
            {"confirm": False},
            {"confirm": "true"},
            {"confirm": 1},
            {"confirm": True, "extra": True},
        ):
            assert client.post("/api/credentials/reset", json=body).status_code == 422
            assert store.path.read_bytes() == before
        for headers in ({"x-csrf-token": "wrong"}, {"origin": "https://untrusted.example"}):
            assert (
                client.post(
                    "/api/credentials/reset", json={"confirm": True}, headers=headers
                ).status_code
                == 403
            )
            assert store.path.read_bytes() == before
