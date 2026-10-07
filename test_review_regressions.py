"""Behavioral regressions found during the full data-bot audit."""

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

from ai_http import NoAIRedirect, post
from gateway import endpoint, gateway_key, require_capability, search_gateway
from semantic import check_request
from data_pipeline import build, retrieve, single_writer
import test_data_pipeline as fixtures


class ReviewRegressions(unittest.TestCase):
    def test_from_run_does_not_require_parser_runtime_or_reparse(self):
        from data_bot import main

        with (
            patch("sys.argv", ["data_bot.py", "--from-run", "existing-run"]),
            patch("document_parser.parser_options", side_effect=AssertionError("must not parse")),
            patch("data_bot.run_bot", side_effect=AssertionError("must not crawl")),
            patch(
                "data_bot.build",
                return_value={
                    "status": "ready_partial",
                    "chunk_count": 1,
                    "crawl_status": "needs_review",
                },
            ) as build_mock,
        ):
            self.assertEqual(main(), 0)
            self.assertEqual(build_mock.call_args.args[0], Path("existing-run"))

    def test_ai_redirect_and_unknown_destination_rejected(self):
        request = urllib.request.Request("https://api.openai.com/v1/responses")
        with self.assertRaisesRegex(ValueError, "redirect"):
            NoAIRedirect().redirect_request(request, None, 302, "", {}, "https://evil.example/")
        with self.assertRaisesRegex(ValueError, "allowlist"):
            post("https://evil.example/responses", {}, "fixture")

    def test_btc_does_not_use_openai_key_or_fallback(self):
        with (
            patch.dict(
                os.environ, {"AI_PROVIDER": "btc", "OPENAI_API_KEY": "fixture-openai"}, clear=True
            ),
            patch(
                "gateway.setting",
                side_effect=lambda name, default=None: os.environ.get(name, default),
            ),
        ):
            self.assertIsNone(gateway_key())
            self.assertEqual(endpoint("embeddings"), "https://api.thucchien.ai/embeddings")
            with self.assertRaisesRegex(ValueError, "CAPABILITY_UNVERIFIED"):
                require_capability("BTC_STRUCTURED_VERIFIED")

    def test_incomplete_search_never_accepts_citations(self):
        payload = {
            "status": "incomplete",
            "output": [
                {"type": "web_search_call", "status": "completed"},
                {"content": [{"annotations": [{"url": "https://example.org"}]}]},
            ],
        }
        with (
            tempfile.TemporaryDirectory() as name,
            patch("gateway.gateway_key", return_value="fixture"),
            patch("ai_http.AI_OPENER.open", return_value=io.BytesIO(json.dumps(payload).encode())),
        ):
            with self.assertRaisesRegex(ValueError, "incomplete"):
                search_gateway("query", Path(name), 1)

    def test_conceptual_text_without_numbers_is_eligible(self):
        quote = "The Pythagorean theorem applies to right triangles."
        plan = {
            "brief": "Pythagorean theorem",
            "metric": "Pythagorean theorem",
            "country": None,
            "content_mode": "conceptual",
            "concepts": [["Pythagorean theorem"]],
            "exclusions": [],
            "ambiguities": [],
            "start_year": None,
            "end_year": None,
        }
        result = {
            "subject_match": True,
            "geography_match": True,
            "contains_data": False,
            "contains_requested_metric": True,
            "years": [],
            "unit": None,
            "evidence_ids": [0],
            "missing": [],
        }
        with patch("semantic.structured_request", return_value=(result, {})):
            checked, _ = check_request(plan, {"title": "Theorem", "text": quote}, Path("."), 1)
        self.assertEqual(checked["status"], "review")
        self.assertEqual(checked["evidence_quotes"], [quote])
        self.assertEqual(checked["evidence_char_ranges"], [{"start": 0, "end": len(quote)}])

    def test_late_matching_section_inspected_and_quote_backed(self):
        quote = "The Pythagorean theorem applies to right triangles."
        text = ("irrelevant text " * 2200) + "\n" + quote
        plan = {
            "brief": "Pythagorean theorem",
            "metric": "Pythagorean theorem",
            "country": None,
            "content_mode": "conceptual",
            "concepts": [["Pythagorean theorem"]],
            "exclusions": [],
            "ambiguities": [],
            "start_year": None,
            "end_year": None,
        }

        def checker(task, schema, folder, name):
            segments = json.loads(task.split("\n", 1)[1])["segments"]
            index = next(s["id"] for s in segments if quote in s["text"])
            return {
                "subject_match": True,
                "geography_match": True,
                "contains_data": False,
                "contains_requested_metric": True,
                "years": [],
                "unit": None,
                "evidence_ids": [index],
                "missing": [],
            }, {}

        with patch("semantic.structured_request", side_effect=checker):
            checked, _ = check_request(plan, {"title": "Theorem", "text": text}, Path("."), 1)
        self.assertTrue(checked["input_truncated"])
        self.assertIn(quote, checked["evidence_quotes"][0])

    def test_run_lock_rejects_concurrent_mutation_and_releases_on_error(self):
        @single_writer
        def operation(folder):
            raise RuntimeError("fixture failure")

        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            with self.assertRaises(RuntimeError):
                operation(folder)
            self.assertFalse((folder / ".data-lock").exists())
            (folder / ".data-lock").mkdir()
            with self.assertRaisesRegex(ValueError, "RUN_BUSY"):
                operation(folder)

    def test_provider_change_invalidates_index_before_api_request(self):
        fixture = fixtures.DataTests()
        with tempfile.TemporaryDirectory() as name:
            folder = fixture.setup_run(Path(name))
            build(folder, dimensions=2, request_fn=fixture.fake_embed)
            with (
                patch("data_pipeline.provider", return_value="btc"),
                self.assertRaisesRegex(ValueError, "Provider"),
            ):
                retrieve(folder, "rain", request_fn=lambda *args: self.fail("must not call AI"))

    def test_outside_scope_gate_returns_empty_context_without_embedding(self):
        fixture = fixtures.DataTests()
        with tempfile.TemporaryDirectory() as name:
            folder = fixture.setup_run(Path(name))
            build(folder, dimensions=2, request_fn=fixture.fake_embed)

            def gate(task, schema, output, filename):
                path = output / (filename + ".json")
                path.write_text("{}")
                return {"within_scope": False, "reason": "outside corpus"}, {
                    "raw_path": "raw/" + path.name
                }

            with patch("data_pipeline.structured_request", side_effect=gate):
                bundle = retrieve(
                    folder,
                    "unrelated subject",
                    request_fn=lambda *args: self.fail("must not embed"),
                )
            self.assertFalse(bundle["evidence"])
            self.assertTrue(bundle["retrieval"]["outside_scope"])


if __name__ == "__main__":
    unittest.main()
