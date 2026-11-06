
from decimal import Decimal
from pathlib import Path
import sys
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.tools.financial_calculator import (
    CAGRInput,
    FinancialCalculator,
    FinancialMetricsInput,
    GrossMarginInput,
    GrowthInput,
    InvalidPeriodError,
    NegativeValueError,
    NetMarginInput,
    OperatingMarginInput,
    ZeroDivisionFinancialError,
    cagr,
    compare_companies,
    compute_metrics,
)


class TestFinancialCalculator(unittest.TestCase):

    def test_growth_reference_values(self):
        out1 = FinancialCalculator.calculate_growth(
            GrowthInput(current_value=Decimal("115"), previous_value=Decimal("100"))
        )
        self.assertEqual(out1.growth_rate, Decimal("15.00"))
        self.assertEqual(out1.bps_change, Decimal("1500"))

        out2 = FinancialCalculator.calculate_growth(
            {"current_value": "127.35", "previous_value": "110.20"}
        )
        self.assertEqual(out2.growth_rate, Decimal("15.56"))
        self.assertEqual(out2.bps_change, Decimal("1556"))

        out3 = FinancialCalculator.calculate_growth(
            {"current_value": 80, "previous_value": 100}
        )
        self.assertEqual(out3.growth_rate, Decimal("-20.00"))
        self.assertEqual(out3.bps_change, Decimal("-2000"))

    def test_growth_zero_division(self):
        with self.assertRaises(ZeroDivisionFinancialError):
            FinancialCalculator.calculate_growth(
                {"current_value": "100", "previous_value": "0"}
            )

    def test_gross_margin_reference_values(self):
        out = FinancialCalculator.calculate_gross_margin(
            GrossMarginInput(revenue=Decimal("1000"), gross_profit=Decimal("432.50"))
        )
        self.assertEqual(out.gross_margin, Decimal("43.25"))

        aapl_gm = FinancialCalculator.calculate_gross_margin(
            {"revenue": "394328000000", "gross_profit": "170782000000"}
        )
        self.assertEqual(aapl_gm.gross_margin, Decimal("43.31"))

    def test_gross_margin_zero_or_negative_revenue(self):
        with self.assertRaises(ZeroDivisionFinancialError):
            FinancialCalculator.calculate_gross_margin({"revenue": "0", "gross_profit": "100"})

        with self.assertRaises(ZeroDivisionFinancialError):
            FinancialCalculator.calculate_gross_margin({"revenue": "-500", "gross_profit": "100"})

    def test_operating_margin_reference_values(self):
        out = FinancialCalculator.calculate_operating_margin(
            OperatingMarginInput(revenue=Decimal("1000"), operating_income=Decimal("256.30"))
        )
        self.assertEqual(out.operating_margin, Decimal("25.63"))

        aapl_om = FinancialCalculator.calculate_operating_margin(
            {"revenue": "394328000000", "operating_income": "119437000000"}
        )
        self.assertEqual(aapl_om.operating_margin, Decimal("30.29"))

    def test_operating_margin_zero_revenue(self):
        with self.assertRaises(ZeroDivisionFinancialError):
            FinancialCalculator.calculate_operating_margin({"revenue": "0", "operating_income": "50"})

    def test_net_margin_reference_values(self):
        out = FinancialCalculator.calculate_net_margin(
            NetMarginInput(revenue=Decimal("1000"), net_income=Decimal("198.75"))
        )
        self.assertEqual(out.net_margin, Decimal("19.88"))

        aapl_nm = FinancialCalculator.calculate_net_margin(
            {"revenue": "394328000000", "net_income": "99803000000"}
        )
        self.assertEqual(aapl_nm.net_margin, Decimal("25.31"))

        loss_out = FinancialCalculator.calculate_net_margin(
            {"revenue": "1000", "net_income": "-50"}
        )
        self.assertEqual(loss_out.net_margin, Decimal("-5.00"))

    def test_cagr_mathematical_precision(self):
        cagr1 = FinancialCalculator.calculate_cagr(
            CAGRInput(start_value=Decimal("100"), end_value=Decimal("200"), years=2)
        )
        self.assertEqual(cagr1.cagr, Decimal("41.42"))

        cagr2 = FinancialCalculator.calculate_cagr(
            {"start_value": "100", "end_value": "133.10", "years": 3}
        )
        self.assertEqual(cagr2.cagr, Decimal("10.00"))

        cagr3 = FinancialCalculator.calculate_cagr(
            {"start_value": "50", "end_value": "150", "years": 5}
        )
        self.assertEqual(cagr3.cagr, Decimal("24.57"))

    def test_cagr_invalid_inputs(self):
        with self.assertRaises(NegativeValueError):
            FinancialCalculator.calculate_cagr({"start_value": "0", "end_value": "100", "years": 2})

        with self.assertRaises(NegativeValueError):
            FinancialCalculator.calculate_cagr({"start_value": "-50", "end_value": "100", "years": 2})

        with self.assertRaises(NegativeValueError):
            FinancialCalculator.calculate_cagr({"start_value": "100", "end_value": "0", "years": 2})

        with self.assertRaises(InvalidPeriodError):
            FinancialCalculator.calculate_cagr({"start_value": "100", "end_value": "200", "years": 0})

        with self.assertRaises(InvalidPeriodError):
            FinancialCalculator.calculate_cagr({"start_value": "100", "end_value": "200", "years": -1})

    def test_float_rounding_issue_avoidance(self):
        float_rounded = round(2.675, 2)
        self.assertEqual(float_rounded, 2.67)                             

        d_val = Decimal("2.675").quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
        self.assertEqual(d_val, Decimal("2.68"))

    def test_compute_metrics_orchestration(self):
        payload = {
            "revenue": "1000",
            "gross_profit": "400",
            "operating_income": "250",
            "net_income": "200",
            "previous_revenue": "800",
            "cagr_start_value": "500",
            "cagr_end_value": "1000",
            "cagr_years": 3,
        }

        output = compute_metrics(payload)
        self.assertTrue(output.success)
        self.assertEqual(output.revenue, Decimal("1000"))
        self.assertEqual(output.growth, Decimal("25.00"))                        
        self.assertEqual(output.gross_margin, Decimal("40.00"))
        self.assertEqual(output.operating_margin, Decimal("25.00"))
        self.assertEqual(output.net_margin, Decimal("20.00"))
        self.assertEqual(output.cagr, Decimal("25.99"))                       
        self.assertEqual(len(output.errors), 0)

    def test_compute_metrics_non_strict_error_handling(self):
        payload = {
            "revenue": "1000",
            "gross_profit": "400",
            "cagr_start_value": "0",
            "cagr_end_value": "1000",
            "cagr_years": 3,
        }

        output = compute_metrics(payload, strict=False)
        self.assertFalse(output.success)
        self.assertEqual(output.gross_margin, Decimal("40.00"))
        self.assertIsNone(output.cagr)
        self.assertIn("cagr", output.errors)

    def test_compute_metrics_strict_mode(self):
        payload = {
            "revenue": "1000",
            "cagr_start_value": "0",
            "cagr_end_value": "1000",
            "cagr_years": 3,
        }
        with self.assertRaises(NegativeValueError):
            compute_metrics(payload, strict=True)

    def test_pdf_standard_cagr_function(self):
        res = cagr(100.0, 200.0, 4)
        self.assertAlmostEqual(res, 0.189207115, places=5)

        with self.assertRaises(ValueError) as ctx1:
            cagr(0.0, 100.0, 4)
        self.assertIn("CAGR tanımsız: başlangıç <= 0 veya dönem <= 0", str(ctx1.exception))

        with self.assertRaises(ValueError) as ctx2:
            cagr(100.0, 200.0, 0)
        self.assertIn("CAGR tanımsız: başlangıç <= 0 veya dönem <= 0", str(ctx2.exception))

    def test_compare_companies_multi_ticker(self):
        res = compare_companies(
            tickers=["AAPL", "MSFT", "NVDA"],
            metrics=["revenue", "growth", "gross_margin", "net_margin"],
            years=[2022, 2023, 2024],
        )
        self.assertIn("table", res)
        self.assertIn("fiscal_year_ends", res)
        self.assertIn("footnotes", res)
        self.assertIn("sources", res)

        self.assertGreater(len(res["table"]), 0)

        self.assertEqual(res["fiscal_year_ends"]["AAPL"]["FY2024"], "2024-09-28")
        self.assertEqual(res["fiscal_year_ends"]["MSFT"]["FY2024"], "2024-06-30")
        self.assertEqual(res["fiscal_year_ends"]["NVDA"]["FY2024"], "2024-01-28")

        footnote_text = " ".join(res["footnotes"])
        self.assertIn("Mali Yıl Farkı", footnote_text)
        self.assertIn("Birim Tutarlılığı", footnote_text)
        self.assertIn("Düzeltme Önceliği", footnote_text)


if __name__ == "__main__":
    unittest.main()

