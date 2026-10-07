"""Real approval/snapshot/chunk boundaries; no provider calls or synthetic vectors."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

from credentials import CredentialStore
from ingestion import _worker_environment
from pipeline import Pipeline, fingerprint
from store import Store, Conflict, today

TEXT = "Nội dung kiểm thử do nhóm viết để đối chiếu nguồn gốc và phiên bản tài liệu. Người duyệt cần đọc toàn bộ văn bản trước khi đưa vào bộ tài liệu phục vụ tra cứu có dẫn nguồn."


def document(store, text=TEXT):
    return store.create(
        text.encode(),
        {
            "text": text,
            "parser": "utf8",
            "segments": [{"text": text, "locator": {"kind": "document_text"}}],
        },
        {"collection": "test", "title": "Tài liệu thử"},
        source_kind="file",
        filename="source.txt",
        mime="text/plain",
    )


def approve(store, doc):
    return store.decide(
        doc["id"],
        {
            "revision": doc["revision"],
            "action": "approve",
            "actor": "Người kiểm thử",
            "acknowledge_findings": True,
        },
    )


def test_approval_gate_withdrawal_and_revisions(tmp_path):
    store = Store(tmp_path)
    pipeline = Pipeline(store, CredentialStore(tmp_path))
    doc = document(store)
    job = {"collection": "test", "as_of": today()}
    assert pipeline.eligible(job) == []
    doc = approve(store, doc)
    job["approved_versions"] = fingerprint(pipeline.eligible(job))
    pipeline.assert_current(job)
    store.decide(
        doc["id"],
        {
            "revision": doc["revision"],
            "action": "withdraw",
            "actor": "Reviewer",
            "note": "Test withdrawal",
        },
    )
    with pytest.raises(Conflict):
        pipeline.assert_current(job)
    assert pipeline.eligible(job) == []


def test_saved_evidence_api_rechecks_approval_gate_without_key(tmp_path):
    from app import create_app
    from fastapi.testclient import TestClient

    app = create_app(tmp_path)
    pipeline = app.state.pipeline
    doc = approve(pipeline.store, document(pipeline.store))
    job = {
        "id": uuid4().hex,
        "action": "build",
        "status": "ready",
        "collection": "test",
        "as_of": today(),
        "approved_versions": fingerprint([doc]),
    }
    pipeline.save(job)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        endpoint = f"/api/pipeline/{job['id']}/evidence"
        assert client.get(endpoint).json() == {"last_evidence": None}
        # Isolated saved-context fixture, no generated vectors or provider calls.
        record = {"question": "Test retrieval", "bundle": {"evidence": [{"text": TEXT}]}}
        (pipeline.folder / job["id"] / "last-evidence.json").write_text(json.dumps(record))
        assert client.get(endpoint).json()["last_evidence"] == record
        download = client.get(endpoint + "/download")
        assert download.json() == record["bundle"]
        assert "attachment" in download.headers["content-disposition"]
        pipeline.store.decide(
            doc["id"],
            {
                "revision": doc["revision"],
                "action": "withdraw",
                "actor": "Test reviewer",
                "note": "Exercise saved context withdrawal",
            },
        )
        response = client.get(endpoint)
        assert response.status_code == 409
        assert TEXT not in response.text
        assert client.get(endpoint + "/download").status_code == 409


def test_empty_parse_remains_blocked_and_pdf_mime_preserved(tmp_path):
    store = Store(tmp_path)
    pipeline = Pipeline(store, CredentialStore(tmp_path))
    identifier = uuid4().hex
    job = {
        "id": identifier,
        "action": "crawl",
        "status": "running",
        "collection": "test",
        "created_at": "test",
        "document_ids": [],
        "errors": [],
    }
    pipeline.save(job)
    run = pipeline.folder / identifier / "crawl" / "run"
    (run / "parsed").mkdir(parents=True)
    (run / "raw").mkdir()
    body = b"%PDF-isolated-contract-fixture"
    (run / "raw/source.pdf").write_bytes(body)
    parsed = {
        "text": "",
        "raw_path": "raw/source.pdf",
        "raw_sha256": hashlib.sha256(body).hexdigest(),
        "url": "https://example.com/source.pdf",
        "status": "review",
    }
    (run / "parsed/document.json").write_text(json.dumps(parsed))
    (run / "report.json").write_text(
        json.dumps({"documents": [{"parsed_path": "parsed/document.json"}]})
    )
    pipeline.import_run(job, run)
    doc = store.get(job["document_ids"][0])
    assert doc["text"] == ""
    assert doc["mime"] == "application/pdf"
    assert doc["crawl"]["job_id"] == identifier
    with pytest.raises(ValueError, match="lỗi chặn"):
        approve(store, doc)


def test_real_upstream_chunks_have_approved_provenance(tmp_path):
    store = Store(tmp_path / "db")
    doc = approve(store, document(store))
    folder = tmp_path / "snapshot"
    folder.mkdir()
    (folder / "originals").mkdir()
    (folder / "originals" / doc["id"]).write_bytes(TEXT.encode())
    (folder / "approved.json").write_text(json.dumps({"documents": [doc]}))
    root = Path(__file__).resolve().parents[1]
    # Exercise real upstream trace integrity and tokenizer without paid embedding calls.
    program = """import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from ingestion import _require_upstream
sys.path.insert(0,_require_upstream()['path'])
from pipeline_worker import prepare_snapshot
from data_pipeline import make_chunks
from trace import TraceStore
run=prepare_snapshot(Path(sys.argv[2]),'Tài liệu đã được người duyệt kiểm tra')
lineage=json.loads((run/'lineage.json').read_text())
trace=TraceStore(run);trace.nodes=lineage['nodes'];trace.issues=lineage['issues']
chunks=make_chunks(run,trace)
assert chunks and all(c['raw_path'] and c['assessment']['human_approval']['revision']==2 for c in chunks)
assert all((run/c['raw_path']).exists() for c in chunks)
print('approved provenance verified')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", program, str(root), str(folder)],
        capture_output=True,
        text=True,
        env=_worker_environment(),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "verified" in result.stdout


def test_empty_semantic_index_is_not_ready(tmp_path):
    store = Store(tmp_path)
    pending = store.create(
        TEXT.encode(),
        {
            "text": TEXT,
            "parser": "utf8",
            "segments": [{"text": TEXT, "locator": {"kind": "document_text"}}],
            # Review chunks use text; semantic chunks use the preserved pages.
            "parser_evidence": {"text": TEXT, "pages": [{"page": 1, "text": ""}]},
        },
        {"collection": "test", "title": "Tài liệu thử"},
        source_kind="file",
        filename="source.txt",
        mime="text/plain",
    )
    doc = approve(store, pending)
    pipeline = Pipeline(store, CredentialStore(tmp_path))
    job = {
        "id": uuid4().hex,
        "action": "build",
        "status": "running",
        "collection": "test",
        "scope": "Phạm vi kiểm thử nguồn đã duyệt",
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimensions": 1536,
        "max_chunks": 400,
        "approved_versions": fingerprint([doc]),
    }
    pipeline.save(job)
    folder = pipeline.folder / job["id"]
    (folder / "originals").mkdir()
    (folder / "originals" / doc["id"]).write_bytes(TEXT.encode())
    (folder / "approved.json").write_text(json.dumps({"documents": [doc]}))

    # The real worker builds an empty index without requesting embeddings or keys.
    pipeline.run(job, {})

    completed = pipeline.get(job["id"])
    assert completed["manifest"]["status"] == "no_evidence"
    assert completed["manifest"]["chunk_count"] == 0
    assert completed["status"] == "failed"
    assert "chưa có evidence" in completed["error"]
    with pytest.raises(Conflict, match="Index chưa sẵn sàng"):
        pipeline.evidence(job["id"], "Nội dung tài liệu là gì?")


@pytest.mark.parametrize(
    "manifest_status,chunk_count,expected",
    [
        ("ready_partial", 1, "ready"),
        ("ready_partial", 0, "failed"),
        ("no_evidence", 1, "failed"),
    ],
)
def test_build_job_readiness_matches_worker_manifest(
    tmp_path, monkeypatch, manifest_status, chunk_count, expected
):
    store = Store(tmp_path)
    doc = approve(store, document(store))
    pipeline = Pipeline(store, CredentialStore(tmp_path))
    job = {
        "id": uuid4().hex,
        "action": "build",
        "status": "running",
        "collection": "test",
        "approved_versions": fingerprint([doc]),
    }
    manifest = {"status": manifest_status, "chunk_count": chunk_count}
    monkeypatch.setattr(pipeline, "worker", lambda request, key: manifest)

    pipeline.run(job, {})

    completed = pipeline.get(job["id"])
    assert completed["manifest"] == manifest
    assert completed["status"] == expected
    if expected == "failed":
        assert "chưa có evidence" in completed["error"]
    else:
        assert "error" not in completed


def test_restart_marks_jobs_interrupted(tmp_path):
    store = Store(tmp_path)
    pipeline = Pipeline(store, CredentialStore(tmp_path))
    previous_owner = subprocess.Popen([sys.executable, "-c", "pass"])
    previous_owner.wait(timeout=10)
    job = {
        "id": uuid4().hex,
        "status": "running",
        "created_at": "test",
        "owner_pid": previous_owner.pid,
    }
    pipeline.save(job)
    restarted = Pipeline(store, CredentialStore(tmp_path))
    assert restarted.get(job["id"])["status"] == "interrupted"


def test_snapshot_failure_is_persisted_without_exposing_key(tmp_path):
    store = Store(tmp_path)
    doc = approve(store, document(store))
    credentials = CredentialStore(tmp_path)
    secret = "test-only-" + uuid4().hex
    credentials.put("btc", secret)
    (store.raw / doc["id"]).write_bytes(b"changed source")
    pipeline = Pipeline(store, credentials)
    with pytest.raises(ValueError, match="Bản gốc thay đổi"):
        pipeline.start(
            {"action": "build", "scope": "Phạm vi kiểm thử nguồn đã duyệt", "collection": "test"}
        )
    assert not pipeline.busy
    assert pipeline.list()[0]["status"] == "failed"
    assert secret not in json.dumps(pipeline.list())


def test_api_requires_session_and_approved_sources(tmp_path):
    from app import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        payload = {
            "action": "build",
            "scope": "Phạm vi kiểm thử nguồn đã duyệt",
            "collection": "test",
        }
        assert client.post("/api/pipeline", json=payload).status_code == 403
        client.headers["x-csrf-token"] = client.get("/api/config").json()["csrf_token"]
        CredentialStore(tmp_path).put("btc", "test-only-" + uuid4().hex)
        assert client.post("/api/pipeline", json=payload).status_code == 422
        assert client.get("/api/pipeline").json() == {"jobs": []}


def test_scope_only_crawl_requires_selected_key_without_provider_fallback(tmp_path):
    pipeline = Pipeline(Store(tmp_path), CredentialStore(tmp_path))
    pipeline.credentials.put("openai", "test-only-other-provider")
    payload = {
        "action": "crawl",
        "scope": "Kinh tế Hà Nam giai đoạn 2020–2024",
        "collection": "ha-nam",
    }
    with pytest.raises(ValueError, match="Chưa lưu key cho btc"):
        pipeline.start(payload)
    assert pipeline.list() == []
    with pytest.raises(ValueError, match="không nhận seed_urls"):
        pipeline.start({**payload, "seed_urls": ["https://example.com/article"]})
    with pytest.raises(ValueError, match="Chọn BTC hoặc OpenAI"):
        pipeline.start({**payload, "provider": "google"})


def test_connector_series_enters_pending_review(tmp_path):
    store = Store(tmp_path)
    pipeline = Pipeline(store, CredentialStore(tmp_path))
    identifier = uuid4().hex
    job = {
        "id": identifier,
        "action": "crawl",
        "status": "running",
        "collection": "test",
        "created_at": "test",
        "document_ids": [],
        "errors": [],
    }
    pipeline.save(job)
    run = pipeline.folder / identifier / "crawl" / "run"
    (run / "parsed").mkdir(parents=True)
    (run / "raw").mkdir()
    body = b'{"year":2024,"value":10}'
    (run / "raw/data.json").write_bytes(body)
    parsed = {
        "url": "https://example.com/data",
        "status": "verified_against_source",
        "indicator": {"name": "Test series"},
        "rows": [
            {
                "year": 2024,
                "value": 10,
                "raw_path": "raw/data.json",
                "raw_sha256": hashlib.sha256(body).hexdigest(),
            }
        ],
    }
    (run / "parsed/series-1.json").write_text(json.dumps(parsed))
    (run / "report.json").write_text(
        json.dumps({"documents": [{"status": "verified_against_source"}]})
    )
    pipeline.import_run(job, run)
    assert not job["errors"]
    doc = store.get(job["document_ids"][0])
    assert doc["status"] == "pending"
    assert doc["crawl"]["upstream_status"] == "verified_against_source"
    assert not store.export("test")["documents"]


@pytest.mark.parametrize(
    "action,gate", [("crawl", "BTC_STRUCTURED_VERIFIED"), ("build", "BTC_EMBEDDING_VERIFIED")]
)
def test_real_native_job_persists_capability_failure_before_network(
    tmp_path, monkeypatch, action, gate
):
    import time
    from pipeline_trace import trace_view

    for flag in (
        "BTC_STRUCTURED_VERIFIED",
        "BTC_SEARCH_VERIFIED",
        "BTC_EMBEDDING_VERIFIED",
        "BTC_EMBEDDING_BATCH_VERIFIED",
    ):
        monkeypatch.setenv(flag, "0")
    pipeline = Pipeline(Store(tmp_path), CredentialStore(tmp_path))
    pipeline.credentials.put("btc", "isolated-test-key-never-sent")
    if action == "build":
        approve(pipeline.store, document(pipeline.store))
    job = pipeline.start(
        {
            "action": action,
            "scope": "Phạm vi kiểm thử nguồn đã duyệt",
            "collection": "test",
            "max_pages": 1,
            "max_depth": 0,
        }
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        completed = pipeline.get(job["id"])
        if completed["status"] != "running":
            break
        time.sleep(0.02)
    assert completed["status"] == "failed", completed
    assert gate in completed["error"]
    assert completed["provider"] == "btc"
    assert completed["document_ids"] == []
    assert "isolated-test-key-never-sent" not in json.dumps(completed)
    trace = trace_view(pipeline, job["id"])
    assert any(gate in issue["message"] for issue in trace["issues"])
    assert not list((pipeline.folder / job["id"]).rglob("index.sqlite"))


def test_out_of_scope_documents_remain_pending_and_reimport_is_idempotent(tmp_path):
    store = Store(tmp_path)
    pipeline = Pipeline(store, CredentialStore(tmp_path))
    job = {
        "id": uuid4().hex,
        "action": "crawl",
        "status": "running",
        "collection": "test",
        "created_at": "test",
        "document_ids": [],
        "errors": [],
    }
    pipeline.save(job)
    run = pipeline.folder / job["id"] / "crawl" / "run"
    (run / "parsed").mkdir(parents=True)
    (run / "raw").mkdir()
    body = TEXT.encode()
    (run / "raw/source.txt").write_bytes(body)
    parsed = {
        "text": TEXT,
        "raw_path": "raw/source.txt",
        "raw_sha256": hashlib.sha256(body).hexdigest(),
        "url": "https://example.com/source",
        "status": "out_of_scope",
    }
    (run / "parsed/document.json").write_text(json.dumps(parsed))
    (run / "report.json").write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "status": "out_of_scope",
                        "parsed_path": "parsed/document.json",
                        "reason": "Chỉ có số liệu một năm",
                    }
                ]
            }
        )
    )
    pipeline.import_run(job, run)
    pipeline.import_run(job, run)
    assert len(job["document_ids"]) == 1
    assert not job["errors"]
    doc = store.get(job["document_ids"][0])
    assert doc["status"] == "pending"
    assert doc["text"] == TEXT
    assert doc["crawl"]["scope_reason"] == "Chỉ có số liệu một năm"
    assert doc["crawl"]["upstream_status"] == "out_of_scope"
    assert not store.export("test")["documents"]
