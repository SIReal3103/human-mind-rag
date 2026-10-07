import json
import tempfile
import unittest
from pathlib import Path

from bot import ValidationError, expand_worldbank_catalog, extract_document, plan_scope
from parsing import html_article_text, html_tables
from trace import TraceStore, explain


class ArticleTests(unittest.TestCase):
    lead = (
        "The source lead identifies Ha Nam separately and states that results from adjoining "
        "provinces must not be added to its figures."
    )
    paragraphs = [
        "Ha Nam expanded transport connections between production areas and residential districts. "
        "The 2024 report describes completed projects and distinguishes them from plans that remain "
        "under review.",
        "Local authorities coordinated infrastructure and transport services across district "
        "boundaries. The source identifies each province, reporting period and measurement unit "
        "so readers can compare figures against the original report.",
    ]
    footer = (
        "<div><p>Contact our editorial office for publication details, office opening hours and "
        "advertising services. Readers can also consult the subscription terms and the monthly "
        "publication calendar for further information.</p><p>Copyright belongs to the publishing "
        "organization. The editorial board handles corrections and general enquiries during "
        "business hours. Visit the office reception to request printed copies or update a "
        "subscription address.</p></div>"
    )

    def test_article_body_survives_incidental_social_class_with_original_receipts(self):
        source = (
            "<html><head><title>Regional report</title></head><body><!-- layout --><div>"
            f'<div class="content-detail social-special-line"><div class="font-bold">{self.lead}'
            "</div><div>"
            + "".join(f"<p>{text}</p>" for text in self.paragraphs)
            + "<p>The value is <math><msup><mi>x</mi><mn>2</mn></msup></math>.</p>"
            "<table><tr><th>Year</th><th>Amount</th></tr>"
            "<tr><td>2024</td><td>1,234.50</td></tr></table></div></div></div>"
            + self.footer
            + "</body></html>"
        )
        document = extract_document(
            source.encode(), "text/html", "utf-8", "https://example.org/report"
        )
        for text in [self.lead, *self.paragraphs]:
            self.assertEqual(document["text"].count(text), 1)
        self.assertNotIn("Contact our editorial office", document["text"])
        self.assertIn("x^{2}", document["text"])
        self.assertEqual(document["tables"][0], html_tables(source)[0])
        self.assertEqual(document["tables"][0]["cells"][3]["text"], "1,234.50")
        self.assertEqual(
            document["html_math"][0]["locator"],
            "/html/body/div[1]/div/div[2]/p[3]/math",
        )
        self.assertIn("<math>", document["html_math"][0]["mathml"])

    def test_article_fallback_excludes_related_blocks_and_link_lists(self):
        prose = "".join(f"<p>{text}</p>" for text in self.paragraphs)
        for wrapper in ("nav", "aside", "footer"):
            self.assertIsNone(
                html_article_text(f"<{wrapper}><article>{prose}</article></{wrapper}>", "")
            )
        self.assertIsNone(
            html_article_text(
                '<div class="entry-content">'
                + "".join(f'<p><a href="/other">{text}</a></p>' for text in self.paragraphs)
                + "</div>",
                "",
            )
        )
        result = html_article_text(
            f'<article>{prose}<div class="related-articles"><p>Unrelated story</p></div>'
            "<aside>Sidebar text</aside><script>untrusted_script()</script></article>",
            "",
        )
        self.assertEqual(result, "\n".join(self.paragraphs))

    def test_existing_article_coverage_does_not_trigger_recovery(self):
        source = "<article>" + "".join(f"<p>{text}</p>" for text in self.paragraphs) + "</article>"
        self.assertIsNone(html_article_text(source, "\n".join(self.paragraphs)))

    def test_semantic_article_body_recovers_when_original_extraction_missed_it(self):
        source = (
            '<section itemprop="articleBody"><div>'
            + self.lead
            + "</div>"
            + "".join(f"<p>{text}</p>" for text in self.paragraphs)
            + "</section>"
        )
        self.assertEqual(
            html_article_text(source, "Contact our editorial office"),
            "\n".join([self.lead, *self.paragraphs]),
        )


class TableTests(unittest.TestCase):
    def test_merged_cells_keep_headers_caption_empty_cell_and_exact_money(self):
        source = """<html><body><h2>Dân số (người)</h2><table><caption>Bảng 1</caption>
          <tr><th rowspan="2">Năm</th><th colspan="2">Việt Nam</th></tr>
          <tr><th>Dân số</th><th>Ghi chú</th></tr>
          <tr><td>2024</td><td>100.987.686</td><td></td></tr></table></body></html>"""
        table = html_tables(source)[0]
        self.assertEqual(table["caption"], "Bảng 1")
        self.assertEqual(table["section"], "Dân số (người)")
        self.assertEqual(table["grid_cell_indices"], [[0, 1, 1], [0, 2, 3], [4, 5, 6]])
        self.assertEqual(table["cells"][5]["text"], "100.987.686")
        self.assertEqual(table["cells"][6]["text"], "")
        self.assertEqual(table["cells"][5]["locator"], "/html/body/table/tr[3]/td[2]")

    def test_navigation_and_script_do_not_enter_tables(self):
        source = "<html><body><nav><table><tr><td>menu</td></tr></table></nav><table><tr><td>42<script>malicious</script></td></tr></table></body></html>"
        tables = html_tables(source)
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]["cells"][0]["text"], "42")

    def test_invalid_or_overlapping_spans_fail_without_silent_repair(self):
        for source in [
            '<table><tr><td rowspan="4">x</td></tr></table>',
            '<table><tr><td colspan="101">x</td></tr></table>',
            '<table><tr><td>x</td><td rowspan="2">y</td></tr><tr><td colspan="2">z</td></tr></table>',
        ]:
            with self.subTest(source=source), self.assertRaises(ValidationError):
                html_tables(source)

    def test_html_document_retains_structured_table_and_source_locator(self):
        source = (
            "<html><head><title>Dân số Việt Nam</title></head><body><article><h1>Dân số Việt Nam</h1><p>"
            + ("Số liệu dân số Việt Nam được công bố theo năm, đơn vị người. " * 5)
            + "</p><table><tr><th>Năm</th><th>Dân số (người)</th></tr><tr><td>2024</td><td>100987686</td></tr></table></article></body></html>"
        )
        doc = extract_document(
            source.encode(), "text/html", "utf-8", "https://example.org/population"
        )
        self.assertEqual(doc["tables"][0]["cells"][3]["text"], "100987686")
        self.assertIn("/td[2]", doc["tables"][0]["cells"][3]["locator"])

    def test_short_table_is_retained_without_requiring_long_prose(self):
        source = b"<html><body><table><tr><th>Year</th><th>Population</th></tr><tr><td>2024</td><td>100987686</td></tr></table></body></html>"
        doc = extract_document(source, "text/html", "utf-8", "https://example.org/table")
        self.assertEqual(doc["tables"][0]["cells"][3]["text"], "100987686")

    def test_csv_bom_does_not_corrupt_header_or_numeric_string(self):
        source = "\ufeffyear,amount\n2024,9999999999999999.0001\n"
        doc = extract_document(
            source.encode(), "text/csv", "utf-8", "https://example.org/table.csv"
        )
        self.assertEqual(doc["table"][0][0], "year")
        self.assertEqual(doc["table"][1][1], "9999999999999999.0001")


class CatalogTests(unittest.TestCase):
    def expand(self, folder, items, meta=None, topic="Dân số Việt Nam 2020–2024"):
        trace = TraceStore(folder)
        origin = trace.node("search", "Actual search evidence", parents=[])
        candidates = [
            {
                "url": "https://datacatalog.worldbank.org/search/dataset/0037655",
                "search_queries": ["Vietnam population data"],
                "lineage_ids": [origin["id"]],
            }
        ]

        class HTTP:
            pass

        http = HTTP()
        http.trace = trace
        body = json.dumps([meta or {"page": 1, "pages": 1, "total": len(items)}, items]).encode()

        def fetch(url, kind):
            (folder / "catalog.json").write_bytes(body)
            artifact = trace.artifact("catalog.json", parents=[origin["id"]], stage="crawl")
            return body, {"raw_path": "catalog.json", "trace_id": artifact["id"]}

        http.fetch = fetch
        expand_worldbank_catalog(http, plan_scope(topic), candidates)
        return candidates, trace

    def test_catalog_selects_total_instead_of_growth_and_retains_origin(self):
        items = [
            {"id": "growth", "name": "Population growth (annual %)", "source": {"id": "2"}},
            {"id": "total", "name": "Population, total", "source": {"id": "2"}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            candidates, trace = self.expand(folder, items)
            self.assertEqual(
                candidates[-1]["url"], "https://data.worldbank.org/indicator/total?locations=VN"
            )
            trace.save()
            result = explain(folder, candidates[-1]["lineage_ids"][0])
            self.assertIn("search", {n["stage"] for n in result["backward_trace"]})

    def test_ambiguous_and_incomplete_catalog_never_emits_dataset_candidate(self):
        item = {"id": "total", "name": "Population, total", "source": {"id": "2"}}
        for items, meta in [([item, item], None), ([item], {"pages": 2, "total": 5})]:
            with tempfile.TemporaryDirectory() as directory:
                candidates, trace = self.expand(Path(directory), items, meta)
                self.assertEqual(len(candidates), 1)
                self.assertTrue(trace.issues)
                self.assertIn("catalog_error", candidates[0])

    def test_changed_scope_selects_life_expectancy_without_changing_code(self):
        items = [
            {"id": "life", "name": "Life expectancy at birth, total (years)", "source": {"id": "2"}}
        ]
        with tempfile.TemporaryDirectory() as directory:
            candidates, _ = self.expand(Path(directory), items, topic="Tuổi thọ Việt Nam 2020–2024")
            self.assertEqual(
                candidates[-1]["url"], "https://data.worldbank.org/indicator/life?locations=VN"
            )
