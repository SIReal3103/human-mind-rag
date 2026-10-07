"""Real store approval boundaries and audit trail for opt-in automatic review."""

from copy import deepcopy
from uuid import uuid4

import pytest

from auto_review import ACTOR, blockers
from credentials import CredentialStore
from pipeline import Pipeline
from store import Store

TEXT = "Tài liệu nguồn mô tả hệ sinh thái rừng, hoạt động bảo tồn và giáo dục môi trường. Nội dung công khai này đủ dài để kiểm thử việc chia đoạn và quyết định duyệt theo chính sách đã khai báo."


def candidate(store, **changes):
    assessment = {
        "status": "review",
        "subject_match": True,
        "country_gate_required": False,
        "verification": "model_assessed_quotes_checked_not_fact_verified",
        "evidence_quotes": [TEXT],
        "parse_partial": False,
        "input_truncated": False,
    }
    assessment.update(changes)
    return store.create(
        TEXT.encode(),
        {
            "text": TEXT,
            "parser": "utf8",
            "segments": [{"text": TEXT, "locator": {"kind": "document_text"}}],
        },
        {"collection": "auto-test", "title": "Tài liệu quy tắc"},
        source_kind="web",
        filename="source.txt",
        mime="text/plain",
        source_url="https://example.com/source",
        crawl={"assessment": assessment},
    )


def test_automatic_approval_records_policy_and_keeps_approval_gate(tmp_path):
    store = Store(tmp_path)
    doc = candidate(store)
    assert not store.export("auto-test")["documents"]
    assert not blockers(doc)
    updated = store.decide(
        doc["id"],
        {"action": "approve", "revision": 1, "actor": ACTOR, "approval_mode": "automatic"},
    )
    assert updated["audit"][-1]["approval_mode"] == "automatic"
    assert updated["audit"][-1]["actor"] == ACTOR
    assert store.export("auto-test")["documents"]
    evidence = store.search("bảo tồn", "auto-test")["results"]
    assert evidence and all(
        e["factual_confidence"] == "automatically_approved_not_fact_verified" for e in evidence
    )


@pytest.mark.parametrize(
    "change",
    [
        {"status": "out_of_scope"},
        {"subject_match": False},
        {"evidence_quotes": []},
        {"input_truncated": True},
        {"parse_partial": True},
        {"verification": "unverified"},
    ],
)
def test_uncertain_content_cannot_be_auto_approved(tmp_path, change):
    store = Store(tmp_path)
    doc = candidate(store, **change)
    with pytest.raises(ValueError, match="Không đủ điều kiện"):
        store.decide(
            doc["id"],
            {"action": "approve", "revision": 1, "actor": ACTOR, "approval_mode": "automatic"},
        )
    assert store.get(doc["id"])["status"] == "pending"
    assert not store.export("auto-test")["documents"]


def test_auto_review_is_idempotent_and_modified_or_empty_content_stays_pending(tmp_path):
    store = Store(tmp_path)
    doc = candidate(store)
    for edit in (
        {"text": ""},
        {"partial": True},
        {"parser_warnings": ["Cần OCR"]},
        {"revision": 2},
    ):
        changed = deepcopy(doc)
        changed.update(edit)
        assert blockers(changed)
    pipeline = Pipeline(store, CredentialStore(tmp_path))
    job = {
        "id": uuid4().hex,
        "action": "crawl",
        "status": "needs_review",
        "document_ids": [doc["id"]],
        "collection": "auto-test",
        "created_at": "test",
    }
    pipeline.save(job)
    pipeline.auto_review(job["id"])
    pipeline.auto_review(job["id"])
    assert len([e for e in store.get(doc["id"])["audit"] if e["action"] == "approve"]) == 1


def test_second_pipeline_instance_does_not_interrupt_live_owner(tmp_path):
    import os

    store = Store(tmp_path)
    pipeline = Pipeline(store, CredentialStore(tmp_path))
    job = {
        "id": uuid4().hex,
        "action": "crawl",
        "status": "running",
        "owner_pid": os.getpid(),
        "created_at": "test",
    }
    pipeline.save(job)
    another = Pipeline(store, CredentialStore(tmp_path))
    assert another.get(job["id"])["status"] == "running"
    job.pop("owner_pid")
    pipeline.save(job)
    assert Pipeline(store, CredentialStore(tmp_path)).get(job["id"])["status"] == "running"


def test_mixed_snapshot_preserves_automatic_and_human_provenance(tmp_path):
    import json
    from pathlib import Path
    import subprocess
    import sys
    from ingestion import _worker_environment

    store = Store(tmp_path)
    auto = candidate(store)
    auto = store.decide(
        auto["id"],
        {"action": "approve", "revision": 1, "actor": ACTOR, "approval_mode": "automatic"},
    )
    text = TEXT + " Bản thứ hai do người duyệt kiểm tra riêng."
    manual = store.create(
        text.encode(),
        {
            "text": text,
            "parser": "utf8",
            "segments": [{"text": text, "locator": {"kind": "document_text"}}],
        },
        {"collection": "auto-test", "title": "Bản duyệt tay"},
        source_kind="file",
        filename="manual.txt",
        mime="text/plain",
    )
    manual = store.decide(manual["id"], {"action": "approve", "revision": 1, "actor": "Reviewer"})
    pipeline = Pipeline(store, CredentialStore(tmp_path))
    job = {
        "id": uuid4().hex,
        "action": "crawl",
        "status": "needs_review",
        "document_ids": [auto["id"], manual["id"]],
        "collection": "auto-test",
        "created_at": "test",
    }
    pipeline.save(job)
    outcomes = pipeline.auto_review(job["id"])["auto_review"]["outcomes"]
    assert not any(o["newly_approved"] for o in outcomes)
    assert sorted(o["approval_mode"] for o in outcomes) == ["automatic", "manual"]
    folder = tmp_path / "snapshot"
    folder.mkdir()
    (folder / "originals").mkdir()
    for doc in (auto, manual):
        (folder / "originals" / doc["id"]).write_bytes((store.raw / doc["id"]).read_bytes())
    (folder / "approved.json").write_text(json.dumps({"documents": [auto, manual]}))
    program = """import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from ingestion import _require_upstream
sys.path.insert(0,_require_upstream()['path'])
from pipeline_worker import prepare_snapshot
run=prepare_snapshot(Path(sys.argv[2]),'Bảo tồn rừng')
report=json.loads((run/'report.json').read_text())
assert report['counts']=={'human_approved':1,'automatically_approved':1}
parsed=[json.loads(p.read_text()) for p in (run/'parsed').glob('*.json')]
assert sum('automatic_approval' in p['assessment'] for p in parsed)==1
assert sum('human_approval' in p['assessment'] for p in parsed)==1
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            program,
            str(Path(__file__).resolve().parents[1]),
            str(folder),
        ],
        capture_output=True,
        text=True,
        env=_worker_environment(),
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
