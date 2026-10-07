"""Offline suite must never inherit live provider credentials from the host."""

import pytest


@pytest.fixture(autouse=True)
def isolated_provider_settings(monkeypatch):
    from upstream_config import GATES, SETTING_NAMES

    for name in SETTING_NAMES:
        if name.endswith("_API_KEY"):
            monkeypatch.setenv(name, "")
    monkeypatch.setenv("AI_PROVIDER", "btc")
    monkeypatch.setenv("BTC_API_KEY", "isolated-test-key-never-sent")
    monkeypatch.setenv("BTC_TEXT_MODEL", "gpt-6-luna")
    monkeypatch.setenv("BTC_EMBEDDING_MODEL", "text-multilingual-embedding-002")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")
    for flag in GATES:
        monkeypatch.setenv(flag, "0")
