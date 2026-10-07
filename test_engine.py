import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import (
    ValidationError,
    discover_indicator,
    require_api_url,
    run,
    unpack_json,
    validate_rows,
)


class QualityGateTests(unittest.TestCase):
    def setUp(self):
        self.scope = {
            "source_id": "2",
            "country": "VN",
            "country_iso3": "VNM",
            "start_year": 2020,
            "end_year": 2021,
            "value_kind": "nonnegative_integer",
            "indicator_name": "Population, total",
        }
        self.meta = {"sourceid": "2", "lastupdated": "2026-07-13"}
        self.rows = [
            {
                "country": {"id": "VN"},
                "countryiso3code": "VNM",
                "indicator": {"id": "SP.POP.TOTL"},
                "date": str(year),
                "value": 100 + year,
                "unit": "",
            }
            for year in (2020, 2021)
        ]

    def validate(self, rows=None, meta=None):
        return validate_rows(
            self.meta if meta is None else meta,
            self.rows if rows is None else rows,
            self.scope,
            "SP.POP.TOTL",
        )

    def test_valid_rows_keep_original_locator(self):
        result = self.validate(list(reversed(self.rows)))
        self.assertEqual(result[0]["year"], 2020)
        self.assertEqual(result[0]["raw_locator"], "$[1][1]")
        self.assertEqual(result[0]["source_unit"], "")

    def test_reject_foreign_country(self):
        for key in ("country", "countryiso3code"):
            rows = copy.deepcopy(self.rows)
            rows[0][key] = {"id": "US"} if key == "country" else "USA"
            with self.subTest(key=key), self.assertRaises(ValidationError):
                self.validate(rows)

    def test_missing_year_is_not_zero(self):
        with self.assertRaisesRegex(ValidationError, "Missing years"):
            self.validate(self.rows[:1])

    def test_duplicate_year_rejected(self):
        with self.assertRaisesRegex(ValidationError, "duplicate"):
            self.validate(self.rows + [self.rows[0]])

    def test_wrong_year_indicator_and_source_rejected(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["date"] = "2019"
        with self.assertRaises(ValidationError):
            self.validate(rows)
        rows = copy.deepcopy(self.rows)
        rows[0]["indicator"]["id"] = "OTHER"
        with self.assertRaises(ValidationError):
            self.validate(rows)
        with self.assertRaises(ValidationError):
            self.validate(meta={**self.meta, "sourceid": "99"})

    def test_invalid_values_rejected(self):
        for value in (None, True, -1, "123", float("nan"), float("inf"), 123.5):
            rows = copy.deepcopy(self.rows)
            rows[0]["value"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.validate(rows)

    def test_api_error_and_pagination_rejected(self):
        for payload in (
            [{"message": [{"id": "120", "value": "Invalid value"}]}],
            [{"pages": 2, "page": 1, "total": 2}, self.rows],
            [{"pages": 1, "page": 1, "total": 99}, self.rows],
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                unpack_json(json.dumps(payload))

    def test_ambiguous_catalog_rejected(self):
        candidate = {
            "id": "SP.POP.TOTL",
            "name": "Population, total",
            "source": {"id": "2"},
            "sourceNote": "Definition",
            "sourceOrganization": "Publisher",
        }
        payload = [{"page": 1, "pages": 1, "total": 2}, [candidate, candidate]]
        with self.assertRaises(ValidationError):
            discover_indicator(json.dumps(payload), self.scope)

    def test_missing_provenance_rejected(self):
        candidate = {"id": "SP.POP.TOTL", "name": "Population, total", "source": {"id": "2"}}
        with self.assertRaises(ValidationError):
            discover_indicator(
                json.dumps([{"page": 1, "pages": 1, "total": 1}, [candidate]]), self.scope
            )

    def test_offsite_and_insecure_requests_rejected(self):
        for url in (
            "http://api.worldbank.org/v2/indicator",
            "https://api.worldbank.org.evil.com/v2/a",
            "https://127.0.0.1/v2/a",
            "https://api.worldbank.org/v2.evil/a",
            "https://api.worldbank.org:444/v2/a",
            "https://user@api.worldbank.org/v2/a",
        ):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                require_api_url(url)

    def test_network_failure_quarantines_without_accepted_data(self):
        config = Path(__file__).parent / "scopes/de-f-population.json"
        with tempfile.TemporaryDirectory() as temporary:
            with patch("engine.Fetcher.fetch", side_effect=TimeoutError("network unavailable")):
                self.assertEqual(run(config, Path(temporary)), 1)
            reports = list(Path(temporary).rglob("report.json"))
            self.assertEqual(len(reports), 1)
            self.assertEqual(json.loads(reports[0].read_text())["status"], "quarantined")
            self.assertFalse(list(Path(temporary).rglob("accepted.*")))


if __name__ == "__main__":
    unittest.main()
