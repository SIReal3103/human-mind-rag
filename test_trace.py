import json
import tempfile
from contextlib import closing
import unittest
from pathlib import Path
from unittest.mock import patch

from bot import ROOT, run_bot, traced
from trace import EvidenceError, TraceStore, explain


class TraceTests(unittest.TestCase):
    def test_parser_keyword_options_survive_trace_wrapper(self):
        with tempfile.TemporaryDirectory() as temporary:
            http = type("HTTP", (), {"trace": TraceStore(Path(temporary))})()

            def operation(value, *, parser_cache):
                return value, parser_cache

            result, node = traced(
                http, "parse", "Parser", operation, "source", parser_cache="cache"
            )
            self.assertEqual(result, ("source", "cache"))
            self.assertEqual(http.trace.nodes[0]["status"], "success")
            self.assertEqual(node, "n00001")

    def test_error_traces_to_exact_raw_field_and_search(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            trace = TraceStore(folder)
            scope = trace.node("scope", "Dân số Việt Nam", parents=[])
            search = trace.node("search", "Vietnam population", parents=[scope["id"]])
            (folder / "raw.json").write_text('[{"value":null}]')
            raw = trace.artifact("raw.json", parents=[search["id"]], stage="crawl")
            with self.assertRaises(EvidenceError):
                with trace.stage("check", "Validate value", parents=[raw["id"]]):
                    raise EvidenceError("INVALID_VALUE", "Null", "$[0].value", "number", None)
            result = explain(folder, "e00001")
            self.assertEqual(result["issue"]["locator"], "$[0].value")
            self.assertEqual(result["issue"]["repair"]["restart_from"], "parse")
            self.assertEqual(
                {n["stage"] for n in result["backward_trace"]},
                {"scope", "search", "crawl", "check"},
            )
            self.assertTrue(
                next(n for n in result["backward_trace"] if n["stage"] == "crawl")[
                    "artifact_integrity"
                ]
            )

    def test_output_trace_detects_modified_raw_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            trace = TraceStore(folder)
            (folder / "raw.txt").write_text("original")
            raw = trace.artifact("raw.txt", parents=[], stage="crawl")
            output = trace.node("save", "output", parents=[raw["id"]])
            (folder / "raw.txt").write_text("changed")
            result = explain(folder, output["id"])
            self.assertFalse(result["backward_trace"][1]["artifact_integrity"])

    def test_nested_failure_records_one_deepest_issue(self):
        with tempfile.TemporaryDirectory() as temporary:
            trace = TraceStore(Path(temporary))
            with self.assertRaises(EvidenceError):
                with trace.stage("check", "connector"):
                    with trace.stage("parse", "parser"):
                        raise EvidenceError("INVALID_VALUE", "Bad value")
            self.assertEqual(len(trace.issues), 1)
            self.assertEqual(trace.issues[0]["detected_stage"], "parse")
            self.assertEqual(trace.nodes[0]["issue_id"], trace.nodes[1]["issue_id"])

    def test_missing_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                TraceStore(Path(temporary)).node("save", "unknown input", parents=["unknown"])

    def fixture_run(self, temporary, corrupt=False):
        benchmark = json.loads((ROOT / "benchmarks/vietnam-population-2020-2024.json").read_text())
        rows = [
            {
                "country": {"id": "VN"},
                "countryiso3code": "VNM",
                "indicator": {"id": "SP.POP.TOTL"},
                "date": year,
                "value": value,
                "unit": "",
            }
            for year, value in benchmark["values"].items()
        ]
        if corrupt:
            rows[2]["value"] = None
        meta = {"pages": 1, "page": 1, "total": 5, "sourceid": "2", "lastupdated": "2026-07-13"}

        def discovery(http, plan, provider):
            search = http.trace.node(
                "search", "Fixture search — no live request", parents=[http.trace_parent]
            )
            return (
                [
                    {
                        "url": "https://data.worldbank.org/indicator/SP.POP.TOTL?locations=VN",
                        "title": "Population, total - Viet Nam",
                        "decision": "candidate",
                        "reason": "fixture",
                        "lineage_ids": [search["id"]],
                    }
                ],
                [],
            )

        def network(http, url, kind="page", robots=True):
            if kind == "metadata":
                data = [
                    {"pages": 1, "page": 1, "total": 1},
                    [
                        {
                            "id": "SP.POP.TOTL",
                            "name": "Population, total",
                            "source": {"id": "2"},
                            "sourceNote": "Midyear estimates",
                            "sourceOrganization": "UN",
                        }
                    ],
                ]
            elif kind == "country-metadata":
                data = [{"pages": 1, "page": 1, "total": 1}, [{"id": "VNM"}]]
            elif kind == "data":
                data = [meta, rows]
            elif kind == "crosscheck":
                data = None
            else:
                raise AssertionError("Unexpected request " + kind)
            if data is None:
                entries = "".join(
                    f'<wb:data><wb:country id="VN"/><wb:countryiso3code>VNM</wb:countryiso3code><wb:indicator id="SP.POP.TOTL"/><wb:date>{r["date"]}</wb:date><wb:value>{r["value"]}</wb:value></wb:data>'
                    for r in rows
                )
                body = (
                    '<wb:data xmlns:wb="http://www.worldbank.org" pages="1" page="1" total="5" sourceid="2" lastupdated="2026-07-13">'
                    + entries
                    + "</wb:data>"
                ).encode()
            else:
                body = json.dumps(data).encode()
            filename = kind + (".xml" if data is None else ".json")
            (http.folder / filename).write_bytes(body)
            import hashlib

            return body, {
                "url": url,
                "raw_path": "raw/" + filename,
                "sha256": hashlib.sha256(body).hexdigest(),
            }

        with (
            patch("bot.discover", side_effect=discovery),
            patch("bot.PublicHTTP._fetch", new=network),
        ):
            return run_bot(
                "Dân số Việt Nam 2020–2024", Path(temporary), search_provider="duckduckgo"
            )

    def test_integrated_output_traces_to_search_and_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            report, folder = self.fixture_run(temporary)
            self.assertEqual(report["status"], "has_verified_data")
            row = report["datasets"][0]["rows"][0]
            result = explain(folder, row["trace_id"])
            stages = {n["stage"] for n in result["backward_trace"]}
            self.assertTrue({"scope", "search", "discovery", "crawl", "parse", "check"} <= stages)
            paths = {n["refs"].get("path") for n in result["backward_trace"]}
            self.assertIn("raw/metadata.json", paths)
            self.assertIn("raw/crosscheck.xml", paths)

    def test_integrated_bad_row_quarantined_with_exact_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            report, folder = self.fixture_run(temporary, corrupt=True)
            self.assertEqual(report["status"], "incomplete")
            self.assertFalse((folder / "observations.csv").exists())
            self.assertEqual(len(report["issues"]), 1)
            result = explain(folder, report["issues"][0]["id"])
            self.assertEqual(result["issue"]["code"], "INVALID_VALUE")
            self.assertEqual(result["issue"]["locator"], "$[1][2].value")
            self.assertIn("search", {n["stage"] for n in result["backward_trace"]})

    def test_save_failure_rolls_back_and_does_not_publish_dataset(self):
        from engine import save_json as real_save
        import sqlite3

        def fail_parsed(path, data):
            if path.parent.name == "parsed" and path.name.startswith("series-"):
                raise OSError("simulated disk full")
            real_save(path, data)

        with tempfile.TemporaryDirectory() as temporary:
            with patch("bot.save_json", side_effect=fail_parsed):
                report, folder = self.fixture_run(temporary)
            self.assertEqual(report["datasets"], [])
            self.assertFalse((folder / "observations.csv").exists())
            self.assertEqual(report["issues"][0]["detected_stage"], "save")
            with closing(sqlite3.connect(folder / "crawl.sqlite")) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM observations").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
