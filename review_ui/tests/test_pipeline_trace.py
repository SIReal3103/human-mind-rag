"""Trace projection never returns provider payloads or operator keys."""

import json
from uuid import uuid4

from credentials import CredentialStore
from pipeline import Pipeline
from pipeline_trace import trace_view
from pipeline_trace import discovery_diagnosis
from store import Store


def setup_trace(tmp_path, action="crawl"):
    pipeline = Pipeline(Store(tmp_path), CredentialStore(tmp_path))
    job = {
        "id": uuid4().hex,
        "action": action,
        "status": "running",
        "created_at": "2026-10-07T00:00:00Z",
        "document_ids": [],
    }
    pipeline.save(job)
    folder = pipeline.folder / job["id"] / ("crawl/run" if action == "crawl" else "published")
    folder.mkdir(parents=True)
    return pipeline, job, folder / "lineage.json"


def test_crawl_trace_current_error_and_redaction(tmp_path):
    pipeline, job, path = setup_trace(tmp_path)
    secret = "test-only-" + uuid4().hex
    pipeline.credentials.put("btc", secret)
    path.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "id": "n1",
                        "stage": "crawl",
                        "label": "Download " + secret,
                        "status": "running",
                        "at": "2026-10-07T00:00:00Z",
                        "parents": [],
                        "refs": {
                            "url": "https://example.com/?token=hidden&topic=test",
                            "path": secret,
                        },
                    }
                ],
                "issues": [
                    {
                        "id": "e1",
                        "code": "202",
                        "detected_at": "n1",
                        "detected_stage": "crawl",
                        "message": "HTTP Error 202 " + secret,
                    }
                ],
            }
        )
    )
    result = trace_view(pipeline, job["id"])
    assert result["current"]["id"] == "n1"
    assert result["issues"][0]["code"] == "202"
    assert secret not in json.dumps(result)
    assert "hidden" not in result["events"][0]["url"]
    job["status"] = "no_documents"
    pipeline.save(job)
    assert trace_view(pipeline, job["id"])["current"] is None


def test_partial_write_is_explicit_not_failure(tmp_path):
    pipeline, job, path = setup_trace(tmp_path)
    path.write_text('{"nodes":')
    result = trace_view(pipeline, job["id"])
    assert result["incomplete"] is True
    assert result["events"] == []
    assert result["status"] == "running"


def test_provider_error_body_is_not_exposed(tmp_path):
    pipeline, job, path = setup_trace(tmp_path, "build")
    path.write_text(
        json.dumps(
            {
                "nodes": [],
                "issues": [
                    {
                        "id": "e1",
                        "code": "STAGE_ERROR",
                        "detected_at": "n1",
                        "detected_stage": "embedding",
                        "message": "provider response containing private document text",
                    }
                ],
            }
        )
    )
    result = trace_view(pipeline, job["id"])
    assert "private document text" not in json.dumps(result)
    assert result["issues"][0]["stage"] == "Tạo embedding"


def test_trace_api_reads_existing_job_without_mutation(tmp_path):
    from app import create_app
    from fastapi.testclient import TestClient

    pipeline, job, path = setup_trace(tmp_path)
    job["status"] = "no_documents"
    pipeline.save(job)
    path.write_text(json.dumps({"nodes": [], "issues": []}))
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        result = client.get(f"/api/pipeline/{job['id']}/trace")
        assert result.status_code == 200
        assert result.json()["job_id"] == job["id"]
        assert client.get("/api/pipeline/not-an-id/trace").status_code == 422
    assert pipeline.get(job["id"]) == job


def test_discovery_diagnosis_requires_failed_search_and_duckduckgo_http_202():
    job = {"action": "crawl", "status": "no_documents", "seed_urls": [], "document_ids": []}
    events = [
        {"stage": "search", "status": "failed", "issue_id": "e1"},
        {
            "stage": "crawl",
            "status": "failed",
            "issue_id": "e1",
            "url": "https://lite.duckduckgo.com/lite/?q=test",
        },
    ]
    issues = [{"id": "e1", "code": "202"}]
    assert discovery_diagnosis(job, events, issues)["code"] == "discovery_http_202"
    assert (
        discovery_diagnosis({**job, "seed_urls": ["https://example.com"]}, events, issues) is None
    )
    assert discovery_diagnosis({**job, "status": "running"}, events, issues) is None
    assert discovery_diagnosis(job, events, [{"id": "e1", "code": "403"}]) is None
    assert (
        discovery_diagnosis(job, events + [{"stage": "search", "status": "success"}], issues)
        is None
    )
    events[1]["url"] = "https://example.com/article"
    assert discovery_diagnosis(job, events, issues) is None


def test_native_crawl_hides_model_bodies_but_preserves_actionable_capability(tmp_path):
    pipeline, job, path = setup_trace(tmp_path)
    job["integration"] = "upstream-native"
    pipeline.save(job)
    path.write_text(
        json.dumps(
            {
                "nodes": [],
                "issues": [
                    {
                        "id": "e1",
                        "code": "STAGE_ERROR",
                        "detected_stage": "check",
                        "message": "private model body",
                    },
                    {
                        "id": "e2",
                        "code": "STAGE_ERROR",
                        "detected_stage": "scope",
                        "message": "CAPABILITY_UNVERIFIED: BTC_STRUCTURED_VERIFIED; smoke-test BTC before enabling",
                    },
                ],
            }
        )
    )
    result = trace_view(pipeline, job["id"])
    assert "private model body" not in json.dumps(result)
    assert "BTC_STRUCTURED_VERIFIED" in result["issues"][1]["message"]
