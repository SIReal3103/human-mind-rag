"""Unified engine contracts: approval, parser fidelity, shared cache and lifecycle."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from bot import plan_scope
from data_pipeline import build
from audit_run import audit
from trace import explain
from ingestion import parser_evidence, upstream_info
from pipeline import Pipeline, fingerprint
from pipeline_worker import prepare_snapshot
from credentials import CredentialStore
from store import Store, Conflict

TEXT = "Rainfall is measured in millimetres. The table below retains its original headers, units, source coordinates and missing values for a reviewer to compare with the source."


def source_document():
    provenance = [{"page_no": 1, "bbox": {"l": 0, "t": 20, "r": 100, "b": 0}}]
    originals = [
        {
            "text": text,
            "start_row_offset_idx": row,
            "end_row_offset_idx": row + 1,
            "start_col_offset_idx": column,
            "end_col_offset_idx": column + 1,
            "column_header": row == 0,
            "row_header": False,
            "bbox": None,
        }
        for row, values in enumerate([["Year", "Rain mm"], ["2020", "1000"]])
        for column, text in enumerate(values)
    ]
    cells = [
        {
            "text": c["text"],
            "row": c["start_row_offset_idx"],
            "column": c["start_col_offset_idx"],
            "rowspan": 1,
            "colspan": 1,
            "header": c["column_header"],
            "row_header": False,
            "bbox": None,
        }
        for c in originals
    ]
    return {
        "text": TEXT,
        "parser": "docling-local-v1",
        "parser_library_version": "fixture",
        "parser_config": {"ocr": "auto"},
        "parse_partial": False,
        "parse_warnings": [],
        "pages": [
            {
                "page": 1,
                "text": TEXT,
                "items": [
                    {
                        "ref": "#/texts/0",
                        "label": "text",
                        "char_start": 0,
                        "char_end": len(TEXT),
                        "provenance": provenance,
                    }
                ],
            }
        ],
        "tables": [
            {
                "locator": "#/tables/0",
                "cells": cells,
                "grid_cell_indices": [[0, 1], [2, 3]],
                "row_count": 2,
                "column_count": 2,
                "provenance": provenance,
                "warnings": [],
            }
        ],
        "docling_document": {
            "texts": [{"text": TEXT, "prov": provenance}],
            "tables": [{"prov": provenance, "data": {"table_cells": originals}}],
        },
    }


def create_document(store, **metadata):
    parsed = source_document()
    return store.create(
        TEXT.encode(),
        {
            "text": TEXT,
            "parser": parsed["parser"],
            "parser_evidence": parser_evidence(parsed),
            "segments": [{"text": TEXT, "locator": {"kind": "page", "page": 1}}],
        },
        {"collection": "test", "title": "Rainfall", **metadata},
        source_kind="file",
        filename="fixture.txt",
        mime="text/plain",
    )


def approve(store, doc):
    return store.decide(
        doc["id"],
        {
            "action": "approve",
            "revision": doc["revision"],
            "actor": "Fixture reviewer",
            "acknowledge_findings": True,
        },
    )


def snapshot(folder, store, doc):
    (folder / "originals").mkdir(parents=True)
    (folder / "originals" / doc["id"]).write_bytes((store.raw / doc["id"]).read_bytes())
    (folder / "approved.json").write_text(json.dumps({"documents": [doc]}))
    return prepare_snapshot(folder, "Rainfall with table headers")


def test_bundled_engine_does_not_require_other_checkout():
    assert upstream_info()["integration"] == "bundled"
    assert Path(upstream_info()["path"]) == Path(__file__).resolve().parents[2]
    assert plan_scope("đạo hàm")["subject"] == "đạo hàm"
    assert plan_scope("AI")["subject"] == "AI"
    with pytest.raises(ValueError):
        plan_scope("đề F")


def test_approved_docling_structure_survives_snapshot_index_and_backward_audit(tmp_path):
    store = Store(tmp_path / "store")
    pending = create_document(store)
    with pytest.raises(ValueError, match="Unapproved"):
        snapshot(tmp_path / "blocked", store, pending)
    doc = approve(store, pending)
    shared_cache = store.folder / "embedding-cache.sqlite"
    for number in (1, 2):
        run = snapshot(tmp_path / str(number), store, doc)
        parsed = json.loads((run / "parsed" / (doc["id"] + ".json")).read_text())
        assert parsed["tables"] == source_document()["tables"]
        assert parsed["docling_document"] == source_document()["docling_document"]

        def embed(texts, model, dims, number=number):
            assert number == 1, "second build must reuse vectors across snapshot directories"
            return [[1, 0] for _ in texts], {"fixture": True, "inputs": len(texts)}

        manifest = build(run, dimensions=2, request_fn=embed, cache_path=shared_cache)
        assert audit(run)["status"] == "pass"
        assert all(
            n["artifact_integrity"] is not False
            for n in explain(run, manifest["trace_id"])["backward_trace"]
        )
        chunks = json.loads((run / "data/chunks.json").read_text())
        assert any(c["locator"].get("representation") == "row_with_headers" for c in chunks)
        if number == 2:
            receipt = json.loads((run / "data/embedding-receipts.json").read_text())
            assert receipt["cache_hits"] == len(chunks)


def test_text_edits_clear_old_docling_coordinates_and_still_pass_audit(tmp_path):
    store = Store(tmp_path / "store")
    doc = create_document(store)
    edited = store.update(
        doc["id"], {"revision": doc["revision"], "text": TEXT + " Corrected by reviewer."}
    )
    assert edited["parser_evidence"] == {}
    assert edited["segments"] == []
    assert edited["parser"] == "human-edited-text-v1"
    doc = approve(store, edited)
    run = snapshot(tmp_path / "snapshot", store, doc)
    build(run, dimensions=2, request_fn=lambda texts, *args: ([[1, 0] for _ in texts], {}))
    assert audit(run)["status"] == "pass"
    chunks = json.loads((run / "data/chunks.json").read_text())
    assert all("page" not in c["locator"] for c in chunks)


def test_index_survives_midnight_only_when_eligible_versions_are_unchanged(tmp_path):
    store = Store(tmp_path)
    doc = approve(
        store, create_document(store, effective_from="2026-10-01", effective_to="2026-10-09")
    )
    pipeline = Pipeline(store, CredentialStore(tmp_path))
    job = {"collection": "test", "as_of": "2026-10-07", "approved_versions": fingerprint([doc])}
    with patch("pipeline.today", return_value="2026-10-08"):
        pipeline.assert_current(job)
    with patch("pipeline.today", return_value="2026-10-09"), pytest.raises(Conflict):
        pipeline.assert_current(job)


def test_queue_summaries_omit_large_parser_payloads_and_keep_review_fields(tmp_path):
    store = Store(tmp_path)
    doc = create_document(store)
    summary = store.summaries("pending")[0]
    assert summary["id"] == doc["id"]
    assert summary["quality"] == doc["quality"]
    assert not {"text", "chunks", "segments", "audit", "parser_evidence"} & summary.keys()
    assert store.summaries("approved") == []
    assert store.get(doc["id"])["parser_evidence"] == parser_evidence(source_document())


def test_snapshot_keeps_review_coverage_warnings(tmp_path):
    store = Store(tmp_path / "store")
    doc = approve(store, create_document(store))
    # Review coverage can add findings beyond the parser's original result.
    doc["parser_warnings"] = ["Review-layer coverage warning"]
    run = snapshot(tmp_path / "snapshot", store, doc)
    parsed = json.loads((run / "parsed" / (doc["id"] + ".json")).read_text())
    assert parsed["parse_warnings"] == doc["parser_warnings"]


def test_multisource_series_cannot_be_attributed_to_first_raw_snapshot(tmp_path):
    import hashlib
    from uuid import uuid4

    store = Store(tmp_path)
    pipeline = Pipeline(store, CredentialStore(tmp_path))
    job = {"id": uuid4().hex, "collection": "test", "document_ids": [], "errors": []}
    pipeline.save(job)
    run = pipeline.folder / job["id"] / "crawl" / "run"
    (run / "parsed").mkdir(parents=True)
    (run / "raw").mkdir()
    rows = []
    for number in (1, 2):
        body = str(number).encode()
        path = f"raw/{number}.json"
        (run / path).write_bytes(body)
        rows.append({"raw_path": path, "raw_sha256": hashlib.sha256(body).hexdigest()})
    (run / "parsed/series-1.json").write_text(json.dumps({"rows": rows}))
    (run / "report.json").write_text(json.dumps({"documents": []}))
    pipeline.import_run(job, run)
    assert not job["document_ids"]
    assert job["errors"]
    assert not store.list()
