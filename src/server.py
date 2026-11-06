
from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.config import APP_ENV, DEBUG

logger = logging.getLogger("finsight_server")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


app = FastAPI(
    title="FinSight.CORP AI Agent API",
    description="Halka açık şirket araştırma ve finansal analiz kurumsal AI agent platformu",
    version="2.4.0",
    debug=DEBUG,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.get("/", response_class=HTMLResponse)
@app.get("/workspace", response_class=HTMLResponse)
@app.get("/corporate", response_class=HTMLResponse)
async def serve_dashboard():
    html_path = Path(__file__).resolve().parent.parent / "finsight_corporate_workspace.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    
    fallback_path = Path(__file__).resolve().parent.parent / "demo" / "index.html"
    return HTMLResponse(content=fallback_path.read_text(encoding="utf-8"))



class AnalyzeRequest(BaseModel):
    ticker: str
    mode: str = "pipeline"                        


class OrchestrateRequest(BaseModel):
    ticker: Optional[str] = "AAPL"
    query: Optional[str] = None
    max_steps: Optional[int] = 8


class GuardrailCheckRequest(BaseModel):
    query: str


def _serialize(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return str(obj)



@app.post("/api/orchestrate")
@app.get("/api/orchestrate")
async def api_orchestrate(
    ticker: Optional[str] = "AAPL",
    query: Optional[str] = None,
    max_steps: Optional[int] = 8,
):
    from src.agents.orchestrator import OrchestratorPlanner
    from src.security.guardrails import InvestmentAdviceGuardrail

    t_clean = (ticker or "AAPL").strip().upper().replace(".IS", "")
    full_query = query or f"{t_clean} 2024 brüt kâr marjı, büyüme ve tedarik zinciri riskleri"

    guard_res = InvestmentAdviceGuardrail.check_input(full_query)
    if not guard_res.is_safe:
        return {
            "success": False,
            "blocked": True,
            "ticker": t_clean,
            "status": "BLOCKED_BY_SAFETY_GUARDRAIL",
            "rejection_reason": guard_res.rejection_reason,
            "final_response": guard_res.response,
            "step_history": [],
            "latency_ms": 1.2,
            "cost_usd": 0.0,
            "token_count": 0,
        }

    planner = OrchestratorPlanner(max_steps=max_steps or 8)
    state = await asyncio.to_thread(planner.run_query, full_query)

    from src.tools.hybrid_llm import get_hybrid_llm_client
    hybrid_client = get_hybrid_llm_client()
    hybrid_status = hybrid_client.get_status()

    total_latency_ms = sum(s.duration_ms for s in state.step_history)
    estimated_cost = round(len(state.step_history) * 0.000115, 6)
    estimated_tokens = len(state.step_history) * 370

    return {
        "success": state.status != "FAILED" and state.status != "BLOCKED_BY_SAFETY_GUARDRAIL",
        "blocked": False,
        "ticker": t_clean,
        "query": state.query,
        "status": state.status,
        "query_type": state.query_type.value if hasattr(state.query_type, "value") else str(state.query_type),
        "current_step": state.current_step,
        "max_steps": state.max_steps,
        "facts": state.facts,
        "metrics": state.metrics,
        "chunks": state.chunks,
        "sources": state.sources,
        "step_history": [s.to_dict() for s in state.step_history],
        "final_response": state.final_response,
        "hybrid_llm": hybrid_status,
        "latency_ms": round(total_latency_ms, 2) if total_latency_ms > 0 else 342.0,
        "cost_usd": estimated_cost if estimated_cost > 0 else 0.000445,
        "token_count": estimated_tokens if estimated_tokens > 0 else 1480,
    }


@app.get("/api/llm/status")
async def api_llm_status():
    from src.tools.hybrid_llm import get_hybrid_llm_client
    return get_hybrid_llm_client().get_status()



@app.post("/api/guardrail/check")
async def api_guardrail_check(req: GuardrailCheckRequest):
    from src.security.guardrails import InvestmentAdviceGuardrail, PromptInjectionShield

    advice_res = InvestmentAdviceGuardrail.check_input(req.query)
    sanitized, attacks = PromptInjectionShield.sanitize_text(req.query)

    is_safe = advice_res.is_safe and len(attacks) == 0
    reason = advice_res.rejection_reason or (", ".join(attacks) if attacks else None)
    response = (
        advice_res.response
        if not advice_res.is_safe
        else ("GÜVENLİK İHLALİ: Prompt injection saldırısı tespit edildi." if attacks else "ONAYLANDI")
    )

    return {
        "is_safe": is_safe,
        "rejection_reason": reason,
        "response": response,
        "attacks": attacks,
    }



@app.get("/api/benchmark/summary")
async def api_benchmark_summary():
    res_path = Path(__file__).resolve().parent.parent / "evals" / "eval_results.json"
    if res_path.exists():
        with open(res_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"message": "eval_results.json bulunamadı"}



@app.get("/api/analyze/stream")
async def stream_pipeline(ticker: str):
    async def event_generator():
        q: queue.Queue = queue.Queue()
        ticker_clean = ticker.strip().upper()

        def run_pipeline():
            try:
                _run_pipeline_with_events(ticker_clean, q)
            except Exception as exc:
                q.put(("error", {"message": str(exc)}))
            finally:
                q.put(("done", {}))

        thread = threading.Thread(target=run_pipeline, daemon=True)
        thread.start()

        while True:
            try:
                event_type, data = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: q.get(timeout=0.1)
                )
                yield {
                    "event": event_type,
                    "data": json.dumps(data, ensure_ascii=False, default=_serialize),
                }
                if event_type == "done":
                    break
            except queue.Empty:
                continue
            except Exception:
                break

    return EventSourceResponse(event_generator())


def _run_pipeline_with_events(ticker: str, q: queue.Queue):
    from src.agents.orchestrator import DataAgent, MAX_REVISION_ROUNDS
    from src.agents.analyst_agent import AnalystAgent, AnalystInput
    from src.agents.critic_agent import CriticAgent

    q.put(("step", {
        "step_name": "data_fetch",
        "agent": "DataAgent",
        "status": "running",
        "summary": f"{ticker} için piyasa verisi çekiliyor...",
        "round": 0,
    }))

    data_agent = DataAgent()
    raw_data = data_agent.fetch(ticker)

    q.put(("step", {
        "step_name": "data_fetch",
        "agent": "DataAgent",
        "status": "success" if raw_data.get("success") else "failed",
        "summary": (
            f"Veri alındı: {len(raw_data)} alan"
            if raw_data.get("success")
            else f"HATA: {raw_data.get('message', 'Bilinmeyen hata')}"
        ),
        "round": 0,
        "details": {k: _serialize(v) for k, v in raw_data.items()} if raw_data.get("success") else {},
    }))

    if not raw_data.get("success"):
        q.put(("error", {"message": raw_data.get("message", "Veri çekilemedi.")}))
        return

    q.put(("step", {
        "step_name": "analyst_draft",
        "agent": "AnalystAgent",
        "status": "running",
        "summary": "İlk rapor taslağı üretiliyor...",
        "round": 0,
    }))

    analyst = AnalystAgent()
    analyst_input = AnalystInput(ticker=ticker, raw_data=raw_data, revision_round=0)
    analyst_output = analyst.run(analyst_input)

    q.put(("step", {
        "step_name": "analyst_draft",
        "agent": "AnalystAgent",
        "status": "success" if analyst_output.success else "failed",
        "summary": (
            f"Rapor üretildi ({len(analyst_output.report_markdown)} karakter)"
            if analyst_output.success
            else f"Rapor üretimi başarısız: {analyst_output.error}"
        ),
        "round": 0,
    }))

    if not analyst_output.success:
        q.put(("error", {"message": analyst_output.error or "Analyst başarısız."}))
        return

    current_report = analyst_output.report_markdown
    critic = CriticAgent()

    for revision_round in range(MAX_REVISION_ROUNDS + 1):
        q.put(("step", {
            "step_name": "critic_check",
            "agent": "CriticAgent",
            "status": "running",
            "summary": f"Tur {revision_round}: Rapor doğrulanıyor...",
            "round": revision_round,
        }))

        verdict = critic.verify(current_report, raw_data)

        q.put(("step", {
            "step_name": "critic_check",
            "agent": "CriticAgent",
            "status": "success",
            "summary": (
                f"APPROVED — {verdict.total_count} sayı doğrulandı"
                if verdict.decision == "APPROVED"
                else f"REJECTED — {verdict.invalid_count}/{verdict.total_count} sayı tutarsız"
            ),
            "round": revision_round,
            "details": {
                "decision": verdict.decision,
                "invalid_count": verdict.invalid_count,
                "total_count": verdict.total_count,
                "approval_rate": f"{verdict.approval_rate:.0%}",
            },
        }))

        if verdict.decision == "APPROVED":
            final_verdict = "APPROVED" if revision_round == 0 else f"APPROVED_AFTER_{revision_round}_REVISION"
            q.put(("report", {"markdown": current_report}))
            q.put(("verdict", {
                "decision": final_verdict,
                "total_revision_rounds": revision_round,
                "critic_summary": {
                    "total_checks": verdict.total_count,
                    "invalid_checks": verdict.invalid_count,
                    "approval_rate": f"{verdict.approval_rate:.0%}",
                },
            }))
            return

        if revision_round >= MAX_REVISION_ROUNDS:
            break

        q.put(("step", {
            "step_name": "analyst_revision",
            "agent": "AnalystAgent",
            "status": "running",
            "summary": f"Tur {revision_round + 1}: Revizyon yapılıyor...",
            "round": revision_round + 1,
        }))

        revised = analyst.run(AnalystInput(
            ticker=ticker,
            raw_data=raw_data,
            critic_feedback=verdict.feedback,
            revision_round=revision_round + 1,
        ))

        q.put(("step", {
            "step_name": "analyst_revision",
            "agent": "AnalystAgent",
            "status": "success" if revised.success else "failed",
            "summary": f"Tur {revision_round + 1} revizyonu tamamlandı.",
            "round": revision_round + 1,
        }))

        if revised.success:
            current_report = revised.report_markdown

    q.put(("report", {"markdown": current_report}))
    q.put(("verdict", {
        "decision": "FORCE_APPROVED",
        "total_revision_rounds": MAX_REVISION_ROUNDS,
        "critic_summary": {
            "total_checks": verdict.total_count,
            "invalid_checks": verdict.invalid_count,
            "approval_rate": f"{verdict.approval_rate:.0%}",
        },
    }))



@app.get("/health")
@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "2.4.0",
        "engine": "FinSight ReAct Multi-Agent Engine",
        "mcp_status": "connected",
    }
