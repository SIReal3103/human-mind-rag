import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from document_parser import (
    parse_document,
    parser_options,
    should_use_docling,
    worker_environment,
    document_type,
    run_worker,
)
from docling_worker import normalize_document, normalize_table
from engine import ValidationError


class ParserTests(unittest.TestCase):
    def test_crawl_pipeline_passes_docling_output_through_save_with_trace(self):
        from bot import run_bot

        def discover(http, plan, provider):
            source = http.trace.node("search", "Offline fixture", parents=[http.trace_parent])
            return [
                {
                    "url": "https://example.org/docling.pdf",
                    "title": "Docling tài liệu PDF",
                    "decision": "candidate",
                    "reason": "fixture",
                    "lineage_ids": [source["id"]],
                }
            ], []

        def fetch(http, url, kind="page", robots=True):
            (http.folder / "fixture.pdf").write_bytes(b"%PDF-fixture")
            return b"%PDF-fixture", {
                "raw_path": "raw/fixture.pdf",
                "final_url": url,
                "content_type": "application/pdf",
                "charset": "utf-8",
                "sha256": "fixture",
            }

        doc = {
            "title": "Docling tài liệu PDF",
            "text": "Docling chuyển đổi tài liệu PDF thành JSON. " * 6,
            "pages": [],
            "links": [],
            "parser": "docling-local-v1",
            "parser_config": self.options(),
            "parse_warnings": ["OCR needs review"],
        }
        with (
            tempfile.TemporaryDirectory() as name,
            patch("bot.discover", side_effect=discover),
            patch("bot.PublicHTTP._fetch", new=fetch),
            patch("document_parser.should_use_docling", return_value=True),
            patch("document_parser.parse_document", return_value=doc) as parser,
        ):
            report, folder = run_bot(
                "Thu thập tài liệu về Docling chuyển đổi PDF thành JSON.",
                Path(name),
                planner="rules",
                max_depth=0,
            )
            self.assertEqual(report["counts"].get("review"), 1)
            parsed = json.loads((folder / "parsed/document-001.json").read_text())
            self.assertEqual(parsed["parser"], "docling-local-v1")
            self.assertIn("OCR needs review", parsed["parse_warnings"])
            self.assertEqual(parser.call_args.args[1], "application/pdf")

    def test_octet_stream_routes_known_extensions_without_guessing_html(self):
        self.assertEqual(
            document_type("application/octet-stream", "https://example.org/a.docx", b"PK"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(
            document_type("text/plain", "https://example.org/file", b"%PDF-"), "application/pdf"
        )
        self.assertEqual(
            document_type("text/html", "https://example.org/a.pdf", b"<html>"), "text/html"
        )

    def test_real_worker_timeout_terminates_process(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run_worker([sys.executable, "-c", "import time; time.sleep(10)"], 0.1)

    def options(self):
        return {
            "mode": "docling",
            "ocr": "auto",
            "languages": ["vi", "en"],
            "max_pages": 2,
            "timeout": 10,
            "threads": 2,
        }

    def document(self):
        return {
            "text": "Real source text",
            "pages": [],
            "parser": "docling-local-v1",
            "parser_config": self.options(),
        }

    def fake_worker(self, command, timeout):
        Path(command[3]).write_text(json.dumps(self.document()))

    def test_parser_cache_reuses_only_conversion_not_scope_assessment(self):
        with (
            tempfile.TemporaryDirectory() as name,
            patch("document_parser.parser_options", self.options),
            patch("document_parser.runtime", return_value=Path(__file__)),
            patch("document_parser.run_worker", side_effect=self.fake_worker) as worker,
        ):
            first = parse_document(b"%PDF-fixture", "application/pdf", name)
            second = parse_document(b"%PDF-fixture", "application/pdf", name)
            self.assertFalse(first["parser_cache_hit"])
            self.assertTrue(second["parser_cache_hit"])
            self.assertNotIn("assessment", second)
            self.assertEqual(worker.call_count, 1)
            cache = next(Path(name).glob("*.json"))
            doc = json.loads(cache.read_text())
            doc["document"]["text"] = "changed"
            cache.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValidationError, "CACHE_INTEGRITY"):
                parse_document(b"%PDF-fixture", "application/pdf", name)

    def test_timeout_is_explicit_and_cannot_populate_cache(self):
        with (
            tempfile.TemporaryDirectory() as name,
            patch("document_parser.parser_options", self.options),
            patch("document_parser.runtime", return_value=Path(__file__)),
            patch(
                "document_parser.run_worker", side_effect=subprocess.TimeoutExpired("worker", 10)
            ),
        ):
            with self.assertRaisesRegex(ValidationError, "DOCLING_TIMEOUT"):
                parse_document(b"%PDF-fixture", "application/pdf", name)
            self.assertEqual(list(Path(name).iterdir()), [])

    def test_worker_receives_no_credentials_or_proxy_python_injection(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-key",
                "BTC_API_KEY": "test-key",
                "HTTPS_PROXY": "https://example.org",
                "PYTHONPATH": "/untrusted",
            },
        ):
            env = worker_environment()
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        for key in ("OPENAI_API_KEY", "BTC_API_KEY", "HTTPS_PROXY", "PYTHONPATH"):
            self.assertNotIn(key, env)

    def test_modes_and_missing_runtime_do_not_silently_accept_scans(self):
        with patch.dict(os.environ, {"DOCUMENT_PARSER": "native"}):
            self.assertFalse(should_use_docling("application/pdf", b"%PDF-"))
        with (
            patch.dict(os.environ, {"DOCUMENT_PARSER": "auto"}),
            patch("document_parser.runtime", return_value=Path("/missing/parser/python")),
        ):
            self.assertFalse(should_use_docling("application/pdf", b"%PDF-"))
            with self.assertRaisesRegex(ValidationError, "NOT_INSTALLED"):
                should_use_docling("image/png", b"image")
        for key, value in (
            ("DOCUMENT_MAX_PAGES", "201"),
            ("DOCUMENT_TIMEOUT", "0"),
            ("DOCUMENT_OCR", "invalid"),
            ("DOCUMENT_OCR_LANGUAGES", "xx"),
            ("DOCUMENT_THREADS", "99"),
            ("DOCUMENT_PARSER", "invalid"),
        ):
            with (
                self.subTest(key=key),
                patch.dict(os.environ, {key: value}),
                self.assertRaises(ValidationError),
            ):
                parser_options()

    def test_worker_failure_and_empty_output_are_not_evidence(self):
        def empty(command, timeout):
            Path(command[3]).write_text(json.dumps({**self.document(), "text": ""}))

        with (
            patch("document_parser.runtime", return_value=Path(__file__)),
            patch("document_parser.run_worker", side_effect=empty),
            self.assertRaisesRegex(ValidationError, "EMPTY"),
        ):
            parse_document(b"%PDF-fixture", "application/pdf")


class NormalizationTests(unittest.TestCase):
    def test_audit_detects_changed_native_text_or_page(self):
        from audit_run import docling_fidelity

        native = {"texts": [{"text": "Original", "prov": [{"page_no": 3}]}]}
        doc = {
            "docling_document": native,
            "pages": [
                {
                    "page": 3,
                    "text": "Original",
                    "items": [
                        {
                            "ref": "#/texts/0",
                            "label": "text",
                            "char_start": 0,
                            "char_end": 8,
                            "provenance": [{"page_no": 3}],
                        }
                    ],
                }
            ],
        }
        self.assertTrue(docling_fidelity(doc))
        native["texts"][0]["text"] = "Changed"
        self.assertFalse(docling_fidelity(doc))
        native["texts"][0]["text"] = "Original"
        doc["pages"][0]["page"] = 1
        self.assertFalse(docling_fidelity(doc))

    def cell(self, r, c, text, rowspan=1, colspan=1, header=False):
        return SimpleNamespace(
            start_row_offset_idx=r,
            start_col_offset_idx=c,
            end_row_offset_idx=r + rowspan,
            end_col_offset_idx=c + colspan,
            text=text,
            column_header=header,
            row_header=False,
            bbox=None,
        )

    def table(self, cells):
        return SimpleNamespace(
            data=SimpleNamespace(num_rows=2, num_cols=2, table_cells=cells),
            self_ref="#/tables/0",
            prov=[],
            caption_text=lambda doc: "Original caption",
        )

    def test_merged_header_and_precise_numeric_strings_keep_grid(self):
        table = normalize_table(
            self.table(
                [
                    self.cell(0, 0, "Amount", colspan=2, header=True),
                    self.cell(1, 0, "2024"),
                    self.cell(1, 1, "999999999999.0001"),
                ]
            ),
            None,
            "Section",
        )
        self.assertEqual(table["grid_cell_indices"], [[0, 0], [1, 2]])
        self.assertEqual(table["cells"][2]["text"], "999999999999.0001")
        self.assertEqual(table["locator"], "#/tables/0")

    def test_bad_coordinates_and_overlapping_cells_fail(self):
        for cells in (
            [self.cell(0, 0, "x", colspan=3)],
            [self.cell(0, 0, "x", colspan=2), self.cell(0, 1, "y")],
        ):
            with self.assertRaisesRegex(ValueError, "DOCLING_TABLE"):
                normalize_table(self.table(cells), None, "")

    def test_merged_numeric_values_are_flagged_without_inventing_rows(self):
        table = normalize_table(self.table([self.cell(1, 0, "0.965 0.969")]), None, "")
        self.assertEqual(table["cells"][0]["text"], "0.965 0.969")
        self.assertEqual(table["warnings"][0]["code"], "MULTIPLE_NUMERIC_VALUES")

    def test_page_number_and_bbox_are_not_invented_and_coverage_is_partial(self):
        bbox = {"page_no": 7, "bbox": {"l": 10, "t": 20, "r": 30, "b": 40}, "charspan": [0, 5]}
        prov = SimpleNamespace(page_no=7, model_dump=lambda **kwargs: bbox)
        item = SimpleNamespace(
            label=SimpleNamespace(value="text"), text="Hello", self_ref="#/texts/0", prov=[prov]
        )
        doc = SimpleNamespace(
            name="Source",
            iterate_items=lambda **kwargs: [(item, 0)],
            export_to_dict=lambda: {"texts": [{"text": "Hello", "prov": [bbox]}]},
        )
        result = normalize_document(doc, {"max_pages": 2}, 10, "success")
        self.assertEqual(result["pages"][0]["page"], 7)
        self.assertEqual(result["pages"][0]["items"][0]["provenance"], [bbox])
        self.assertEqual(result["pages"][0]["text"][0:5], "Hello")
        self.assertTrue(result["parse_partial"])
        item.prov = []
        result = normalize_document(doc, {"max_pages": 2}, 0, "success")
        self.assertEqual(result["pages"], [])
        self.assertEqual(result["unpaginated_items"][0]["provenance"], [])


if __name__ == "__main__":
    unittest.main()
