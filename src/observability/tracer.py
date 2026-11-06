
from __future__ import annotations

import contextvars
import dataclasses
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("finsight_tracer")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)


class SpanKind(str, Enum):
    CHAIN = "chain"
    AGENT = "agent"
    TOOL = "tool"
    LLM = "llm"
    GUARDRAIL = "guardrail"
    EVAL = "eval"


class SpanStatus(str, Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    BLOCKED = "BLOCKED"                                            


PRICING_REGISTRY = {
    "gemini-1.5-flash": {"input_per_m": 0.15, "output_per_m": 0.60},
    "gemini-1.5-pro": {"input_per_m": 3.50, "output_per_m": 10.50},
    "gpt-4o-mini": {"input_per_m": 0.15, "output_per_m": 0.60},
    "gpt-4o": {"input_per_m": 5.00, "output_per_m": 15.00},
    "default": {"input_per_m": 0.15, "output_per_m": 0.60},
}


@dataclasses.dataclass
class Span:
    trace_id: str
    span_id: str
    name: str
    span_kind: SpanKind
    parent_span_id: Optional[str] = None
    start_time_iso: str = ""
    end_time_iso: str = ""
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    status: SpanStatus = SpanStatus.SUCCESS
    input_data: Any = None
    output_data: Any = None
    attributes: Dict[str, Any] = dataclasses.field(default_factory=dict)
    error_message: Optional[str] = None

    def finish(
        self,
        output_data: Any = None,
        status: SpanStatus = SpanStatus.SUCCESS,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model_name: str = "gemini-1.5-flash",
        error: Optional[Exception] = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        self.end_time_iso = now.isoformat()
        if hasattr(self, "_start_ts"):
            self.latency_ms = round((time.perf_counter() - self._start_ts) * 1000, 2)
        
        self.output_data = output_data
        self.status = status
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = input_tokens + output_tokens

        rates = PRICING_REGISTRY.get(model_name, PRICING_REGISTRY["default"])
        input_cost = (input_tokens / 1_000_000.0) * rates["input_per_m"]
        output_cost = (output_tokens / 1_000_000.0) * rates["output_per_m"]
        self.cost_usd = round(input_cost + output_cost, 6)

        if error:
            self.status = SpanStatus.ERROR
            self.error_message = f"{type(error).__name__}: {str(error)}"

    def to_dict(self) -> Dict[str, Any]:
        data = dataclasses.asdict(self)
        data["span_kind"] = self.span_kind.value if isinstance(self.span_kind, SpanKind) else self.span_kind
        data["status"] = self.status.value if isinstance(self.status, SpanStatus) else self.status
        if hasattr(self, "_start_ts"):
            data.pop("_start_ts", None)
        return data

    def to_phoenix_format(self) -> Dict[str, Any]:
        return {
            "context": {
                "trace_id": self.trace_id,
                "span_id": self.span_id,
                "parent_id": self.parent_span_id,
            },
            "name": self.name,
            "span_kind": self.span_kind.value.upper(),
            "start_time": self.start_time_iso,
            "end_time": self.end_time_iso,
            "status_code": "OK" if self.status == SpanStatus.SUCCESS else "ERROR",
            "attributes": {
                "openinference.span.kind": self.span_kind.value,
                "llm.token_count.prompt": self.input_tokens,
                "llm.token_count.completion": self.output_tokens,
                "llm.token_count.total": self.total_tokens,
                "llm.cost.total_usd": self.cost_usd,
                "latency_ms": self.latency_ms,
                "input.value": str(self.input_data)[:2000] if self.input_data is not None else None,
                "output.value": str(self.output_data)[:2000] if self.output_data is not None else None,
                **self.attributes,
            },
        }

    def to_langfuse_format(self) -> Dict[str, Any]:
        return {
            "traceId": self.trace_id,
            "id": self.span_id,
            "parentObservationId": self.parent_span_id,
            "name": self.name,
            "type": self.span_kind.value.upper(),
            "startTime": self.start_time_iso,
            "endTime": self.end_time_iso,
            "metadata": self.attributes,
            "input": self.input_data,
            "output": self.output_data,
            "usage": {
                "promptTokens": self.input_tokens,
                "completionTokens": self.output_tokens,
                "totalTokens": self.total_tokens,
                "totalCost": self.cost_usd,
            },
            "level": "ERROR" if self.status == SpanStatus.ERROR else ("WARNING" if self.status == SpanStatus.BLOCKED else "DEFAULT"),
            "statusMessage": self.error_message or self.status.value,
        }


_active_span_stack: contextvars.ContextVar[List[str]] = contextvars.ContextVar(
    "_active_span_stack", default=[]
)
_current_trace_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "_current_trace_id", default=None
)


class SpanContextManager:

    def __init__(self, tracer: FinSightTracer, span: Span):
        self.tracer = tracer
        self.span = span

    def __enter__(self) -> Span:
        stack = list(_active_span_stack.get())
        stack.append(self.span.span_id)
        _active_span_stack.set(stack)
        return self.span

    def __exit__(self, exc_type, exc_val, exc_tb):
        stack = list(_active_span_stack.get())
        if stack and stack[-1] == self.span.span_id:
            stack.pop()
        _active_span_stack.set(stack)

        if exc_type is not None:
            self.span.finish(status=SpanStatus.ERROR, error=exc_val)
        elif not self.span.end_time_iso:
            self.span.finish(status=SpanStatus.SUCCESS)

        self.tracer.record_span(self.span)
        return False                                          


class FinSightTracer:

    def __init__(self, default_trace_id: Optional[str] = None):
        self._default_trace_id = default_trace_id or str(uuid.uuid4())
        self.spans: List[Span] = []

    def start_trace(self, trace_id: Optional[str] = None) -> str:
        tid = trace_id or f"trace_{uuid.uuid4().hex[:12]}"
        _current_trace_id.set(tid)
        _active_span_stack.set([])
        return tid

    def get_current_trace_id(self) -> str:
        tid = _current_trace_id.get()
        return tid if tid else self._default_trace_id

    def trace_span(
        self,
        name: str,
        span_kind: SpanKind = SpanKind.TOOL,
        parent_span_id: Optional[str] = None,
        input_data: Any = None,
        attributes: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> SpanContextManager:
        tid = trace_id or self.get_current_trace_id()
        stack = _active_span_stack.get()
        actual_parent_id = parent_span_id if parent_span_id is not None else (stack[-1] if stack else None)

        now = datetime.now(timezone.utc)
        span_id = f"span_{uuid.uuid4().hex[:10]}"

        span = Span(
            trace_id=tid,
            span_id=span_id,
            name=name,
            span_kind=span_kind,
            parent_span_id=actual_parent_id,
            start_time_iso=now.isoformat(),
            input_data=input_data,
            attributes=attributes or {},
        )
        setattr(span, "_start_ts", time.perf_counter())
        return SpanContextManager(self, span)

    def record_span(self, span: Span) -> None:
        self.spans.append(span)

    def export_jsonl(self, filepath: str) -> int:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            for s in self.spans:
                f.write(json.dumps(s.to_dict(), ensure_ascii=False) + "\n")
        logger.info(f"Observability: {len(self.spans)} span kaydedildi -> {filepath}")
        return len(self.spans)

    def export_phoenix_jsonl(self, filepath: str) -> int:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            for s in self.spans:
                f.write(json.dumps(s.to_phoenix_format(), ensure_ascii=False) + "\n")
        return len(self.spans)

    def export_langfuse_jsonl(self, filepath: str) -> int:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            for s in self.spans:
                f.write(json.dumps(s.to_langfuse_format(), ensure_ascii=False) + "\n")
        return len(self.spans)

    def get_summary(self) -> Dict[str, Any]:
        total_spans = len(self.spans)
        total_latency = sum(s.latency_ms for s in self.spans)
        total_input_tokens = sum(s.input_tokens for s in self.spans)
        total_output_tokens = sum(s.output_tokens for s in self.spans)
        total_tokens = sum(s.total_tokens for s in self.spans)
        total_cost_usd = sum(s.cost_usd for s in self.spans)

        by_kind: Dict[str, Dict[str, Any]] = {}
        for s in self.spans:
            kind_str = s.span_kind.value if isinstance(s.span_kind, SpanKind) else s.span_kind
            if kind_str not in by_kind:
                by_kind[kind_str] = {
                    "count": 0,
                    "total_latency_ms": 0.0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                }
            by_kind[kind_str]["count"] += 1
            by_kind[kind_str]["total_latency_ms"] += s.latency_ms
            by_kind[kind_str]["total_tokens"] += s.total_tokens
            by_kind[kind_str]["cost_usd"] += s.cost_usd

        for k, v in by_kind.items():
            cnt = v["count"]
            v["avg_latency_ms"] = round(v["total_latency_ms"] / cnt, 2) if cnt > 0 else 0.0
            v["cost_usd"] = round(v["cost_usd"], 6)

        return {
            "total_spans": total_spans,
            "avg_latency_ms": round(total_latency / total_spans, 2) if total_spans > 0 else 0.0,
            "total_tokens": total_tokens,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_cost_usd": round(total_cost_usd, 6),
            "by_kind": by_kind,
        }

    def clear(self) -> None:
        self.spans.clear()


_global_tracer: Optional[FinSightTracer] = None


def get_tracer() -> FinSightTracer:
    global _global_tracer
    if _global_tracer is None:
        _global_tracer = FinSightTracer()
    return _global_tracer


def reset_tracer() -> FinSightTracer:
    global _global_tracer
    _global_tracer = FinSightTracer()
    return _global_tracer

