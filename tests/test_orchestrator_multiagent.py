
from pathlib import Path
import sys
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.agents.orchestrator import (
    AgentStepRecord,
    FilingRAGAgent,
    FinancialDataAgent,
    OrchestratorPlanner,
    QueryType,
    SharedAgentState,
    SubTask,
    SubTaskStatus,
)
from src.tools.mcp_client import EdgarMCPClient


class TestOrchestratorMultiAgent(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = EdgarMCPClient()
        cls.orchestrator = OrchestratorPlanner(mcp_client=cls.client, max_steps=8)

    def test_classify_numerical_query(self):
        q = "Apple'ın 2024 yılı brüt kâr marjı, faaliyet kârı ve 3 yıllık CAGR büyümesi kaç?"
        q_type, tickers, years, sections = self.orchestrator.classify_query(q)

        self.assertEqual(q_type, QueryType.NUMERICAL)
        self.assertIn("AAPL", tickers)
        self.assertIn(2024, years)

    def test_classify_textual_query(self):
        q = "Apple şirketinin Asya ve Tayvan'daki yarı iletken tedarik zinciri riskleri nelerdir?"
        q_type, tickers, years, sections = self.orchestrator.classify_query(q)

        self.assertEqual(q_type, QueryType.TEXTUAL)
        self.assertIn("AAPL", tickers)
        self.assertIn("item_1a", sections)

    def test_classify_hybrid_query(self):
        q = "Apple'ın 2024 gelir artışı ve marjlarını incele, ayrıca App Store antitröst risklerini açıkla"
        q_type, tickers, years, sections = self.orchestrator.classify_query(q)

        self.assertEqual(q_type, QueryType.HYBRID)
        self.assertIn("AAPL", tickers)

    def test_classify_comparison_query(self):
        q = "Apple ve Microsoft şirketlerinin 2024 faaliyet marjlarını karşılaştır"
        q_type, tickers, years, sections = self.orchestrator.classify_query(q)

        self.assertEqual(q_type, QueryType.COMPARISON)
        self.assertIn("AAPL", tickers)
        self.assertIn("MSFT", tickers)

    def test_create_plan_for_hybrid_query(self):
        state = SharedAgentState(
            query="Apple 2024 geliri ve riskleri",
            query_type=QueryType.HYBRID,
            target_tickers=["AAPL"],
            target_years=[2024],
            target_sections=["item_1a"],
        )

        plan = self.orchestrator.create_plan(state)
        self.assertGreaterEqual(len(plan), 3)

        agents_assigned = [t.assigned_agent for t in plan]
        self.assertIn("FinancialDataAgent", agents_assigned)
        self.assertIn("FilingRAGAgent", agents_assigned)

        actions = [t.action for t in plan]
        self.assertIn("resolve_cik", actions)
        self.assertIn("get_company_facts", actions)
        self.assertIn("search_filings", actions)

    def test_shared_state_accumulation(self):
        state = SharedAgentState(
            query="Apple 2024 analizi",
            query_type=QueryType.HYBRID,
            target_tickers=["AAPL"],
            target_years=[2024],
            target_sections=["item_1a"],
        )

        task_cik = SubTask(
            task_id="t1",
            assigned_agent="FinancialDataAgent",
            action="resolve_cik",
            description="CIK Çözümleme",
            params={"ticker": "AAPL"},
        )
        self.orchestrator.data_agent.execute(task_cik, state)

        self.assertEqual(state.facts.get("AAPL_cik"), "0000320193")

        task_rag = SubTask(
            task_id="t2",
            assigned_agent="FilingRAGAgent",
            action="search_filings",
            description="Risk araması",
            params={"ticker": "AAPL", "query": "semiconductor", "fy": 2024, "section": "item_1a"},
        )
        self.orchestrator.rag_agent.execute(task_rag, state)

        self.assertGreater(len(state.chunks), 0)
        self.assertGreater(len(state.sources), 0)

    def test_max_steps_loop_guard(self):
        short_orchestrator = OrchestratorPlanner(mcp_client=self.client, max_steps=1)

        state = SharedAgentState(
            query="Apple 2024 finansal ve risk analizi",
            query_type=QueryType.HYBRID,
            target_tickers=["AAPL"],
            target_years=[2024],
            target_sections=["item_1a"],
            max_steps=1,                      
        )

        state.plan = short_orchestrator.create_plan(state)
        self.assertGreater(len(state.plan), 1)

        result_state = short_orchestrator.execute_plan(state)

        self.assertEqual(result_state.status, "MAX_STEPS_EXCEEDED")
        self.assertEqual(result_state.current_step, 1)
        self.assertEqual(len(result_state.step_history), 1)
        self.assertIn("Döngü Koruması Uyarısı", result_state.final_response)

    def test_run_query_end_to_end(self):
        query = "Apple'ın 2024 marjları ve tedarik zinciri riskleri nelerdir?"
        final_state = self.orchestrator.run_query(query, max_steps=8)

        self.assertEqual(final_state.status, "COMPLETED")
        self.assertIn("AAPL", final_state.target_tickers)
        self.assertIn("AAPL", final_state.metrics)
        self.assertGreater(len(final_state.chunks), 0)
        self.assertGreater(len(final_state.sources), 0)

        report = final_state.final_response
        self.assertIn("# FinSight Analiz Raporu", report)
        self.assertIn("Sayısal & Deterministik Finansal Metrikler", report)
        self.assertIn("10-K Rapor Anlatımları & Riskler", report)
        self.assertIn("Doğrulanmış Kaynaklar", report)


if __name__ == "__main__":
    unittest.main()

