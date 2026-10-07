import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot import plan_scope, relevance
from semantic import ValidationError, plan_request, rank_request, check_request


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.brief = "Tỉ lệ tội phạm ma túy Việt Nam 2010–2015"
        self.plan = {
            "metric": "Tỉ lệ tội phạm ma túy",
            "content_mode": "statistical",
            "denominator": None,
            "country": "VN",
            "start_year": 2010,
            "end_year": 2015,
            "concepts": [["tội phạm", "crime", "offences"], ["ma túy", "drug"]],
            "queries": ["Vietnam drug crime rate 2010 2015", "Tội phạm ma túy Việt Nam 2010 2015"],
            "exclusions": ["Tỉ lệ sử dụng ma túy"],
            "ambiguities": ["Chưa xác định mẫu số"],
        }

    def mock_plan(self, value=None, brief=None):
        with (
            tempfile.TemporaryDirectory() as d,
            patch("semantic.structured_request", return_value=(value or self.plan, {})),
        ):
            text = brief or self.brief
            return plan_request(text, plan_scope(text), Path(d))[0]

    def test_country_year_matches_cannot_promote_business_page(self):
        plan = self.mock_plan()
        self.assertEqual(relevance("Doanh nghiệp Việt Nam giai đoạn 2010–2015", plan), 0)
        self.assertEqual(relevance("Drug offences Vietnam 2010", plan), 10)

    def test_any_subject_and_country_supported_without_topic_dictionary(self):
        value = copy.deepcopy(self.plan)
        value.update(
            metric="Annual precipitation",
            country="TH",
            concepts=[["rainfall", "precipitation", "lượng mưa"]],
            queries=["Thailand rainfall 2010 2015"],
            exclusions=[],
            ambiguities=[],
        )
        plan = self.mock_plan(value, "Lượng mưa Thái Lan 2010–2015")
        self.assertEqual(plan["country"], "TH")
        self.assertEqual(relevance("Annual precipitation in Thailand", plan), 10)

    def test_mentioning_population_as_denominator_does_not_activate_population_connector(self):
        plan = self.mock_plan(brief="Tội phạm ma túy trên dân số Việt Nam 2010–2015")
        self.assertIsNone(plan["topic"])

    def test_changed_years_and_extra_fields_fail(self):
        for change in ({"start_year": 2011}, {"injected": "run command"}):
            value = {**self.plan, **change}
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.mock_plan(value)

    def test_model_cannot_hide_missing_denominator_or_invent_one(self):
        plan = self.mock_plan(self.plan | {"ambiguities": []})
        self.assertTrue(plan["ambiguities"])
        with self.assertRaises(ValidationError):
            self.mock_plan(self.plan | {"denominator": "100000 dân"})

    def test_ranking_must_cover_exact_candidate_ids(self):
        candidates = [
            {"title": "A", "url": "https://example.org/a"},
            {"title": "B", "url": "https://example.org/b"},
        ]
        result = {
            "results": [
                {"id": 0, "relation": "direct", "reason": "x"},
                {"id": 0, "relation": "lead", "reason": "y"},
            ]
        }
        with (
            patch("semantic.structured_request", return_value=(result, {})),
            self.assertRaises(ValidationError),
        ):
            rank_request(self.plan | {"brief": self.brief}, candidates, Path("."))

    def check(self, result, text):
        with patch("semantic.structured_request", return_value=(copy.deepcopy(result), {})):
            return check_request(
                self.plan | {"brief": self.brief}, {"title": "Report", "text": text}, Path("."), 1
            )[0]

    def test_unrequested_country_cannot_reject_conceptual_evidence(self):
        result = {
            "subject_match": True,
            "geography_match": False,
            "contains_data": False,
            "contains_requested_metric": True,
            "years": [],
            "unit": None,
            "evidence_ids": [0],
            "missing": [],
        }
        plan = {
            **self.plan,
            "brief": "Tài liệu về định lý Pythagoras",
            "content_mode": "conceptual",
            "country": None,
            "start_year": None,
            "end_year": None,
        }
        with patch("semantic.structured_request", return_value=(copy.deepcopy(result), {})):
            checked, _ = check_request(
                plan,
                {"title": "Theorem", "text": "Pythagorean theorem applies to right triangles."},
                Path("."),
                1,
            )
        self.assertEqual(checked["status"], "review")
        self.assertFalse(checked["geography_match"])
        self.assertFalse(checked["country_gate_required"])
        # An explicitly requested country still requires geographic evidence.
        with patch("semantic.structured_request", return_value=(copy.deepcopy(result), {})):
            checked, _ = check_request(
                {**plan, "country": "VN"},
                {"title": "Theorem", "text": "Pythagorean theorem applies to right triangles."},
                Path("."),
                1,
            )
        self.assertEqual(checked["status"], "out_of_scope")
        self.assertTrue(checked["country_gate_required"])
        # Ignoring a non-applicable country gate must not bypass full-scope subject rejection.
        with patch(
            "semantic.structured_request", return_value=({**result, "subject_match": False}, {})
        ):
            checked, _ = check_request(
                plan,
                {"title": "Different scope", "text": "Unrelated publisher and region."},
                Path("."),
                1,
            )
        self.assertEqual(checked["status"], "out_of_scope")

    def test_fake_quotes_and_years_are_rejected(self):
        base = {
            "subject_match": True,
            "geography_match": True,
            "contains_data": True,
            "contains_requested_metric": False,
            "years": [2010],
            "unit": None,
            "evidence_ids": [999],
            "missing": ["denominator"],
        }
        with self.assertRaises(ValidationError):
            self.check(base, "Niên giám giới thiệu kinh tế Việt Nam.")
        with self.assertRaises(ValidationError):
            self.check(
                base | {"years": [2015], "evidence_ids": [0]},
                "Vietnam drug offences 2010: 100 cases.",
            )

    def test_partial_counts_do_not_become_verified_rates(self):
        quote = "Vietnam drug offences 2010: 100 cases."
        result = {
            "subject_match": True,
            "geography_match": True,
            "contains_data": True,
            "contains_requested_metric": False,
            "years": [2010],
            "unit": "cases",
            "evidence_ids": [0],
            "missing": ["denominator"],
        }
        checked = self.check(result, quote)
        self.assertEqual(checked["status"], "review")
        self.assertEqual(checked["missing_years"], [2011, 2012, 2013, 2014, 2015])
        self.assertNotIn("verified", checked["status"])
