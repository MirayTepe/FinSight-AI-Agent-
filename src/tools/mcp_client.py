
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.mcp_server import mcp as fastmcp_server

logger = logging.getLogger("mcp_client")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class EdgarMCPClient:

    def __init__(self, use_subprocess: bool = False, server_script: Optional[Path] = None):
        self.use_subprocess = use_subprocess
        self.server_script = server_script or (ROOT_DIR / "src" / "mcp_server.py")
        self._server = fastmcp_server

    async def call_tool_async(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if not self.use_subprocess:
            try:
                res = await self._server.call_tool(tool_name, arguments)
                if isinstance(res, tuple) and len(res) == 2:
                    content_list, extra = res
                    if "result" in extra:
                        return extra["result"]
                    if content_list and hasattr(content_list[0], "text"):
                        try:
                            return json.loads(content_list[0].text)
                        except Exception:
                            return {"text": content_list[0].text}
                return {"result": res}
            except Exception as e:
                logger.error("[MCP Client] Araç çağrı hatası '%s': %s", tool_name, e)
                return {"success": False, "error": str(e)}

        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(self.server_script)],
            env=dict(os.environ),
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                if result.content and hasattr(result.content[0], "text"):
                    try:
                        return json.loads(result.content[0].text)
                    except Exception:
                        return {"text": result.content[0].text}
                return {"content": [c.dict() for c in result.content]}

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            try:
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(self.call_tool_async(tool_name, arguments))
            except Exception:
                # uvloop veya nest_asyncio'nun desteklemediği döngüler için
                # Ayrı bir thread üzerinde bağımsız asyncio.run ile çalıştır
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(asyncio.run, self.call_tool_async(tool_name, arguments))
                    return future.result()

        return asyncio.run(self.call_tool_async(tool_name, arguments))

    def get_react_tool_definitions(self) -> List[Any]:
        from src.agents.base_agent import ToolDefinition

        tools = [
            ToolDefinition(
                name="resolve_ticker_to_cik",
                description="Borsa hisse senedi sembolünden (örn: AAPL) SEC EDGAR 10 haneli CIK numarasını ve şirket unvanını döner.",
                args_schema='{"ticker": "AAPL"}',
                func=lambda args: self.call_tool("resolve_ticker_to_cik", args),
            ),
            ToolDefinition(
                name="get_company_facts",
                description="Şirketin SEC EDGAR XBRL companyfacts verilerini çeker, gelir serisini dikişsiz birleştirir ve rasyoları üretir.",
                args_schema='{"cik": "0000320193", "start_year": 2018, "end_year": 2024, "clean_series": true}',
                func=lambda args: self.call_tool("get_company_facts", args),
            ),
            ToolDefinition(
                name="search_filings",
                description="10-K yıllık rapor metinlerinde (Riskler, Yönetim Görüşü) yıl ve bölüm filtreli hibrit (BM25 + Vektör RRF) arama yapar.",
                args_schema='{"query": "semiconductor supply chain", "ticker": "AAPL", "fy": 2024, "section": "item_1a", "top_k": 3}',
                func=lambda args: self.call_tool("search_filings", args),
            ),
            ToolDefinition(
                name="get_filing_section",
                description="Arama yapmadan doğrudan şirketin belirli yıl ve bölümüne (item_1, item_1a, item_7) ait tam gövde metnini getirir.",
                args_schema='{"ticker": "AAPL", "fy": 2024, "section": "item_7"}',
                func=lambda args: self.call_tool("get_filing_section", args),
            ),
            ToolDefinition(
                name="compute_financial_metrics",
                description="Deterministik Python Decimal hesaplayıcı ile brüt marj, faaliyet marjı, net marj ve CAGR hesaplar.",
                args_schema='{"revenue": 1000.0, "gross_profit": 400.0, "cagr_start_value": 500.0, "cagr_end_value": 1000.0, "cagr_years": 3}',
                func=lambda args: self.call_tool("compute_financial_metrics", args),
            ),
            ToolDefinition(
                name="fetch_market_data",
                description="Yahoo Finance üzerinden canlı piyasa fiyatı, EPS, PD/DD ve Piyasa Değeri verilerini çeker.",
                args_schema='{"ticker": "AAPL"}',
                func=lambda args: self.call_tool("fetch_market_data", args),
            ),
        ]
        return tools

    def get_smolagents_tools(self) -> List[Any]:
        try:
            from smolagents import Tool
        except ImportError:
            logger.info("smolagents kütüphanesi kurulu değil, smolagents araçları oluşturulamadı.")
            return []

        client = self

        class ResolveTickerTool(Tool):
            name = "resolve_ticker_to_cik"
            description = "Resolves stock ticker symbol (e.g. 'AAPL') to SEC EDGAR 10-digit CIK number."
            inputs = {"ticker": {"type": "string", "description": "Ticker symbol"}}
            output_type = "string"

            def forward(self, ticker: str) -> str:
                res = client.call_tool("resolve_ticker_to_cik", {"ticker": ticker})
                return json.dumps(res, ensure_ascii=False)

        class GetCompanyFactsTool(Tool):
            name = "get_company_facts"
            description = "Fetches SEC EDGAR XBRL companyfacts financial series and calculates deterministic margins & CAGR."
            inputs = {
                "cik": {"type": "string", "description": "10-digit zero-padded CIK number"},
                "start_year": {"type": "integer", "description": "Start fiscal year", "nullable": True},
                "end_year": {"type": "integer", "description": "End fiscal year", "nullable": True},
            }
            output_type = "string"

            def forward(self, cik: str, start_year: int = 2018, end_year: int = 2024) -> str:
                res = client.call_tool("get_company_facts", {"cik": cik, "start_year": start_year, "end_year": end_year})
                return json.dumps(res, ensure_ascii=False)

        class SearchFilingsTool(Tool):
            name = "search_filings"
            description = "Performs hybrid (BM25 + Vector RRF) search on 10-K sections with year and section filters."
            inputs = {
                "query": {"type": "string", "description": "Search query"},
                "ticker": {"type": "string", "description": "Ticker symbol", "nullable": True},
                "fy": {"type": "integer", "description": "Fiscal year filter", "nullable": True},
                "section": {"type": "string", "description": "Section ('item_1', 'item_1a', 'item_7')", "nullable": True},
            }
            output_type = "string"

            def forward(self, query: str, ticker: str = "AAPL", fy: Optional[int] = None, section: Optional[str] = None) -> str:
                res = client.call_tool("search_filings", {"query": query, "ticker": ticker, "fy": fy, "section": section})
                return json.dumps(res, ensure_ascii=False)

        class GetFilingSectionTool(Tool):
            name = "get_filing_section"
            description = "Directly retrieves full body text of a 10-K section without vector search."
            inputs = {
                "ticker": {"type": "string", "description": "Ticker symbol"},
                "fy": {"type": "integer", "description": "Fiscal year"},
                "section": {"type": "string", "description": "Section key: item_1, item_1a, or item_7"},
            }
            output_type = "string"

            def forward(self, ticker: str, fy: int, section: str) -> str:
                res = client.call_tool("get_filing_section", {"ticker": ticker, "fy": fy, "section": section})
                return json.dumps(res, ensure_ascii=False)

        return [
            ResolveTickerTool(),
            GetCompanyFactsTool(),
            SearchFilingsTool(),
            GetFilingSectionTool(),
        ]
