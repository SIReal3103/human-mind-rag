import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import save_json
from trace import TraceStore, explain
from data_pipeline import (
    build,
    retrieve,
    spans,
    tokens,
    valid_vector,
    context_bundle,
    embedding_request,
    digest,
    VERSION,
)


class DataTests(unittest.TestCase):
    def setup_run(self, root, status="review", run_name="run", brief="Mưa Thái Lan 2020-2021"):
        folder = root / run_name
        (folder / "parsed").mkdir(parents=True)
        (folder / "raw").mkdir()
        save_json(
            folder / "scope.json",
            {"brief": brief, "ambiguities": ["Thiếu tỉnh"]},
        )
        save_json(folder / "report.json", {"status": "needs_review"})
        trace = TraceStore(folder)
        scope = trace.artifact("scope.json")
        (folder / "raw/source.txt").write_text(
            "Annual rainfall Thailand 2020 1000 mm. 2021 missing."
        )
        raw = trace.artifact("raw/source.txt", parents=[scope["id"]], stage="crawl")
        doc = {
            "title": "Rainfall",
            "text": "Annual rainfall Thailand 2020 1000 mm. 2021 missing.",
            "status": status,
            "assessment": {"missing": ["2021"]},
            "url": "https://example.org/rain",
            "raw_path": "raw/source.txt",
            "trace_id": raw["id"],
        }
        save_json(folder / "parsed/document-001.json", doc)
        trace.artifact("parsed/document-001.json", parents=[raw["id"]])
        return folder

    def fake_embed(self, texts, model, dims):
        return [[1.0] + [0.0] * (dims - 1) for _ in texts], {
            "inputs": len(texts),
            "test_fixture": True,
        }

    def test_unicode_spans_preserve_exact_text_and_budget(self):
        text = "Tiếng Việt đậm 🌧️\nĐiều kiện và mẫu số.\n" * 100
        pieces = [text[a:b] for a, b in spans(text, 50)]
        self.assertEqual("".join(pieces), text)
        self.assertTrue(all(tokens(p) <= 50 for p in pieces))

    def test_invalid_vectors(self):
        for vector in ([0, 0], [float("nan"), 1], [True, 1], [1], [float("inf"), 1], [1e308, 1]):
            with self.assertRaises(ValueError):
                valid_vector(vector, 2)

    def test_cache_context_and_backward_provenance(self):
        with tempfile.TemporaryDirectory() as name:
            folder = self.setup_run(Path(name))
            manifest = build(folder, dimensions=2, request_fn=self.fake_embed)
            self.assertEqual(manifest["status"], "ready_partial")
            scope_context = json.loads((folder / "data/llm-input.json").read_text())
            self.assertEqual(len(scope_context["evidence"]), 1)
            self.assertNotIn("vector", scope_context["evidence"][0])
            self.assertNotIn("cache_key", scope_context["evidence"][0])
            bundle = retrieve(folder, "rainfall 2021", rerank=False, request_fn=self.fake_embed)
            self.assertEqual(bundle["evidence"][0]["quality"], "review")
            self.assertIn("2021", bundle["evidence"][0]["assessment"]["missing"])
            stages = {
                n["stage"]
                for n in explain(folder, bundle["evidence"][0]["trace_id"])["backward_trace"]
            }
            self.assertTrue({"crawl", "chunk", "save"} <= stages)
            with patch(
                "data_pipeline.embedding_request", side_effect=AssertionError("should use cache")
            ):
                build(folder, dimensions=2, request_fn=lambda *args: self.fail("cache miss"))
            self.assertTrue(
                all(
                    n["artifact_integrity"] is not False
                    for n in explain(folder, bundle["trace_id"])["backward_trace"]
                )
            )
            receipt = json.loads((folder / "data/embedding-receipts.json").read_text())
            self.assertEqual(receipt["cache_hits"], 1)

    def test_identical_embedding_inputs_reused_across_scopes_with_separate_provenance(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            first = self.setup_run(root)
            second = self.setup_run(root, run_name="second", brief="Lượng mưa Thái Lan 2020")
            build(first, dimensions=2, request_fn=self.fake_embed)
            build(second, dimensions=2, request_fn=lambda *args: self.fail("duplicate API input"))
            receipt = json.loads((second / "data/embedding-receipts.json").read_text())
            self.assertEqual(receipt["cache_hits"], 1)
            self.assertEqual(receipt["requests"], [])
            context = retrieve(second, "rainfall", rerank=False, request_fn=self.fake_embed)
            self.assertEqual(context["scope"]["brief"], "Lượng mưa Thái Lan 2020")
            self.assertTrue(
                all(
                    n["artifact_integrity"] is not False
                    for n in explain(second, context["trace_id"])["backward_trace"]
                )
            )
            # Model, dimensions, provider and actual text remain separate cache contracts.
            for model, dims, profile in [
                ("other-model", 2, "openai"),
                ("text-embedding-3-small", 3, "openai"),
                ("text-embedding-3-small", 2, "btc"),
            ]:
                with patch("data_pipeline.provider", return_value=profile):
                    calls = []

                    def embed(texts, model, dims, calls=calls):
                        calls.extend(texts)
                        return self.fake_embed(texts, model, dims)

                    build(second, model=model, dimensions=dims, request_fn=embed)
                    self.assertEqual(len(calls), 1)

    def test_legacy_scoped_cache_is_promoted_without_an_api_call(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            folder = self.setup_run(root)
            doc = json.loads((folder / "parsed/document-001.json").read_text())
            scope = json.loads((folder / "scope.json").read_text())
            key = digest(
                json.dumps(
                    [
                        VERSION,
                        "openai",
                        scope["brief"],
                        "text-embedding-3-small",
                        2,
                        doc["title"] + "\n" + doc["text"],
                    ],
                    ensure_ascii=False,
                )
            )
            from contextlib import closing

            with closing(sqlite3.connect(root / "embedding-cache.sqlite")) as db:
                db.execute("CREATE TABLE cache(key TEXT PRIMARY KEY, vector TEXT)")
                db.execute("INSERT INTO cache VALUES (?,?)", (key, "[1, 0]"))
                db.commit()
            build(folder, dimensions=2, request_fn=lambda *args: self.fail("legacy cache miss"))
            second = self.setup_run(root, run_name="other-scope", brief="Rainfall Thailand")
            build(
                second, dimensions=2, request_fn=lambda *args: self.fail("promotion not committed")
            )

    def test_duplicate_chunks_embed_once_but_keep_both_source_records(self):
        with tempfile.TemporaryDirectory() as name:
            folder = self.setup_run(Path(name))
            doc = json.loads((folder / "parsed/document-001.json").read_text())
            doc["url"] = "https://example.org/second-source"
            save_json(folder / "parsed/document-002.json", doc)
            calls = []

            def embed(texts, model, dims):
                calls.extend(texts)
                return self.fake_embed(texts, model, dims)

            manifest = build(folder, dimensions=2, request_fn=embed)
            self.assertEqual(manifest["chunk_count"], 2)
            self.assertEqual(len(calls), 1)
            receipt = json.loads((folder / "data/embedding-receipts.json").read_text())
            self.assertEqual(receipt["deduplicated_chunks"], 1)
            chunks = json.loads((folder / "data/chunks.json").read_text())
            self.assertEqual(len({c["source_url"] for c in chunks}), 2)
            self.assertEqual(len({c["trace_id"] for c in chunks}), 2)

    def test_reserved_path_characters_work_for_retrieval_and_audit(self):
        from audit_run import audit

        with tempfile.TemporaryDirectory() as name:
            folder = self.setup_run(Path(name) / "dữ liệu #1?100%")
            build(folder, dimensions=2, request_fn=self.fake_embed)
            result = retrieve(folder, "rainfall", rerank=False, request_fn=self.fake_embed)
            self.assertTrue(result["evidence"])
            self.assertEqual(audit(folder)["status"], "pass")

    def test_failed_rebuild_revokes_serving_manifest(self):
        with tempfile.TemporaryDirectory() as name:
            folder = self.setup_run(Path(name))
            build(folder, dimensions=2, request_fn=self.fake_embed)
            with self.assertRaises(ValueError):
                build(folder, dimensions=3, request_fn=lambda *args: ([[0, 0, 0]], {}))
            self.assertEqual(
                json.loads((folder / "data/manifest.json").read_text())["status"], "failed"
            )
            with self.assertRaises(ValueError):
                retrieve(folder, "rain", request_fn=self.fake_embed)

    def test_out_of_scope_excluded(self):
        with tempfile.TemporaryDirectory() as name:
            folder = self.setup_run(Path(name), "out_of_scope")
            manifest = build(
                folder, dimensions=2, request_fn=lambda *args: self.fail("must not embed")
            )
            self.assertEqual(manifest["status"], "no_evidence")

    def test_tampered_source_and_parsed_rejected(self):
        for target in ("raw/source.txt", "parsed/document-001.json"):
            with tempfile.TemporaryDirectory() as name:
                folder = self.setup_run(Path(name))
                if target.endswith(".json"):
                    doc = json.loads((folder / target).read_text())
                    doc["text"] += " altered"
                    save_json(folder / target, doc)
                else:
                    (folder / target).write_text("altered")
                with self.assertRaisesRegex(ValueError, "integrity"):
                    build(folder, dimensions=2, request_fn=self.fake_embed)

    def test_context_budget_does_not_slice_evidence(self):
        chunks = [{"id": str(i), "text": "nội dung " * 100} for i in range(12)]
        bundle = context_bundle(chunks, {"scope": {}, "status": "ready_partial"}, 800)
        self.assertLessEqual(tokens(json.dumps(bundle, ensure_ascii=False)), 800)
        self.assertGreater(bundle["omitted_chunks"], 0)
        self.assertTrue(all(c in chunks for c in bundle["evidence"]))

    def test_index_tampering_blocks_retrieval(self):
        with tempfile.TemporaryDirectory() as name:
            folder = self.setup_run(Path(name))
            build(folder, dimensions=2, request_fn=self.fake_embed)
            with (folder / "data/index.sqlite").open("ab") as handle:
                handle.write(b"tampered")
            with self.assertRaisesRegex(ValueError, "integrity"):
                retrieve(folder, "rain", request_fn=self.fake_embed)

    def test_reranker_can_reject_all_without_fabricating_context(self):
        with tempfile.TemporaryDirectory() as name:
            folder = self.setup_run(Path(name))
            build(folder, dimensions=2, request_fn=self.fake_embed)

            def rank(task, schema, output, filename):
                path = output / (filename + ".json")
                save_json(path, {"fixture": True})
                result = (
                    {"within_scope": True, "reason": "fixture"}
                    if "within_scope" in schema["required"]
                    else {key: 0 for key in schema["required"]}
                )
                return result, {"raw_path": "raw/" + path.name}

            with patch("data_pipeline.structured_request", side_effect=rank):
                bundle = retrieve(folder, "unrelated sports", request_fn=self.fake_embed)
            self.assertEqual(bundle["evidence"], [])
            self.assertTrue(bundle["retrieval"]["no_relevant_evidence"])

    def test_embedding_response_reordered_and_duplicate_index(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self, *args):
                return json.dumps(payload).encode()

        payload = {
            "model": "text-embedding-3-small",
            "data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}],
        }
        with (
            patch("data_pipeline.gateway_key", return_value="fixture"),
            patch("ai_http.AI_OPENER.open", return_value=Response()),
        ):
            vectors, _ = embedding_request(["first", "second"], "text-embedding-3-small", 2)
            self.assertEqual(vectors, [[1, 0], [0, 1]])
            payload["data"][1]["index"] = 1
            with self.assertRaisesRegex(ValueError, "contract"):
                embedding_request(["first", "second"], "text-embedding-3-small", 2)

    def test_table_chunks_keep_headers_and_coordinates(self):
        from parsing import html_tables

        with tempfile.TemporaryDirectory() as name:
            folder = self.setup_run(Path(name))
            doc = json.loads((folder / "parsed/document-001.json").read_text())
            doc["tables"] = html_tables(
                "<table><tr><th>Year</th><th>Rain mm</th></tr><tr><td>2020</td><td>1000</td></tr></table>"
            )
            save_json(folder / "parsed/document-002.json", doc)
            build(folder, dimensions=2, request_fn=self.fake_embed)
            chunks = json.loads((folder / "data/chunks.json").read_text())
            row = next(
                c
                for c in chunks
                if c["locator"].get("representation") == "row_with_headers"
                and c["locator"].get("row") == 1
            )
            self.assertIn('"headers": ["Rain mm"]', row["text"])
            self.assertIn('"text": "1000"', row["text"])
            self.assertIn('"column": 1', row["text"])


if __name__ == "__main__":
    unittest.main()
