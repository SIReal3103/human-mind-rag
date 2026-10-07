"""Native settings parity and lifecycle checks; no paid network calls."""

import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

from credentials import CredentialStore
from pipeline import Pipeline, fingerprint
from store import Conflict, Store, today
from upstream_config import current_config, native_environment, read_config, routing_signature


def test_native_configuration_uses_upstream_values_and_never_returns_key(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("THUCCHIEN_API_KEY", "isolated-legacy-key-not-sent")
    monkeypatch.setenv("OPENAI_SEARCH_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "1536")
    config = read_config()
    assert config["provider"] == "openai"
    assert config["text_model"] == "gpt-4.1-mini"
    assert config["embedding_model"] == "text-embedding-3-small"
    assert config["dimensions"] == 1536
    assert config["endpoints"] == {
        "text_search": "https://api.openai.com/v1/responses",
        "embedding": "https://api.openai.com/v1/embeddings",
    }
    assert config["key"] == {
        "name": "THUCCHIEN_API_KEY",
        "configured": True,
        "source": "environment",
    }
    assert "isolated-legacy-key-not-sent" not in json.dumps(config)
    monkeypatch.setenv("OPENAI_API_KEY", "isolated-preferred-key-not-sent")
    assert read_config()["key"]["name"] == "OPENAI_API_KEY"


def test_native_environment_does_not_insert_provider_or_capability_defaults(monkeypatch):
    from upstream_config import SETTING_NAMES

    for name in SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)
    environment = native_environment()
    assert not set(SETTING_NAMES).intersection(environment)
    # Parse/chunk subprocesses retain their separate key-free environment.
    from ingestion import _worker_environment

    assert _worker_environment()["OPENAI_API_KEY"] == ""


def test_environment_file_and_defaults_match_real_gateway(tmp_path):
    # Redirect only the gateway module's file location to a test .env.local.
    # Its actual setting/provider/model functions remain unchanged.
    (tmp_path / ".env.local").write_text(
        "AI_PROVIDER=btc\nBTC_API_KEY=test-file-key\nBTC_TEXT_MODEL=gpt-6-luna\n"
        "BTC_EMBEDDING_MODEL=text-multilingual-embedding-002\nEMBEDDING_DIMENSIONS=768\n"
        "BTC_STRUCTURED_VERIFIED=1\n"
    )
    program = """import sys,os,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from ingestion import _require_upstream
sys.path.insert(0,_require_upstream()['path'])
import gateway
from upstream_config import current_config,SETTING_NAMES
for name in SETTING_NAMES:os.environ.pop(name,None)
gateway.__file__=str(Path(sys.argv[2])/'gateway.py')
config=current_config()
assert config['provider']=='btc' and config['key']['source']=='upstream .env.local'
assert config['capabilities']['BTC_STRUCTURED_VERIFIED'] is True
assert config['embedding_model']=='text-multilingual-embedding-002'
os.environ['AI_PROVIDER']='openai'
os.environ['OPENAI_SEARCH_MODEL']='gpt-4.1-mini'
os.environ['OPENAI_API_KEY']='test-env-key'
os.environ['EMBEDDING_DIMENSIONS']='1536'
config=current_config()
assert config['provider']=='openai' and config['dimensions']==1536
assert config['text_model']==gateway.text_model()
assert config['endpoints']['text_search']==gateway.endpoint('responses')
assert 'test-env-key' not in json.dumps(config) and 'test-file-key' not in json.dumps(config)
(Path(sys.argv[2])/'.env.local').unlink()
for name in SETTING_NAMES:os.environ.pop(name,None)
config=current_config()
assert config['provider']=='openai' and config['text_model']=='gpt-4.1-mini'
assert config['embedding_model']=='text-embedding-3-small' and config['dimensions']==1536
assert config['key']['configured'] is False
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            program,
            str(Path(__file__).resolve().parents[1]),
            str(tmp_path),
        ],
        env=native_environment(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_native_worker_never_installs_adapter_or_changes_prompt(monkeypatch, tmp_path):
    # Native BTC gate fails before network; compare actual function identities.
    from ingestion import _require_upstream

    sys.path.insert(0, _require_upstream()["path"])
    import gateway
    import bot
    import semantic
    import data_pipeline
    from pipeline_worker import execute

    functions = (
        gateway.structured_request,
        gateway.search_gateway,
        semantic.structured_request,
        data_pipeline.structured_request,
        data_pipeline.embedding_request,
        bot.discover,
    )
    result = execute(
        {
            "action": "crawl",
            "scope": "Kinh tế Hà Nam 2020–2024",
            "folder": str(tmp_path),
            "max_sources": 1,
            "max_pages": 1,
            "max_depth": 0,
            "api_config": current_config(),
        }
    )
    assert "BTC_STRUCTURED_VERIFIED" in result["error"]
    assert functions == (
        gateway.structured_request,
        gateway.search_gateway,
        semantic.structured_request,
        data_pipeline.structured_request,
        data_pipeline.embedding_request,
        bot.discover,
    )
    assert not (tmp_path / "api-events.json").exists()
    assert not list(tmp_path.rglob("document-check-*-repair*"))


def test_native_worker_rejects_changed_config_before_call(tmp_path):
    from pipeline_worker import execute

    config = current_config()
    config["text_model"] = "different-model"
    with pytest.raises(ValueError, match="UPSTREAM_CONFIG_CHANGED"):
        execute({"action": "crawl", "folder": str(tmp_path), "api_config": config})
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "override", ["provider", "key_group", "stage_models", "stage_providers", "model", "dimensions"]
)
def test_new_jobs_reject_ui_api_overrides(tmp_path, override):
    pipeline = Pipeline(Store(tmp_path), CredentialStore(tmp_path))
    with pytest.raises(ValueError, match="không nhận chọn provider/model"):
        pipeline.start(
            {
                "action": "crawl",
                "collection": "test",
                "scope": "Tài liệu công khai kiểm thử",
                override: "old-ui",
            }
        )
    assert pipeline.list() == []


def test_old_adapter_index_and_changed_native_config_cannot_query(tmp_path):
    pipeline = Pipeline(Store(tmp_path), CredentialStore(tmp_path))
    config = read_config()
    job = {
        "id": uuid4().hex,
        "action": "build",
        "status": "ready",
        "collection": "test",
        "as_of": today(),
        "approved_versions": fingerprint([]),
        "api_config": config,
    }
    pipeline.save(job)
    with pytest.raises(Conflict, match="adapter API cũ"):
        pipeline.evidence(job["id"], "Câu hỏi kiểm thử")
    job["integration"] = "upstream-native-api"
    job["api_config"]["embedding_model"] = "different-embedding"
    pipeline.save(job)
    with pytest.raises(Conflict, match="khác index"):
        pipeline.evidence(job["id"], "Câu hỏi kiểm thử")
    assert routing_signature(config)["embedding_model"] == "different-embedding"


def test_config_endpoint_redacts_key_and_does_not_call_provider(tmp_path):
    from fastapi.testclient import TestClient
    from app import create_app

    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        response = client.get("/api/upstream/config")
        assert response.status_code == 200
        assert response.json()["provider"] == "btc"
        assert "isolated-test-key-never-sent" not in response.text
        assert client.get("/api/pipeline").json() == {"jobs": []}


def test_worker_freezes_native_profile_when_config_file_changes(tmp_path):
    program = """import sys,os
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from ingestion import _require_upstream
sys.path.insert(0,_require_upstream()['path'])
import gateway,data_pipeline
from upstream_config import freeze_config,current_config,SETTING_NAMES
for name in SETTING_NAMES:os.environ.pop(name,None)
path=Path(sys.argv[2])/'.env.local'
path.write_text('AI_PROVIDER=btc\\nBTC_API_KEY=original-fixture-key\\nBTC_STRUCTURED_VERIFIED=0\\n')
gateway.__file__=str(path.with_name('gateway.py'))
functions=(gateway.setting,gateway.structured_request,gateway.search_gateway,data_pipeline.embedding_request)
expected=current_config()
freeze_config(expected)
path.write_text('AI_PROVIDER=openai\\nOPENAI_API_KEY=replaced-fixture-key\\nBTC_STRUCTURED_VERIFIED=1\\nBTC_TEXT_MODEL=changed\\n')
assert gateway.provider()=='btc'
assert gateway.gateway_key()=='original-fixture-key'
assert gateway.text_model()==expected['text_model']
assert gateway.setting('BTC_STRUCTURED_VERIFIED')=='0'
assert gateway.endpoint('responses')==expected['endpoints']['text_search']
assert functions==(gateway.setting,gateway.structured_request,gateway.search_gateway,data_pipeline.embedding_request)
try:gateway.require_capability('BTC_STRUCTURED_VERIFIED')
except ValueError:pass
else:raise AssertionError('Gate changed after freeze')
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            program,
            str(Path(__file__).resolve().parents[1]),
            str(tmp_path),
        ],
        env=native_environment(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
