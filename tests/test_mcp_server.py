
from pathlib import Path
import sys
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.tools.mcp_client import EdgarMCPClient


class TestEdgarMCPServer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = EdgarMCPClient()

    def test_resolve_ticker_to_cik(self):
        res = self.client.call_tool("resolve_ticker_to_cik", {"ticker": "AAPL"})
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("ticker"), "AAPL")
        self.assertEqual(res.get("cik_10"), "0000320193")
        self.assertEqual(res.get("title"), "Apple Inc.")

    def test_get_company_facts(self):
        res = self.client.call_tool(
            "get_company_facts",
            {"cik": "0000320193", "start_year": 2023, "end_year": 2024},
        )
        self.assertTrue(res.get("success"))
        data = res.get("data", {})
        self.assertEqual(data.get("entity_name"), "Apple Inc.")
        self.assertGreaterEqual(len(data.get("yearly_financials", [])), 2)

    def test_search_filings_mcp(self):
        res = self.client.call_tool(
            "search_filings",
            {
                "query": "antitrust lawsuits DOJ",
                "ticker": "AAPL",
                "fy": 2024,
                "section": "item_1a",
                "top_k": 1,
            },
        )
        self.assertTrue(res.get("success"))
        self.assertGreaterEqual(res.get("results_count"), 1)
        first_chunk = res["results"][0]["chunk"]
        self.assertEqual(first_chunk["fy"], 2024)
        self.assertEqual(first_chunk["section"], "item_1a")

    def test_get_filing_section_mcp(self):
        res = self.client.call_tool(
            "get_filing_section",
            {"ticker": "AAPL", "fy": 2024, "section": "item_7"},
        )
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("section"), "item_7")
        self.assertIn("Total net sales", res.get("text"))

    def test_react_tool_definitions(self):
        tools = self.client.get_react_tool_definitions()
        self.assertEqual(len(tools), 6)
        tool_names = [t.name for t in tools]
        self.assertIn("resolve_ticker_to_cik", tool_names)
        self.assertIn("get_company_facts", tool_names)
        self.assertIn("search_filings", tool_names)
        self.assertIn("get_filing_section", tool_names)
        self.assertIn("compute_financial_metrics", tool_names)
        self.assertIn("fetch_market_data", tool_names)


if __name__ == "__main__":
    unittest.main()

