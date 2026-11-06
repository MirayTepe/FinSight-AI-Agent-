
import json
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

from src.observability.tracer import (
    FinSightTracer,
    SpanKind,
    SpanStatus,
    get_tracer,
    reset_tracer,
)
from evals.run_eval import MetricsEvaluator, SystemSimulator


class TestGoldenSet(unittest.TestCase):

    def setUp(self):
        self.golden_path = BASE_DIR / "evals" / "golden_set.jsonl"

    def test_golden_set_file_exists_and_count(self):
        self.assertTrue(self.golden_path.exists(), "golden_set.jsonl dosyası bulunamadı!")
        with open(self.golden_path, "r", encoding="utf-8") as f:
            items = [json.loads(line) for line in f if line.strip()]

        self.assertGreaterEqual(len(items), 25, f"En az 25 soru bekleniyordu, {len(items)} bulundu.")

        categories = [it["category"] for it in items]
        num_count = categories.count("numeric")
        txt_count = categories.count("textual")
        oos_count = categories.count("out_of_scope")
        inj_count = categories.count("prompt_injection")

        self.assertTrue(10 <= num_count <= 12, f"Sayısal soru sayısı 10-12 aralığında olmalı: {num_count}")
        self.assertTrue(8 <= txt_count <= 10, f"Metin soru sayısı 8-10 aralığında olmalı: {txt_count}")
        self.assertTrue(4 <= oos_count <= 5, f"Kapsam dışı soru sayısı 4-5 aralığında olmalı: {oos_count}")
        self.assertGreaterEqual(inj_count, 3, f"Injection soru sayısı >=3 olmalı: {inj_count}")

    def test_item_fields_and_validity(self):
        with open(self.golden_path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, 1):
                item = json.loads(line)
                self.assertIn("id", item, f"Satır {idx}: 'id' eksik")
                self.assertIn("category", item, f"Satır {idx}: 'category' eksik")
                self.assertIn("question", item, f"Satır {idx}: 'question' eksik")
                self.assertIn("ground_truth", item, f"Satır {idx}: 'ground_truth' eksik")
                self.assertIn("expected_refusal", item, f"Satır {idx}: 'expected_refusal' eksik")
                self.assertIsInstance(item["expected_refusal"], bool)


class TestObservabilityTracer(unittest.TestCase):

    def setUp(self):
        self.tracer = reset_tracer()

    def test_single_span_lifecycle_and_cost(self):
        tid = self.tracer.start_trace("trace_test_001")
        self.assertEqual(tid, "trace_test_001")

        with self.tracer.trace_span("test_tool", SpanKind.TOOL) as span:
            span.finish(
                output_data={"result": 42},
                status=SpanStatus.SUCCESS,
                input_tokens=1000,
                output_tokens=500,
                model_name="gemini-1.5-flash",
            )

        self.assertEqual(len(self.tracer.spans), 1)
        s = self.tracer.spans[0]
        self.assertEqual(s.name, "test_tool")
        self.assertEqual(s.span_kind, SpanKind.TOOL)
        self.assertEqual(s.status, SpanStatus.SUCCESS)
        self.assertEqual(s.total_tokens, 1500)
        self.assertAlmostEqual(s.cost_usd, 0.00045, places=5)
        self.assertGreaterEqual(s.latency_ms, 0.0)

    def test_nested_spans_parent_relationship(self):
        self.tracer.start_trace()
        with self.tracer.trace_span("parent_agent", SpanKind.AGENT) as parent_span:
            with self.tracer.trace_span("child_tool", SpanKind.TOOL) as child_span:
                child_span.finish()
            parent_span.finish()

        self.assertEqual(len(self.tracer.spans), 2)
        child = self.tracer.spans[0]
        parent = self.tracer.spans[1]
        self.assertEqual(child.parent_span_id, parent.span_id)

    def test_export_formats_phoenix_and_langfuse(self):
        with self.tracer.trace_span("llm_call", SpanKind.LLM) as span:
            span.finish(output_data="Hello", input_tokens=100, output_tokens=50)

        p_dict = self.tracer.spans[0].to_phoenix_format()
        self.assertIn("context", p_dict)
        self.assertIn("attributes", p_dict)
        self.assertEqual(p_dict["span_kind"], "LLM")
        self.assertEqual(p_dict["attributes"]["llm.token_count.total"], 150)

        lf_dict = self.tracer.spans[0].to_langfuse_format()
        self.assertIn("traceId", lf_dict)
        self.assertIn("usage", lf_dict)
        self.assertEqual(lf_dict["usage"]["totalTokens"], 150)

    def test_export_to_file(self):
        with self.tracer.trace_span("sample", SpanKind.CHAIN) as span:
            span.finish()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_file = os.path.join(tmp_dir, "traces.jsonl")
            count = self.tracer.export_jsonl(tmp_file)
            self.assertEqual(count, 1)
            self.assertTrue(os.path.exists(tmp_file))


class TestMetricsEvaluator(unittest.TestCase):

    def test_numeric_accuracy(self):
        self.assertTrue(MetricsEvaluator.evaluate_numeric_accuracy("Gelir 394328000000 USD'dir", "394328000000.0"))
        self.assertTrue(MetricsEvaluator.evaluate_numeric_accuracy("Gelir 394,328,000,000 USD", "394328000000.0"))
        self.assertTrue(MetricsEvaluator.evaluate_numeric_accuracy("Brüt marj %43.50", "43.31"))
        self.assertFalse(MetricsEvaluator.evaluate_numeric_accuracy("Brüt marj %44.50", "43.31"))

    def test_citation_precision(self):
        self.assertTrue(MetricsEvaluator.evaluate_citation_precision(["SEC EDGAR 10-K FY2024 Item 7"], "SEC EDGAR 10-K"))
        self.assertTrue(MetricsEvaluator.evaluate_citation_precision(["KAP-2024-001"], "KAP Announcement"))
        self.assertFalse(MetricsEvaluator.evaluate_citation_precision([], "SEC EDGAR 10-K"))
        self.assertFalse(MetricsEvaluator.evaluate_citation_precision(["Internet tahmini"], "SEC EDGAR 10-K"))

    def test_faithfulness(self):
        score_high = MetricsEvaluator.evaluate_faithfulness(
            "Apple tedarik zincirinde tek kaynaklı yarı iletken üreticilerine bağımlıdır.",
            "Apple tek kaynaklı yarı iletken tedarikçilerine bağımlıdır ve risk taşır."
        )
        self.assertGreater(score_high, 0.6)

        score_low = MetricsEvaluator.evaluate_faithfulness(
            "Güneşli bir günde futbol oynamak çok eğlencelidir.",
            "Apple çip tedarik zincirinde jeopolitik aksama riskleri bulunmaktadır."
        )
        self.assertLess(score_low, 0.3)

    def test_refusal_accuracy(self):
        self.assertTrue(MetricsEvaluator.evaluate_refusal_accuracy(
            is_refusal=True,
            expected_refusal=True,
            response_text="Yatırım tavsiyesi mevzuat uyarınca reddedilmiştir."
        ))
        self.assertFalse(MetricsEvaluator.evaluate_refusal_accuracy(
            is_refusal=False,
            expected_refusal=True,
            response_text="Apple hissesini hemen alın, 300 dolara yükselecek."
        ))


if __name__ == "__main__":
    unittest.main()

