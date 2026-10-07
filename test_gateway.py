import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gateway import search_gateway


class SearchTests(unittest.TestCase):
    def test_openai_destination_and_citation_evidence(self):
        payload = {
            "status": "completed",
            "id": "fixture-response",
            "model": "gpt-4.1-mini",
            "output": [
                {"type": "web_search_call", "status": "completed"},
                {
                    "type": "message",
                    "content": [
                        {
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://data.worldbank.org/",
                                    "title": "World Bank",
                                }
                            ]
                        }
                    ],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with (
                patch("gateway.gateway_key", return_value="fixture-secret"),
                patch(
                    "ai_http.AI_OPENER.open", return_value=io.BytesIO(json.dumps(payload).encode())
                ) as fetch,
            ):
                results, evidence = search_gateway("population Vietnam", folder, 1)
            request = fetch.call_args.args[0]
            self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
            self.assertEqual(json.loads(request.data)["tool_choice"], "required")
            self.assertEqual(
                json.loads(request.data)["input"][-1],
                {"role": "user", "content": "population Vietnam"},
            )
            self.assertEqual(results[0]["url"], "https://data.worldbank.org/")
            self.assertEqual(evidence["web_search_calls"], 1)
            self.assertNotIn("fixture-secret", (folder / "gateway-search-1.json").read_text())

    def test_text_links_without_search_evidence_are_rejected(self):
        payload = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"text": "https://data.worldbank.org/", "annotations": []}],
                }
            ],
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("gateway.gateway_key", return_value="fixture-secret"),
            patch("ai_http.AI_OPENER.open", return_value=io.BytesIO(json.dumps(payload).encode())),
        ):
            with self.assertRaisesRegex(ValueError, "web_search_call"):
                search_gateway("population Vietnam", Path(directory), 1)

    def test_vietnamese_query_is_sent_as_utf8_separate_from_instructions(self):
        payload = {
            "status": "completed",
            "output": [
                {"type": "web_search_call", "status": "completed"},
                {"content": [{"annotations": [{"url": "https://example.org/data"}]}]},
            ],
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("gateway.gateway_key", return_value="fixture-secret"),
            patch(
                "ai_http.AI_OPENER.open", return_value=io.BytesIO(json.dumps(payload).encode())
            ) as fetch,
        ):
            search_gateway("tội phạm ma túy Việt Nam", Path(directory), 1)
        body = fetch.call_args.args[0].data
        self.assertIn("tội phạm ma túy Việt Nam".encode(), body)
        self.assertEqual(json.loads(body)["input"][-1]["content"], "tội phạm ma túy Việt Nam")
