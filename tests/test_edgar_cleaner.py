
import json
import os
import sys
from pathlib import Path
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.tools.edgar_cleaner import (
    CleanMetricPoint,
    EdgarFactsCleaner,
    FinancialSanityError,
    UnitConsistencyError,
    UnitValidator,
)


class TestEdgarCleaner(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parent.parent
        cls.yaml_path = cls.root / "metrics.yaml"
        cls.cleaner = EdgarFactsCleaner(metrics_yaml_path=cls.yaml_path)

    def test_metrics_yaml_structure(self):
        metrics = self.cleaner.metrics_config
        required_metrics = [
            "revenue",
            "gross_profit",
            "gross_margin",
            "operating_income",
            "operating_margin",
            "net_income",
            "net_margin",
            "cagr",
        ]
        for m in required_metrics:
            self.assertIn(m, metrics, f"metrics.yaml içinde '{m}' tanımlı olmalıdır!")

        rev_tags = metrics["revenue"]["tags_priority"]
        self.assertIn("RevenueFromContractWithCustomerExcludingAssessedTax", rev_tags)
        self.assertIn("SalesRevenueNet", rev_tags)
        self.assertIn("Revenues", rev_tags)

        self.assertIn("formula", metrics["cagr"])
        self.assertIn("start_value", metrics["cagr"]["formula"])
        self.assertIn("end_value", metrics["cagr"]["formula"])

    def test_unit_validator_normalization(self):
        self.assertEqual(UnitValidator.normalize_unit("USD"), "USD")
        self.assertEqual(UnitValidator.normalize_unit("iso4217:USD"), "USD")
        self.assertEqual(UnitValidator.normalize_unit("USD/shares"), "USD/shares")
        self.assertEqual(UnitValidator.normalize_unit("shares"), "shares")
        self.assertEqual(UnitValidator.normalize_unit("pure"), "shares")

    def test_unit_validator_strict_rejection(self):
        with self.assertRaises(UnitConsistencyError):
            UnitValidator.validate_unit(
                actual_unit="shares",
                expected_unit="USD",
                metric_name="revenue",
                tag_name="SalesRevenueNet",
                strict=True,
            )

        with self.assertRaises(UnitConsistencyError):
            UnitValidator.validate_unit(
                actual_unit="USD",
                expected_unit="USD/shares",
                metric_name="eps_diluted",
                tag_name="EarningsPerShareDiluted",
                strict=True,
            )

    def test_unit_validator_non_strict(self):
        is_valid = UnitValidator.validate_unit(
            actual_unit="EUR",
            expected_unit="USD",
            metric_name="revenue",
            strict=False,
        )
        self.assertFalse(is_valid)

    def test_financial_sanity_validation(self):
        self.assertTrue(UnitValidator.validate_sanity("revenue", 100_000.0))
        self.assertFalse(UnitValidator.validate_sanity("revenue", -500.0, strict=False))

        with self.assertRaises(FinancialSanityError):
            UnitValidator.validate_sanity("revenue", -100.0, strict=True)

    def test_deduplication_and_revision_priority(self):
        mock_tag_data = {
            "units": {
                "USD": [
                    {
                        "fy": 2020,
                        "fp": "FY",
                        "form": "10-K",
                        "filed": "2020-10-30",
                        "val": 100.0,
                        "start": "2019-10-01",
                        "end": "2020-09-30",
                    },
                    {
                        "fy": 2020,
                        "fp": "FY",
                        "form": "10-K",
                        "filed": "2021-10-29",
                        "val": 105.0,
                        "start": "2019-10-01",
                        "end": "2020-09-30",
                    },
                    {
                        "fy": 2020,
                        "fp": "FY",
                        "form": "10-K/A",
                        "filed": "2022-01-15",
                        "val": 110.0,
                        "start": "2019-10-01",
                        "end": "2020-09-30",
                    },
                ]
            }
        }

        cleaned = self.cleaner.clean_single_tag(
            tag_data=mock_tag_data,
            expected_unit="USD",
            metric_name="revenue",
            tag_name="RevenueFromContractWithCustomerExcludingAssessedTax",
        )

        self.assertIn(2020, cleaned)
        pt = cleaned[2020]
        self.assertEqual(pt.val, 110.0)
        self.assertEqual(pt.form, "10-K/A")
        self.assertEqual(pt.filed, "2022-01-15")

    def test_tag_priority_time_series_merger(self):
        mock_facts = {
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {
                            "USD": [
                                {"fy": 2019, "fp": "FY", "form": "10-K", "filed": "2019-10-31", "val": 260.0, "start": "2018-10-01", "end": "2019-09-30"},
                                {"fy": 2020, "fp": "FY", "form": "10-K", "filed": "2020-10-30", "val": 274.0, "start": "2019-10-01", "end": "2020-09-30"},
                            ]
                        }
                    },
                    "Revenues": {
                        "units": {
                            "USD": [
                                {"fy": 2018, "fp": "FY", "form": "10-K", "filed": "2018-11-05", "val": 215.0, "start": "2017-10-01", "end": "2018-09-30"},
                                {"fy": 2019, "fp": "FY", "form": "10-K", "filed": "2019-10-31", "val": 999.0, "start": "2018-10-01", "end": "2019-09-30"},
                            ]
                        }
                    },
                    "SalesRevenueNet": {
                        "units": {
                            "USD": [
                                {"fy": 2016, "fp": "FY", "form": "10-K", "filed": "2016-10-26", "val": 215.0, "start": "2015-10-01", "end": "2016-09-30"},
                                {"fy": 2017, "fp": "FY", "form": "10-K", "filed": "2017-11-03", "val": 229.0, "start": "2016-10-01", "end": "2017-09-30"},
                            ]
                        }
                    },
                }
            }
        }

        series = self.cleaner.build_metric_series(mock_facts, "revenue")
        years = [p.fy for p in series]
        self.assertEqual(years, [2016, 2017, 2018, 2019, 2020])

        tag_map = {p.fy: (p.source_tag, p.val) for p in series}
        self.assertEqual(tag_map[2016], ("SalesRevenueNet", 215.0))
        self.assertEqual(tag_map[2017], ("SalesRevenueNet", 229.0))
        self.assertEqual(tag_map[2018], ("Revenues", 215.0))
        self.assertEqual(tag_map[2019], ("RevenueFromContractWithCustomerExcludingAssessedTax", 260.0))
        self.assertEqual(tag_map[2020], ("RevenueFromContractWithCustomerExcludingAssessedTax", 274.0))

    def test_cagr_calculation(self):
        res = self.cleaner.calculate_cagr(start_value=100.0, end_value=200.0, periods=2)
        self.assertEqual(res, 41.42)

        with self.assertRaises(ValueError):
            self.cleaner.calculate_cagr(start_value=-100.0, end_value=200.0, periods=2)
        with self.assertRaises(ValueError):
            self.cleaner.calculate_cagr(start_value=100.0, end_value=200.0, periods=0)

    def test_margin_calculations(self):
        rev_pt = CleanMetricPoint(fy=2023, fp="FY", val=1000.0, unit="USD", source_tag="rev", form="10-K", filed="2023-10-01")
        gp_pt = CleanMetricPoint(fy=2023, fp="FY", val=400.0, unit="USD", source_tag="gp", form="10-K", filed="2023-10-01")
        op_pt = CleanMetricPoint(fy=2023, fp="FY", val=250.0, unit="USD", source_tag="op", form="10-K", filed="2023-10-01")
        net_pt = CleanMetricPoint(fy=2023, fp="FY", val=200.0, unit="USD", source_tag="net", form="10-K", filed="2023-10-01")

        margins = self.cleaner.calculate_margins_for_year(rev_pt, gp_pt, op_pt, net_pt)
        self.assertEqual(margins["gross_margin"], 40.0)
        self.assertEqual(margins["operating_margin"], 25.0)
        self.assertEqual(margins["net_margin"], 20.0)

    def test_real_aapl_facts_integration(self):
        aapl_path = self.root / "data" / "raw" / "0000320193" / "companyfacts_0000320193.json"
        if not aapl_path.exists():
            self.skipTest("AAPL companyfacts dosyası mevcut değil, atlanıyor.")

        with open(aapl_path, "r", encoding="utf-8") as f:
            facts = json.load(f)

        summary = self.cleaner.generate_comprehensive_summary(facts, start_fy=2015, end_fy=2024)
        self.assertEqual(summary["entity_name"], "Apple Inc.")
        self.assertGreaterEqual(len(summary["yearly_financials"]), 10)

        self.assertIsNotNone(summary["cagr_revenue_pct"])
        self.assertGreater(summary["cagr_revenue_pct"], 0)

        item_2024 = next(x for x in summary["yearly_financials"] if x["fy"] == 2024)
        self.assertGreater(item_2024["revenue"], 300_000_000_000)
        self.assertIsNotNone(item_2024["gross_margin_pct"])
        self.assertIsNotNone(item_2024["operating_margin_pct"])
        self.assertIsNotNone(item_2024["net_margin_pct"])


if __name__ == "__main__":
    unittest.main()
