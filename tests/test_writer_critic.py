
from pathlib import Path
import sys
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.agents.writer_critic import (
    FaithfulnessJudge,
    MetricPlaceholderEngine,
    NumberVerifier,
    WriterCriticOrchestrator,
)


class TestWriterCritic(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.metrics_data = {
            "AAPL": {
                "cagr_revenue_pct": 7.81,
                "cagr_period": "2015-2026",
                "yearly_financials": [
                    {
                        "fy": 2023,
                        "revenue": 365817000000.0,
                        "gross_margin_pct": 41.78,
                        "operating_margin_pct": 29.78,
                        "net_margin_pct": 25.88,
                    },
                    {
                        "fy": 2024,
                        "revenue": 394328000000.0,
                        "gross_margin_pct": 43.31,
                        "operating_margin_pct": 30.29,
                        "net_margin_pct": 25.31,
                    },
                ],
            }
        }

        cls.context_chunks = [
            {
                "section": "item_1a",
                "fy": 2024,
                "text": (
                    "The Company relies on single-source suppliers for advanced semiconductor "
                    "foundry wafer manufacturing in Asia. Disruptions in Taiwan could materially "
                    "adversely affect operations. Antitröst litigation in the US and Europe under "
                    "the Digital Markets Act may impact App Store revenues."
                ),
            }
        ]

        cls.orchestrator = WriterCriticOrchestrator(gemini_client=None)

    def test_placeholder_extraction_and_rendering(self):
        template = (
            "Apple'ın 2024 mali yılı geliri {{m:AAPL.revenue_2024}} seviyesine ulaşmıştır. "
            "Brüt kâr marjı {{m:AAPL.gross_margin_2024}}, faaliyet marjı {{m:AAPL.operating_margin_2024}} "
            "ve bileşik büyüme oranı (CAGR) {{m:AAPL.revenue_cagr}} olarak gerçekleşmiştir."
        )

        placeholders = MetricPlaceholderEngine.extract_placeholders(template)
        self.assertEqual(len(placeholders), 4)
        self.assertIn("AAPL.revenue_2024", placeholders)
        self.assertIn("AAPL.revenue_cagr", placeholders)

        rendered, missing = MetricPlaceholderEngine.render(template, self.metrics_data)
        self.assertEqual(len(missing), 0)

        self.assertIn("$394,328,000,000", rendered)
        self.assertIn("%43.31", rendered)
        self.assertIn("%30.29", rendered)
        self.assertIn("%7.81", rendered)
        self.assertNotIn("{{m:", rendered)

    def test_placeholder_missing_keys_reporting(self):
        template = "Bilinmeyen metrik: {{m:AAPL.non_existent_field}}"
        rendered, missing = MetricPlaceholderEngine.render(template, self.metrics_data)

        self.assertEqual(missing, ["AAPL.non_existent_field"])
        self.assertIn("{{MISSING:AAPL.non_existent_field}}", rendered)

    def test_verify_numbers_valid(self):
        valid_text = (
            "2024 yılında brüt kâr marjı %43.31 olarak gerçekleşmiş, "
            "gelir ise $394,328,000,000 tutarına yükselmiştir. CAGR oranı %7.81 seviyesindedir."
        )

        results = NumberVerifier.verify_numbers(valid_text, self.metrics_data, tolerance_pct=1.0)
        self.assertGreaterEqual(len(results), 3)

        for r in results:
            self.assertTrue(r.is_valid, f"Geçersiz sayıldı: {r.raw_match} ({r.message})")
            self.assertLessEqual(r.relative_error_pct, 1.0)

    def test_verify_numbers_rejects_hallucinations(self):
        hallucinated_text = (
            "2024 yılında brüt marj %55.80 olarak gerçekleşmiş, "                                  
            "toplam gelir ise $500,000,000,000 olmuştur."                                     
        )

        results = NumberVerifier.verify_numbers(hallucinated_text, self.metrics_data, tolerance_pct=1.0)
        invalid = [r for r in results if not r.is_valid]

        self.assertEqual(len(invalid), 2)
        self.assertIn("RED", invalid[0].message)

    def test_faithfulness_supported_text(self):
        faithful_report = (
            "Apple relies on single-source suppliers for advanced semiconductor foundry wafer manufacturing in Asia. "
            "Any disruptions in Taiwan could materially adversely affect operations. "
            "Antitrust litigation in Europe under the Digital Markets Act may impact App Store revenues."
        )

        verdict = FaithfulnessJudge.evaluate(faithful_report, self.context_chunks)
        self.assertTrue(verdict.is_faithful)
        self.assertGreaterEqual(verdict.faithfulness_score, 0.70)
        self.assertEqual(len(verdict.unsupported_claims), 0)

    def test_faithfulness_unsupported_text(self):
        unfaithful_report = (
            "Apple has completely closed all manufacturing facilities in Taiwan and moved to space shuttles. "
            "The company is launching an orbital space satellite network with alien technology."
        )

        verdict = FaithfulnessJudge.evaluate(unfaithful_report, self.context_chunks)
        self.assertFalse(verdict.is_faithful)
        self.assertLess(verdict.faithfulness_score, 0.50)
        self.assertGreater(len(verdict.unsupported_claims), 0)

    def test_revision_loop_success_on_round_1(self):
        def mock_writer(feedback=None, round_num=0):
            if round_num == 0:
                return "Apple brüt marjı %55.80 seviyesindedir. Disruption in Taiwan could affect operations."
            else:
                return "Apple brüt marjı {{m:AAPL.gross_margin_2024}} seviyesindedir. Disruptions in Taiwan could affect operations."

        loop_result = self.orchestrator.execute_writer_critic_loop(
            writer_fn=mock_writer,
            metrics_data=self.metrics_data,
            context_chunks=self.context_chunks,
        )

        self.assertEqual(loop_result["status"], "APPROVED")
        self.assertEqual(loop_result["total_rounds"], 1)
        self.assertIn("%43.31", loop_result["final_report"])

    def test_revision_loop_max_rounds_exhaustion(self):
        def stubborn_writer(feedback=None, round_num=0):
            return "Apple brüt marjı %99.99 seviyesindedir. Uzay mekiği yapıyoruz."

        loop_result = self.orchestrator.execute_writer_critic_loop(
            writer_fn=stubborn_writer,
            metrics_data=self.metrics_data,
            context_chunks=self.context_chunks,
        )

        self.assertEqual(loop_result["status"], "FORCE_APPROVED_WITH_WARNINGS")
        self.assertEqual(loop_result["total_rounds"], 2)
        self.assertIn("DİKKAT — DOĞRULAMA UYARISI", loop_result["final_report"])


if __name__ == "__main__":
    unittest.main()

