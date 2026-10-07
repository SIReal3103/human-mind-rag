"""API lifecycle checks with real local parsing, SQLite and isolated source fixtures."""

import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SOURCE_TEXT = (
    "This authored test fixture explains how a reader checks a source before approval. "
    "The reviewer compares the original wording with the extracted text and confirms the "
    "intended collection and effective period. Its example content is for isolated tests only."
)


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rag-review-workflow-")
        self.addCleanup(temporary.cleanup)
        self.data_dir = Path(temporary.name)
        environment = patch.dict(
            os.environ,
            {"DOCUMENT_PARSER": "native", "RAG_REVIEW_DATA": str(self.data_dir)},
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.create_app = importlib.import_module("app").create_app
        self.app = self.create_app(self.data_dir)
        self.client = self.new_client(self.app)

    def new_client(self, application):
        client = TestClient(application, base_url="http://127.0.0.1")
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        config = client.get("/api/config")
        self.assertEqual(config.status_code, 200, config.text)
        client.headers["x-csrf-token"] = config.json()["csrf_token"]
        return client

    def create_document(self, marker="needle", **values):
        payload = {"title": f"Fixture {marker}", "text": f"{marker}. {SOURCE_TEXT}", **values}
        response = self.client.post("/api/documents/text", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def decide(self, document, action="approve", expected=200, **values):
        payload = {
            "revision": document["revision"],
            "action": action,
            "actor": "Test reviewer",
            **values,
        }
        response = self.client.post(f"/api/documents/{document['id']}/decision", json=payload)
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def search(self, query="needle", **values):
        response = self.client.post("/api/search", json={"query": query, **values})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def exported(self, **values):
        response = self.client.get("/api/export", params=values)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["documents"]

    def test_pending_and_rejected_never_reach_retrieval_or_export(self):
        pending = self.create_document("needle pending")
        rejected = self.create_document("needle rejected")
        self.assertEqual(self.search()["status"], "no_evidence")
        self.assertEqual(self.exported(), [])
        rejected = self.decide(rejected, "reject", note="Fixture rejection for this test.")
        approved = self.decide(self.create_document("needle approved"))
        result = self.search()
        self.assertEqual({row["document_id"] for row in result["results"]}, {approved["id"]})
        self.assertEqual({doc["id"] for doc in self.exported()}, {approved["id"]})
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(rejected["status"], "rejected")

    def test_edit_invalidates_old_review_and_preserves_raw_source(self):
        original = self.create_document()
        new_text = "replacement marker. " + SOURCE_TEXT
        response = self.client.patch(
            f"/api/documents/{original['id']}",
            json={"revision": original["revision"], "text": new_text},
        )
        self.assertEqual(response.status_code, 200, response.text)
        edited = response.json()
        self.assertGreater(edited["revision"], original["revision"])
        self.assertEqual(edited["source_sha256"], original["source_sha256"])
        self.assertTrue(edited["edited"])
        self.assertTrue(all(c["locator"]["kind"] == "reviewed_text" for c in edited["chunks"]))
        self.decide(original, expected=409)
        stale_edit = self.client.patch(
            f"/api/documents/{original['id']}",
            json={"revision": original["revision"], "title": "Stale title"},
        )
        self.assertEqual(stale_edit.status_code, 409)
        self.decide(edited)
        result = self.search("replacement")
        self.assertEqual(result["results"][0]["text"], new_text)
        raw = self.client.get(f"/api/documents/{original['id']}/original")
        self.assertEqual(raw.content, original["text"].encode())
        self.assertEqual(hashlib.sha256(raw.content).hexdigest(), original["source_sha256"])

    def test_warnings_require_explicit_boolean_acknowledgement(self):
        document = self.create_document(text="A short source needs review.")
        self.assertTrue(any(f["severity"] == "warning" for f in document["quality"]["findings"]))
        self.decide(document, expected=422)
        self.decide(document, expected=422, acknowledge_findings="true")
        self.assertEqual(self.exported(), [])
        approved = self.decide(document, acknowledge_findings=True)
        self.assertTrue(approved["audit"][-1]["acknowledge_findings"])

    def test_blocking_metadata_error_cannot_be_overridden_by_acknowledgement(self):
        document = self.create_document(time_sensitive=True)
        self.assertTrue(any(f["severity"] == "error" for f in document["quality"]["findings"]))
        self.decide(document, expected=422, acknowledge_findings=True)
        self.assertEqual(self.exported(), [])
        response = self.client.patch(
            f"/api/documents/{document['id']}",
            json={"revision": document["revision"], "effective_from": "2026-01-01"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.decide(response.json())

    def test_collection_and_half_open_effective_period_apply_before_limit(self):
        expected = self.decide(
            self.create_document(
                "needle alpha",
                collection="alpha",
                time_sensitive=True,
                effective_from="2026-01-01",
                effective_to="2026-02-01",
            )
        )
        self.decide(self.create_document("needle needle needle beta", collection="beta"))
        for day, visible in [("2025-12-31", False), ("2026-01-01", True), ("2026-02-01", False)]:
            with self.subTest(day=day):
                results = self.search(collection="alpha", as_of=day, limit=1)["results"]
                exported = self.exported(collection="alpha", as_of=day)
                expected_ids = {expected["id"]} if visible else set()
                self.assertEqual({item["document_id"] for item in results}, expected_ids)
                self.assertEqual({doc["id"] for doc in exported}, expected_ids)
        self.assertEqual(self.search(collection="unknown")["status"], "no_evidence")

    def test_approved_content_is_immutable_and_duplicate_decision_does_not_add_evidence(self):
        pending = self.create_document()
        approved = self.decide(pending)
        response = self.client.patch(
            f"/api/documents/{approved['id']}",
            json={"revision": approved["revision"], "text": "Modified after approval"},
        )
        self.assertEqual(response.status_code, 409)
        self.decide(pending, expected=409)
        self.decide(approved, expected=409)
        stored = self.client.get(f"/api/documents/{approved['id']}").json()
        self.assertEqual(stored["text"], pending["text"])
        self.assertEqual([event["action"] for event in stored["audit"]], ["import", "approve"])
        self.assertEqual(len(self.search()["results"]), len(approved["chunks"]))

    def test_compact_and_week_dates_cannot_expose_a_future_document(self):
        document = self.decide(self.create_document(effective_from="2026-12-01"))
        self.assertEqual(self.search(as_of="2026-01-01")["status"], "no_evidence")
        self.assertEqual(self.exported(as_of="2026-01-01"), [])
        for date_value in ("20260101", "2026-W01-1"):
            with self.subTest(as_of=date_value):
                response = self.client.post(
                    "/api/search", json={"query": "needle", "as_of": date_value}
                )
                self.assertEqual(response.status_code, 422, response.text)
                response = self.client.get("/api/export", params={"as_of": date_value})
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(
            self.search(as_of="2026-12-01")["results"][0]["document_id"], document["id"]
        )

    def test_withdrawal_removes_evidence_and_retains_audit_and_original(self):
        approved = self.decide(self.create_document())
        self.decide(approved, "withdraw", expected=422)
        withdrawn = self.decide(approved, "withdraw", note="Fixture source retired.")
        self.assertEqual(withdrawn["status"], "withdrawn")
        self.assertEqual(self.search()["status"], "no_evidence")
        self.assertEqual(self.exported(), [])
        self.assertEqual(withdrawn["audit"][-1]["action"], "withdraw")
        self.assertEqual(
            self.client.get(f"/api/documents/{approved['id']}/original").content,
            approved["text"].encode(),
        )
        self.decide(withdrawn, expected=409)

    def test_restart_preserves_reviewed_data_and_rotates_session_token(self):
        approved = self.decide(self.create_document())
        old_token = self.client.headers["x-csrf-token"]
        restarted = self.new_client(self.create_app(self.data_dir))
        self.assertNotEqual(restarted.headers["x-csrf-token"], old_token)
        stored = restarted.get(f"/api/documents/{approved['id']}")
        self.assertEqual(stored.json(), approved)
        result = restarted.post("/api/search", json={"query": "needle"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["results"][0]["document_id"], approved["id"])
        self.assertEqual(len(restarted.get("/api/export").json()["documents"]), 1)
        stale = restarted.post(
            "/api/search", json={"query": "needle"}, headers={"x-csrf-token": old_token}
        )
        self.assertEqual(stale.status_code, 403)

    def test_fts_and_sql_syntax_in_user_input_cannot_change_storage_or_scope(self):
        document = self.decide(self.create_document("needle copper"))
        self.assertEqual(
            self.search("needle NOT copper")["results"][0]["document_id"], document["id"]
        )
        for query in ['zzzz"); DROP TABLE documents; --', '"*():', "NEAR(zzzz, phantom)"]:
            with self.subTest(query=query):
                self.assertEqual(self.search(query)["status"], "no_evidence")
        self.assertEqual(self.search(collection="general' OR 1=1 --")["results"], [])
        self.assertEqual(self.exported(collection="general' OR 1=1 --"), [])
        self.assertEqual(self.search()["results"][0]["document_id"], document["id"])
        self.assertEqual(len(self.client.get("/api/documents").json()["documents"]), 1)

    def test_source_revisions_cannot_overlap_but_adjacent_periods_can_publish(self):
        first = self.decide(
            self.create_document(
                "needle first",
                source_id="policy-fixture",
                effective_from="2026-01-01",
                effective_to="2026-02-01",
            )
        )
        overlapping = self.create_document(
            "needle overlapping",
            source_id="policy-fixture",
            document_version="2",
            effective_from="2026-01-15",
        )
        self.decide(overlapping, expected=409)
        following = self.decide(
            self.create_document(
                "needle following",
                source_id="policy-fixture",
                document_version="3",
                effective_from="2026-02-01",
            )
        )
        self.assertEqual(self.search(as_of="2026-01-31")["results"][0]["document_id"], first["id"])
        self.assertEqual(
            self.search(as_of="2026-02-01")["results"][0]["document_id"], following["id"]
        )

    def test_rejected_document_requires_explicit_reopen_and_new_review(self):
        document = self.create_document()
        self.decide(document, "reject", expected=422)
        rejected = self.decide(document, "reject", note="Check source before reconsidering.")
        self.decide(rejected, expected=409)
        reopened = self.decide(rejected, "reopen")
        self.assertEqual(reopened["status"], "pending")
        self.assertEqual(self.search()["status"], "no_evidence")
        self.decide(rejected, expected=409)
        self.decide(reopened)

    def test_real_pdf_upload_keeps_page_evidence_and_original_bytes(self):
        output = io.BytesIO()
        pdf = canvas.Canvas(output)
        for number, marker in [(1, "cobalt"), (2, "amber")]:
            pdf.drawString(40, 740, f"Page {number}: {marker} source fixture for review.")
            pdf.drawString(40, 710, "A human compares the original and extracted wording.")
            pdf.showPage()
        pdf.save()
        body = output.getvalue()
        response = self.client.post(
            "/api/documents/upload",
            files={"file": ("../../source.pdf", body, "application/pdf")},
            data={"metadata": json.dumps({"title": "Authored PDF fixture"})},
        )
        self.assertEqual(response.status_code, 201, response.text)
        document = response.json()
        self.assertEqual(document["filename"], "source.pdf")
        self.assertEqual(document["source_sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual({c["locator"]["page"] for c in document["chunks"]}, {1, 2})
        self.assertEqual(self.search("amber")["status"], "no_evidence")
        self.decide(document, acknowledge_findings=True)
        result = self.search("amber")["results"]
        self.assertTrue(result)
        self.assertTrue(all(row["locator"]["page"] == 2 for row in result))
        original = self.client.get(f"/api/documents/{document['id']}/original?inline=true")
        self.assertEqual(original.content, body)
        self.assertEqual(original.headers["content-type"], "application/pdf")

    def test_mismatched_upload_mime_and_invalid_metadata_leave_no_document(self):
        for filename, body, metadata in [
            ("wrong.pdf", b"This is plain text", "{}"),
            ("wrong.txt", b"%PDF-1.7 invalid", "{}"),
            ("source.txt", b"Text fixture", "[1, 2]"),
            ("source.txt", b"Text fixture", "{"),
        ]:
            with self.subTest(filename=filename, metadata=metadata):
                response = self.client.post(
                    "/api/documents/upload",
                    files={"file": (filename, body, "application/octet-stream")},
                    data={"metadata": metadata},
                )
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get("/api/documents").json()["documents"], [])

    def test_pdf_without_extractable_text_stays_blocked_until_reviewed_text_is_added(self):
        from pypdf import PdfWriter

        output = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.write(output)
        body = output.getvalue()
        response = self.client.post(
            "/api/documents/upload",
            files={"file": ("blank-source.pdf", body, "application/pdf")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        document = response.json()
        self.assertEqual(document["status"], "pending")
        self.assertEqual(document["text"], "")
        self.assertEqual(document["chunks"], [])
        self.assertEqual(document["parser"], "pdf-extraction-failed")
        self.assertTrue(any(f["code"] == "empty" for f in document["quality"]["findings"]))
        self.decide(document, expected=422, acknowledge_findings=True)
        self.assertEqual(self.exported(), [])
        self.assertEqual(self.client.get(f"/api/documents/{document['id']}/original").content, body)
        edited = self.client.patch(
            f"/api/documents/{document['id']}",
            json={"revision": document["revision"], "text": "needle. " + SOURCE_TEXT},
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.decide(edited.json(), acknowledge_findings=True)
        result = self.search()["results"][0]
        self.assertEqual(result["locator"]["kind"], "reviewed_text")
        self.assertNotIn("page", result["locator"])

    def test_mixed_pdf_requires_reviewed_replacement_for_missing_image_only_page(self):
        from PIL import Image, ImageDraw
        from reportlab.lib.utils import ImageReader

        output = io.BytesIO()
        pdf = canvas.Canvas(output)
        for line in range(8):
            pdf.drawString(40, 750 - 20 * line, "needle text source needs human review.")
        pdf.showPage()
        scan = Image.new("RGB", (400, 200), "white")
        ImageDraw.Draw(scan).text((20, 80), "Image-only source fixture: amount 12345", fill="black")
        pdf.drawImage(ImageReader(scan), 40, 450, width=400, height=200)
        pdf.showPage()
        pdf.save()
        body = output.getvalue()

        response = self.client.post(
            "/api/documents/upload",
            files={"file": ("mixed-source.pdf", body, "application/pdf")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        document = response.json()
        self.assertEqual(document["status"], "pending")
        self.assertTrue(document["partial"])
        self.assertIn("needle", document["text"])
        self.assertEqual({c["locator"]["page"] for c in document["chunks"]}, {1})
        self.assertTrue(any("Trang PDF 2:" in warning for warning in document["parser_warnings"]))
        self.assertTrue(
            any(
                finding["code"] == "partial" and finding["severity"] == "error"
                for finding in document["quality"]["findings"]
            )
        )

        self.decide(document, expected=422, acknowledge_findings=True)
        stored = self.client.get(f"/api/documents/{document['id']}").json()
        self.assertEqual(stored["status"], "pending")
        self.assertEqual(stored["revision"], document["revision"])
        self.assertEqual(self.search("needle")["status"], "no_evidence")
        self.assertEqual(self.exported(), [])
        original = self.client.get(f"/api/documents/{document['id']}/original")
        self.assertEqual(original.content, body)
        self.assertEqual(hashlib.sha256(original.content).hexdigest(), document["source_sha256"])

        unchanged = self.client.patch(
            f"/api/documents/{document['id']}",
            json={
                "revision": document["revision"],
                "title": "Mixed PDF awaiting full review",
                "text": document["text"],
            },
        )
        self.assertEqual(unchanged.status_code, 200, unchanged.text)
        document = unchanged.json()
        self.assertTrue(document["partial"])
        self.decide(document, expected=422, acknowledge_findings=True)

        replacement = document["text"] + "\nImage-only source fixture: amount 12345"
        response = self.client.patch(
            f"/api/documents/{document['id']}",
            json={"revision": document["revision"], "text": replacement},
        )
        self.assertEqual(response.status_code, 200, response.text)
        edited = response.json()
        self.assertEqual(edited["status"], "pending")
        self.assertFalse(edited["partial"])
        self.assertEqual(edited["parser"], "human-edited-text-v1")
        self.assertEqual(edited["segments"], [])
        self.assertEqual(edited["parser_evidence"], {})
        self.assertTrue(all(c["locator"]["kind"] == "reviewed_text" for c in edited["chunks"]))
        self.assertEqual(edited["parser_warnings"][:-1], document["parser_warnings"])
        self.assertIn("toàn bộ bản gốc", edited["parser_warnings"][-1])
        self.assertEqual(edited["audit"][-1]["previous_parser"], document["parser"])
        self.assertIs(edited["audit"][-1]["previous_partial"], True)
        self.assertFalse(any(f["severity"] == "error" for f in edited["quality"]["findings"]))
        self.assertEqual(self.search("12345")["status"], "no_evidence")
        self.assertEqual(self.exported(), [])

        self.decide(edited, expected=422)
        from auto_review import ACTOR

        self.decide(
            edited,
            expected=422,
            actor=ACTOR,
            approval_mode="automatic",
            acknowledge_findings=True,
        )
        approved = self.decide(edited, acknowledge_findings=True)
        self.assertEqual(approved["audit"][-1]["approval_mode"], "manual")
        self.assertTrue(approved["audit"][-1]["acknowledge_findings"])
        self.assertEqual(self.search("12345")["results"][0]["text"], replacement)
        self.assertEqual(self.exported()[0]["id"], document["id"])
        self.assertEqual(self.client.get(f"/api/documents/{document['id']}/original").content, body)
        self.assertEqual(approved["source_sha256"], document["source_sha256"])

    def test_web_import_rejects_private_and_credentialed_urls_before_fetch(self):
        for url in [
            "http://127.0.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
            "http://user:password@example.com/",
        ]:
            with self.subTest(url=url):
                response = self.client.post("/api/documents/web", json={"url": url})
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get("/api/documents").json()["documents"], [])

    def test_local_host_origin_and_session_token_protect_mutations(self):
        payload = {"text": SOURCE_TEXT}
        for headers in [
            {"x-csrf-token": ""},
            {"x-csrf-token": "stale-token"},
            {"origin": "https://outside.invalid"},
            {"host": "outside.invalid"},
        ]:
            with self.subTest(headers=headers):
                response = self.client.post("/api/documents/text", json=payload, headers=headers)
                self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.client.get("/api/documents").json()["documents"], [])


if __name__ == "__main__":
    unittest.main()
