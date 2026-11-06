
import os
import sys
import tempfile
import unittest
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.tools.report_generator import export_report, format_research_memo


class TestReportGenerator(unittest.TestCase):

    def test_format_research_memo_structure(self):
        metrics = {
            "revenue": {"label": "Toplam Gelir", "value": "$394.33B", "trend": "+7.8%", "source": "SEC 10-K"},
            "gross_margin": {"label": "Brüt Marj", "value": "%43.31", "trend": "+1.5 pp", "source": "SEC 10-K"},
        }
        insights = [
            {"topic": "Tedarik Zinciri", "text": "Tayvan çip bağımlılığı", "citation": "Item 1A"}
        ]
        trace = {"latency_ms": 120.5, "total_tokens": 450, "cost_usd": 0.00015, "step_count": 5}

        memo = format_research_memo("AAPL", "Apple Inc.", metrics, insights, trace)
        
        self.assertIn("FinSight Analist İlk Bakış Notu: AAPL", memo)
        self.assertIn("Temel Finansal Göstergeler", memo)
        self.assertIn("$394.33B", memo)
        self.assertIn("%43.31", memo)
        self.assertIn("Tedarik Zinciri", memo)
        self.assertIn("Item 1A", memo)
        self.assertIn("YASAL UYARI & METODOLOJİ BİLDİRİMİ", memo)
        self.assertIn("kesinlikle yatırım danışmanlığı", memo)

    def test_export_report_markdown(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            sample_content = "# Apple Notu\nGelir: $394.33B"
            saved_path = export_report(
                ticker="AAPL",
                report_content=sample_content,
                format="markdown",
                output_dir=tmp_dir,
                metadata={"analyst": "FinSight AI"},
            )

            self.assertTrue(os.path.exists(saved_path))
            self.assertTrue(saved_path.endswith(".md"))

            with open(saved_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn("AAPL", content)
            self.assertIn("analyst: FinSight AI", content)
            self.assertIn("YASAL UYARI", content)

    def test_export_report_pdf_html(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            sample_content = "# Garanti BBVA\nNet Faiz Marjı Analizi"
            saved_path = export_report(
                ticker="GARAN",
                report_content=sample_content,
                format="pdf",
                output_dir=tmp_dir,
            )

            self.assertTrue(os.path.exists(saved_path))
            self.assertTrue(saved_path.endswith(".pdf"))

            with open(saved_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn("<!DOCTYPE html>", content)
            self.assertIn("GARAN", content)


if __name__ == "__main__":
    unittest.main()

