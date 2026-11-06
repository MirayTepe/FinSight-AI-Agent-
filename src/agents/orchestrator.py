
from __future__ import annotations

import datetime
import enum
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from src.tools.mcp_client import EdgarMCPClient
from src.security.guardrails import (
    InvestmentAdviceGuardrail,
    PromptInjectionShield,
    append_legal_disclaimer,
)

logger = logging.getLogger("finsight_orchestrator")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class QueryType(str, enum.Enum):
    NUMERICAL = "NUMERICAL"                                             
    TEXTUAL = "TEXTUAL"                                             
    HYBRID = "HYBRID"                                                          
    COMPARISON = "COMPARISON"                                                     


class SubTaskStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass
class SubTask:
    task_id: str
    assigned_agent: str                                                                    
    action: str                                                                                                 
    description: str
    params: Dict[str, Any] = field(default_factory=dict)
    status: SubTaskStatus = SubTaskStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None


@dataclass
class AgentStepRecord:
    step_number: int
    agent_name: str
    action: str
    params: Dict[str, Any]
    observation_summary: str
    timestamp: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    duration_ms: float = 0.0
    success: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineStep:
    agent: str
    step_name: str
    round: int
    status: str                                             
    summary: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OrchestratorResult:
    ticker: str
    verdict: str                                                                    
    total_revision_rounds: int
    pipeline_steps: List[PipelineStep] = field(default_factory=list)
    critic_checks_summary: Dict[str, Any] = field(default_factory=dict)
    final_report: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "verdict": self.verdict,
            "total_revision_rounds": self.total_revision_rounds,
            "pipeline_steps": [s.to_dict() for s in self.pipeline_steps],
            "critic_checks_summary": self.critic_checks_summary,
            "final_report": self.final_report,
            "raw_data": self.raw_data,
        }


@dataclass
class SharedAgentState:
    query: str
    query_type: QueryType = QueryType.HYBRID
    target_tickers: List[str] = field(default_factory=list)
    target_years: List[int] = field(default_factory=list)
    target_sections: List[str] = field(default_factory=list)

    facts: Dict[str, Any] = field(default_factory=dict)

    metrics: Dict[str, Any] = field(default_factory=dict)

    chunks: List[Dict[str, Any]] = field(default_factory=list)

    sources: List[Dict[str, Any]] = field(default_factory=list)

    plan: List[SubTask] = field(default_factory=list)
    step_history: List[AgentStepRecord] = field(default_factory=list)
    current_step: int = 0
    max_steps: int = 8

    status: str = "INITIALIZED"                                                              
    final_response: Optional[str] = None
    error: Optional[str] = None

    def add_source(self, url: str, title: str, form: str = "10-K", meta: Optional[Dict[str, Any]] = None):
        for s in self.sources:
            if s.get("url") == url:
                return
        self.sources.append({
            "url": url,
            "title": title,
            "form": form,
            "meta": meta or {},
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "query_type": self.query_type.value,
            "target_tickers": self.target_tickers,
            "target_years": self.target_years,
            "target_sections": self.target_sections,
            "status": self.status,
            "current_step": self.current_step,
            "max_steps": self.max_steps,
            "facts": self.facts,
            "metrics": self.metrics,
            "chunks_count": len(self.chunks),
            "sources_count": len(self.sources),
            "sources": self.sources,
            "step_history": [s.to_dict() for s in self.step_history],
            "final_response": self.final_response,
            "error": self.error,
        }



class DataAgent:
    def __init__(self, mcp_client: Optional[EdgarMCPClient] = None):
        self.client = mcp_client or EdgarMCPClient()

    def fetch(self, ticker: str) -> Dict[str, Any]:
        ticker_clean = ticker.upper().replace(".IS", "")
        sample_path = Path(__file__).resolve().parent.parent.parent / "data" / "sample_financials.json"
        if sample_path.exists():
            try:
                with open(sample_path, "r", encoding="utf-8") as f:
                    samples = json.load(f).get("companies", {})
                    if ticker_clean in samples:
                        data = samples[ticker_clean]
                        fin_data = data.get("financials", {})
                        period_data = fin_data.get("2024_Q2", fin_data.get("2023_Q4", {}))
                        return {
                            "success": True,
                            "ticker": ticker,
                            "currency": data.get("currency", "TRY"),
                            "current_price": str(data.get("stock_price", "0")),
                            "market_cap": data.get("market_cap", 0),
                            "pe_ratio_calculated": data.get("pe_ratio", 0),
                            "pb_ratio_calculated": data.get("pb_ratio", 0),
                            **period_data,
                        }
            except Exception as e:
                logger.warning("sample_financials okunamadı: %s", e)

        res = self.client.call_tool("resolve_ticker_to_cik", {"ticker": ticker_clean})
        return res


class FinancialDataAgent(DataAgent):

    def __init__(self, mcp_client: Optional[EdgarMCPClient] = None):
        super().__init__(mcp_client)

    def execute(self, task: SubTask, state: SharedAgentState) -> Any:
        logger.info("[FinancialDataAgent] Görev icra ediliyor: %s", task.action)
        ticker = task.params.get("ticker", "AAPL").upper()

        if task.action == "resolve_cik":
            res = self.client.call_tool("resolve_ticker_to_cik", {"ticker": ticker})
            if res.get("success"):
                state.facts[f"{ticker}_cik"] = res.get("cik_10")
                state.facts[f"{ticker}_title"] = res.get("title")
                return res
            raise ValueError(f"CIK bulunamadı: {ticker}")

        elif task.action == "get_company_facts":
            start_year = task.params.get("start_year", min(state.target_years or [2020]))
            end_year = task.params.get("end_year", max(state.target_years or [2024]))

            res = self.client.call_tool(
                "get_company_facts",
                {
                    "cik": ticker,
                    "start_year": start_year,
                    "end_year": end_year,
                    "clean_series": True,
                },
            )

            if res.get("success"):
                data = res.get("data", {})
                state.facts[f"{ticker}_facts"] = data
                state.metrics[ticker] = {
                    "cagr_revenue_pct": data.get("cagr_revenue_pct"),
                    "cagr_period": data.get("cagr_period"),
                    "yearly_financials": data.get("yearly_financials", []),
                }

                state.add_source(
                    url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{str(data.get('cik')).zfill(10)}.json",
                    title=f"{data.get('entity_name')} SEC EDGAR XBRL Facts",
                    form="XBRL",
                )
                return data
            raise ValueError(f"Şirket finansal verileri çekilemedi: {res.get('error')}")

        elif task.action == "compute_metrics":
            res = self.client.call_tool("compute_financial_metrics", task.params)
            state.metrics[f"{ticker}_custom"] = res
            return res

        elif task.action == "compare_companies":
            tickers = task.params.get("tickers", state.target_tickers or ["AAPL", "MSFT", "NVDA"])
            metrics = task.params.get("metrics", ["revenue", "growth", "gross_margin", "net_margin"])
            years = task.params.get("years", state.target_years or [2022, 2023, 2024])
            res = self.client.call_tool("compare_companies", {
                "tickers": tickers,
                "metrics": metrics,
                "years": years,
            })
            state.facts["comparison"] = res
            if isinstance(res, dict):
                for src in res.get("sources", []):
                    state.add_source(url="https://www.sec.gov/edgar", title=src, form="10-K")
            return res

        raise NotImplementedError(f"Bilinmeyen eylem: {task.action}")


class FilingRAGAgent:

    def __init__(self, mcp_client: EdgarMCPClient):
        self.client = mcp_client

    def execute(self, task: SubTask, state: SharedAgentState) -> Any:
        logger.info("[FilingRAGAgent] Görev icra ediliyor: %s", task.action)
        ticker = task.params.get("ticker", "AAPL").upper()
        fy = task.params.get("fy", max(state.target_years or [2024]))
        section = task.params.get("section", "item_1a")

        if task.action == "search_filings":
            query = task.params.get("query", state.query)
            top_k = task.params.get("top_k", 3)

            res = self.client.call_tool(
                "search_filings",
                {
                    "query": query,
                    "ticker": ticker,
                    "fy": fy,
                    "section": section,
                    "top_k": top_k,
                },
            )

            if res.get("success"):
                results = res.get("results", [])
                for r in results:
                    chunk_data = r.get("chunk", {})
                    raw_text = chunk_data.get("text", "")
                    safe_wrapped_text = PromptInjectionShield.wrap_filing_excerpt(
                        excerpt_text=raw_text,
                        source_title=f"{ticker} FY{fy} {chunk_data.get('section_name', '')}",
                        fy=fy,
                        section=section,
                    )
                    chunk_data["safe_text"] = safe_wrapped_text
                    state.chunks.append(chunk_data)
                    if chunk_data.get("url"):
                        state.add_source(
                            url=chunk_data["url"],
                            title=f"{ticker} FY{fy} {chunk_data.get('section_name')}",
                            form=chunk_data.get("form", "10-K"),
                            meta={"accn": chunk_data.get("accn")},
                        )
                return results
            raise ValueError(f"10-K arama başarısız: {res.get('error')}")

        elif task.action == "get_filing_section":
            res = self.client.call_tool(
                "get_filing_section",
                {"ticker": ticker, "fy": fy, "section": section},
            )
            if res.get("success"):
                sec_text = res.get("text", "")
                state.chunks.append({
                    "chunk_id": f"{ticker}_{fy}_{section}_FULL",
                    "ticker": ticker,
                    "fy": fy,
                    "section": section,
                    "text": sec_text[:2000] + ("..." if len(sec_text) > 2000 else ""),
                })
                return sec_text
            raise ValueError(f"Bölüm tam metni alınamadı: {res.get('error')}")

        raise NotImplementedError(f"Bilinmeyen eylem: {task.action}")


class OrchestratorPlanner:

    KNOWN_TICKERS = {
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META",
        "THYAO", "GARAN", "TUPRS", "EREGL", "SISE", "KCHOL", "SAHOL", "ASELS", "BIST", "THY"
    }
    COMPANY_NAME_TO_TICKER = {
        "APPLE": "AAPL",
        "MICROSOFT": "MSFT",
        "GOOGLE": "GOOGL",
        "ALPHABET": "GOOGL",
        "AMAZON": "AMZN",
        "NVIDIA": "NVDA",
        "TESLA": "TSLA",
        "META": "META",
        "THYAO": "THYAO",
        "THY": "THYAO",
        "TURK HAVA YOLLARI": "THYAO",
        "TÜRK HAVA YOLLARI": "THYAO",
        "GARAN": "GARAN",
        "GARANTI": "GARAN",
        "GARANTİ": "GARAN",
        "GARANTI BBVA": "GARAN",
    }

    def __init__(
        self,
        mcp_client: Optional[EdgarMCPClient] = None,
        max_steps: int = 8,
        data_agent: Optional[Any] = None,
        analyst_agent: Optional[Any] = None,
        critic_agent: Optional[Any] = None,
        max_revision_rounds: int = 2,
    ):
        self.client = mcp_client or EdgarMCPClient()
        self.data_agent = data_agent or FinancialDataAgent(self.client)
        self.rag_agent = FilingRAGAgent(self.client)
        self.analyst_agent = analyst_agent
        self.critic_agent = critic_agent
        self.max_steps = max_steps
        self.max_revision_rounds = max_revision_rounds

    def classify_query(self, query: str) -> Tuple[QueryType, List[str], List[int], List[str]]:
        q_lower = query.lower()

        found_tickers: List[str] = []
        query_upper = query.upper()
        for cname, ticker_mapped in self.COMPANY_NAME_TO_TICKER.items():
            if cname in query_upper and ticker_mapped not in found_tickers:
                found_tickers.append(ticker_mapped)

        words = re.findall(r"\b[A-Za-z0-9_]{1,15}\b", query)
        for w in words:
            up = w.upper()
            if up in self.KNOWN_TICKERS and up not in found_tickers:
                found_tickers.append(up)
            elif up in self.COMPANY_NAME_TO_TICKER:
                mapped = self.COMPANY_NAME_TO_TICKER[up]
                if mapped not in found_tickers:
                    found_tickers.append(mapped)

        if not found_tickers:
            found_tickers = ["AAPL"]              

        years_found = [int(y) for y in re.findall(r"\b(20[1-2][0-9])\b", query)]
        if not years_found:
            years_found = [2024]
        years_found = sorted(list(set(years_found)))

        sections_found: List[str] = []
        if any(k in q_lower for k in ["risk", "tehdit", "risk factor", "jeopolitik", "belirsizlik"]):
            sections_found.append("item_1a")
        if any(k in q_lower for k in ["yönetim", "md&a", "discussion", "faaliyet raporu", "analiz"]):
            sections_found.append("item_7")
        if any(k in q_lower for k in ["iş modeli", "business", "ürün", "hizmet"]):
            sections_found.append("item_1")

        has_comparison = (
            len(found_tickers) >= 2
            or any(k in q_lower for k in ["karşılaştır", "kıyasla", "compare", "vs", "versus"])
        )

        numerical_keywords = [
            "gelir", "revenue", "satış", "marj", "cagr", "büyüme", "kâr", "kar",
            "margin", "eps", "f/k", "pe", "rasyo", "rakam", "oran"
        ]
        textual_keywords = [
            "risk", "tedarik zinciri", "supply chain", "dava", "regülasyon",
            "antitröst", "yönetim görüşü", "neden", "açıkla", "anlatım", "strateji"
        ]

        has_num = any(k in q_lower for k in numerical_keywords)
        has_text = any(k in q_lower for k in textual_keywords) or len(sections_found) > 0

        if has_comparison:
            q_type = QueryType.COMPARISON
        elif has_num and has_text:
            q_type = QueryType.HYBRID
        elif has_text and not has_num:
            q_type = QueryType.TEXTUAL
        else:
            q_type = QueryType.NUMERICAL

        return q_type, found_tickers, years_found, sections_found

    def create_plan(self, state: SharedAgentState) -> List[SubTask]:
        tasks: List[SubTask] = []
        task_idx = 1

        for ticker in state.target_tickers:
            tasks.append(
                SubTask(
                    task_id=f"task_{task_idx}",
                    assigned_agent="FinancialDataAgent",
                    action="resolve_cik",
                    description=f"{ticker} için SEC CIK çözümlemesi",
                    params={"ticker": ticker},
                )
            )
            task_idx += 1

            if state.query_type in [QueryType.NUMERICAL, QueryType.HYBRID, QueryType.COMPARISON]:
                tasks.append(
                    SubTask(
                        task_id=f"task_{task_idx}",
                        assigned_agent="FinancialDataAgent",
                        action="get_company_facts",
                        description=f"{ticker} için XBRL companyfacts çekme ve rasyo hesaplama",
                        params={
                            "ticker": ticker,
                            "start_year": min(state.target_years),
                            "end_year": max(state.target_years),
                        },
                    )
                )
                task_idx += 1

            if state.query_type in [QueryType.TEXTUAL, QueryType.HYBRID]:
                target_sec = state.target_sections[0] if state.target_sections else "item_1a"
                target_fy = max(state.target_years)

                rag_query = state.query
                keywords_map = {
                    "tedarik": "supply chain",
                    "risk": "risk disruption",
                    "çip": "semiconductor wafer",
                    "yarı iletken": "semiconductor",
                    "dava": "litigation antitrust",
                    "antitröst": "antitrust regulatory",
                    "yönetim": "management discussion",
                    "gelir": "revenue sales",
                }
                added_en_terms = [v for k, v in keywords_map.items() if k in state.query.lower()]
                if added_en_terms:
                    rag_query = f"{state.query} {' '.join(added_en_terms)}"

                tasks.append(
                    SubTask(
                        task_id=f"task_{task_idx}",
                        assigned_agent="FilingRAGAgent",
                        action="search_filings",
                        description=f"{ticker} FY{target_fy} {target_sec} bölümünde arama yapma",
                        params={
                            "ticker": ticker,
                            "query": rag_query,
                            "fy": target_fy,
                            "section": target_sec,
                            "top_k": 3,
                        },
                    )
                )
                task_idx += 1

        if state.query_type == QueryType.COMPARISON and len(state.target_tickers) >= 2:
            tasks.append(
                SubTask(
                    task_id=f"task_{task_idx}",
                    assigned_agent="FinancialDataAgent",
                    action="compare_companies",
                    description=f"{', '.join(state.target_tickers)} şirketlerinin finansal karşılaştırma tablosu",
                    params={
                        "tickers": state.target_tickers,
                        "years": state.target_years or [2022, 2023, 2024],
                    },
                )
            )
            task_idx += 1

        return tasks

    def execute_plan(self, state: SharedAgentState) -> SharedAgentState:
        state.status = "IN_PROGRESS"

        for task in state.plan:
            if state.current_step >= state.max_steps:
                logger.warning(
                    "[Orchestrator] MAX_STEPS SINIRI AŞILDI! (step=%d / max=%d). Döngü güvenli şekilde durduruldu.",
                    state.current_step,
                    state.max_steps,
                )
                state.status = "MAX_STEPS_EXCEEDED"
                state.error = f"İşlem azami adım sınırına ({state.max_steps} adım) ulaştığı için koruma devreye girdi."
                break

            state.current_step += 1
            task.status = SubTaskStatus.IN_PROGRESS
            t_start = time.perf_counter()

            try:
                if task.assigned_agent == "FinancialDataAgent":
                    result = self.data_agent.execute(task, state)
                elif task.assigned_agent == "FilingRAGAgent":
                    result = self.rag_agent.execute(task, state)
                else:
                    raise ValueError(f"Bilinmeyen ajan: {task.assigned_agent}")

                t_dur = (time.perf_counter() - t_start) * 1000
                task.status = SubTaskStatus.COMPLETED
                task.result = result

                state.step_history.append(
                    AgentStepRecord(
                        step_number=state.current_step,
                        agent_name=task.assigned_agent,
                        action=task.action,
                        params=task.params,
                        observation_summary=f"{task.action} başarıyla tamamlandı.",
                        duration_ms=round(t_dur, 2),
                        success=True,
                    )
                )

            except Exception as err:
                t_dur = (time.perf_counter() - t_start) * 1000
                task.status = SubTaskStatus.FAILED
                task.error = str(err)
                logger.error("[Orchestrator] Görev başarısız: %s (%s)", task.task_id, err)

                state.step_history.append(
                    AgentStepRecord(
                        step_number=state.current_step,
                        agent_name=task.assigned_agent,
                        action=task.action,
                        params=task.params,
                        observation_summary=f"HATA: {err}",
                        duration_ms=round(t_dur, 2),
                        success=False,
                    )
                )

        if state.status != "MAX_STEPS_EXCEEDED":
            state.status = "COMPLETED"

        state.final_response = self._synthesize_response(state)
        return state

    def _synthesize_response(self, state: SharedAgentState) -> str:
        lines = []
        lines.append(f"# FinSight Analiz Raporu: {', '.join(state.target_tickers)}")
        lines.append(f"**Sorgu Türü:** `{state.query_type.value}` | **İcra Edilen Adım:** {state.current_step}/{state.max_steps}\n")

        if state.status == "MAX_STEPS_EXCEEDED":
            lines.append("> **Döngü Koruması Uyarısı:** İşlem azami adım sınırına ulaştığı için mevcut verilerle kısmi özet sunulmaktadır.\n")

        if state.metrics:
            lines.append("## [1] Sayısal & Deterministik Finansal Metrikler")
            for ticker, m_data in state.metrics.items():
                if "yearly_financials" in m_data:
                    lines.append(f"### {ticker} Yıllık Büyüme ve Marjlar")
                    lines.append("| Mali Yıl (FY) | Gelir | Brüt Marj | Faaliyet Marjı | Net Marj |")
                    lines.append("| :--- | :--- | :--- | :--- | :--- |")
                    for yf in m_data["yearly_financials"][-3:]:             
                        rev = f"${yf['revenue']:,.0f}" if yf.get("revenue") else "-"
                        gm = f"%{yf['gross_margin_pct']:.2f}" if yf.get("gross_margin_pct") else "-"
                        om = f"%{yf['operating_margin_pct']:.2f}" if yf.get("operating_margin_pct") else "-"
                        nm = f"%{yf['net_margin_pct']:.2f}" if yf.get("net_margin_pct") else "-"
                        lines.append(f"| {yf['fy']} | {rev} | {gm} | {om} | {nm} |")

                    if m_data.get("cagr_revenue_pct"):
                        lines.append(f"\n* **Bileşik Büyüme (CAGR) [{m_data.get('cagr_period')}]:** %{m_data.get('cagr_revenue_pct'):.2f}\n")

        if state.chunks:
            lines.append("## [2] 10-K Rapor Anlatımları & Riskler")
            for c in state.chunks[:3]:
                sec = c.get("section_name", c.get("section", "10-K"))
                fy = c.get("fy", "")
                lines.append(f"**[{sec} - FY{fy}]:**")
                lines.append(f"> {c.get('text')}\n")

        if state.sources:
            lines.append("## [3] Doğrulanmış Kaynaklar")
            for s in state.sources:
                lines.append(f"- [{s['title']}]({s['url']}) ({s['form']})")

        full_report = "\n".join(lines)
        return append_legal_disclaimer(full_report)

    def run_query(self, query: str, max_steps: Optional[int] = None) -> SharedAgentState:
        guard_res = InvestmentAdviceGuardrail.check_input(query)
        if not guard_res.is_safe:
            state = SharedAgentState(
                query=query,
                status="BLOCKED_BY_SAFETY_GUARDRAIL",
                final_response=guard_res.response,
                error=guard_res.rejection_reason,
            )
            return state

        effective_max = max_steps or self.max_steps
        q_type, tickers, years, sections = self.classify_query(query)

        state = SharedAgentState(
            query=query,
            query_type=q_type,
            target_tickers=tickers,
            target_years=years,
            target_sections=sections,
            max_steps=effective_max,
        )

        state.plan = self.create_plan(state)
        return self.execute_plan(state)

    def run(self, ticker: str) -> OrchestratorResult:
        pipeline_steps: List[PipelineStep] = []

        raw_data: Dict[str, Any] = {}
        try:
            if hasattr(self.data_agent, "fetch"):
                raw_data = self.data_agent.fetch(ticker)
            elif hasattr(self.data_agent, "execute"):
                dummy_state = SharedAgentState(query=ticker, target_tickers=[ticker])
                task = SubTask(task_id="fetch_1", assigned_agent="FinancialDataAgent", action="resolve_cik", description="CIK", params={"ticker": ticker})
                raw_data = self.data_agent.execute(task, dummy_state)
            else:
                raw_data = {"ticker": ticker, "status": "UNKNOWN"}

            pipeline_steps.append(
                PipelineStep(
                    agent="DataAgent",
                    step_name="Ham Veri Çekme",
                    round=0,
                    status="success" if raw_data.get("success", True) else "fail",
                    summary=f"{ticker} için ham finansal veriler başarıyla alındı.",
                    details={
                        "ticker": ticker,
                        "currency": raw_data.get("currency", "USD"),
                        "current_price": raw_data.get("current_price"),
                        "pe_ratio": raw_data.get("pe_ratio_calculated", raw_data.get("pe_ratio")),
                    },
                )
            )
        except Exception as e:
            pipeline_steps.append(
                PipelineStep(
                    agent="DataAgent",
                    step_name="Ham Veri Çekme",
                    round=0,
                    status="fail",
                    summary=f"Veri çekme hatası: {e}",
                    details={"error": str(e)},
                )
            )
            return OrchestratorResult(
                ticker=ticker,
                verdict="REJECTED",
                total_revision_rounds=0,
                pipeline_steps=pipeline_steps,
                critic_checks_summary={"error": str(e)},
                final_report="",
                raw_data={},
            )

        analyst = self.analyst_agent
        if analyst is None:
            from src.agents.analyst_agent import AnalystAgent
            analyst = AnalystAgent()

        critic = self.critic_agent
        if critic is None:
            from src.agents.critic_agent import CriticAgent
            critic = CriticAgent()

        from src.agents.analyst_agent import AnalystInput

        current_report = ""
        current_verdict_decision = "REJECTED"
        critic_summary: Dict[str, Any] = {}
        last_feedback: Optional[str] = None
        executed_rounds = 0

        for r in range(self.max_revision_rounds + 1):
            executed_rounds = r

            analyst_in = AnalystInput(
                ticker=ticker,
                raw_data=raw_data,
                critic_feedback=last_feedback,
                revision_round=r,
            )
            analyst_out = analyst.run(analyst_in)
            current_report = analyst_out.report_markdown

            pipeline_steps.append(
                PipelineStep(
                    agent="AnalystAgent",
                    step_name="Taslak Rapor Üretimi" if r == 0 else f"Revize Rapor Üretimi (Tur {r})",
                    round=r,
                    status="success" if getattr(analyst_out, "success", True) else "fail",
                    summary=f"Analyst {ticker} için {'taslak' if r == 0 else 'revize'} rapor üretti.",
                    details={"revision_round": r, "karakter_sayisi": len(current_report)},
                )
            )

            verdict = critic.verify(current_report, raw_data)
            current_verdict_decision = verdict.decision

            critic_summary = {
                "toplam_iddia": getattr(verdict, "total_count", len(getattr(verdict, "checks", []))),
                "gecersiz_iddia": getattr(verdict, "invalid_count", 0),
                "onay_orani": f"%{getattr(verdict, 'approval_rate', 1.0) * 100:.1f}",
                "karar": verdict.decision,
            }

            if verdict.decision == "APPROVED":
                pipeline_steps.append(
                    PipelineStep(
                        agent="CriticAgent",
                        step_name="Hallucination & Doğrulama Kapısı",
                        round=r,
                        status="success",
                        summary="Critic raporu ONAYLADI (%100 tutarlılık).",
                        details=critic_summary,
                    )
                )
                break
            else:
                last_feedback = getattr(verdict, "feedback", "Sayısal tutarsızlıklar tespit edildi.")
                pipeline_steps.append(
                    PipelineStep(
                        agent="CriticAgent",
                        step_name="Hallucination & Doğrulama Kapısı",
                        round=r,
                        status="fail",
                        summary=f"Critic raporu REDDETTİ: {getattr(verdict, 'invalid_count', 0)} hatalı iddia.",
                        details={
                            **critic_summary,
                            "feedback_preview": (last_feedback[:120] + "...") if len(last_feedback) > 120 else last_feedback,
                        },
                    )
                )

        final_verdict = current_verdict_decision
        if current_verdict_decision != "APPROVED":
            final_verdict = "REJECTED (MAX_ROUNDS_EXCEEDED)"

        return OrchestratorResult(
            ticker=ticker,
            verdict=final_verdict,
            total_revision_rounds=executed_rounds,
            pipeline_steps=pipeline_steps,
            critic_checks_summary=critic_summary,
            final_report=current_report,
            raw_data=raw_data,
        )


Orchestrator = OrchestratorPlanner
DataAgent = DataAgent
MAX_REVISION_ROUNDS = 2

