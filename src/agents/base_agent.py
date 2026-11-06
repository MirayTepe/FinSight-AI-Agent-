
import re
import json
import hashlib
import logging
import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from google import genai
from google.genai import types as genai_types

from src.config import GEMINI_API_KEY, GEMINI_MODEL, MAX_AGENT_STEPS

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    name: str
    description: str
    args_schema: str                                                
    func: Callable[[dict], Any]

    def to_prompt_block(self) -> str:
        return (
            f"- **{self.name}**\n"
            f"  Açıklama : {self.description}\n"
            f"  Argümanlar: {self.args_schema}\n"
        )



@dataclass
class TraceStep:
    step_index: int
    thought: str
    action: str
    action_input: dict | str                                                
    observation: str
    timestamp: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    is_final: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "step_index"   : self.step_index,
            "timestamp"    : self.timestamp,
            "thought"      : self.thought,
            "action"       : self.action,
            "action_input" : self.action_input,
            "observation"  : self.observation,
            "is_final"     : self.is_final,
            "error"        : self.error,
        }


@dataclass
class AgentRunResult:
    final_answer: str
    trace: list[TraceStep]
    total_steps: int
    stopped_by: str                                                                 
    query: str

    def to_dict(self) -> dict:
        return {
            "query"        : self.query,
            "final_answer" : self.final_answer,
            "total_steps"  : self.total_steps,
            "stopped_by"   : self.stopped_by,
            "trace"        : [s.to_dict() for s in self.trace],
        }



REACT_SYSTEM_PROMPT = """\
Sen FinSight adlı otonom bir finansal analiz asistanısın.
Kullanıcının sorusunu yanıtlamak için adım adım ReAct (Reasoning + Acting) döngüsünü kullanmalısın.

{tool_descriptions}

Her yanıtın TAM OLARAK şu üç satırı içermeli; satır sırası ve etiketler değişmemeli:

Thought: <Durumu analiz et. Hangi bilgi eksik? Hangi aracı kullanmalısın? Neden?>
Action: <Araç adı — yukarıdaki listeden biri VEYA "Final Answer">
Action Input: <Araç için JSON argümanlar VEYA "Final Answer" ise kullanıcıya sunulacak nihai metin>

1. Her adımda YALNIZca tek bir araç çağır.
2. "Action Input" her zaman geçerli JSON olmalı (Final Answer hariç).
3. Yeterli bilgiye ulaştığında Action: Final Answer kullan.
4. Aynı araç + aynı argümanla tekrar aramayı KESINLIKLE YAPMA.
5. Türkçe düşün ve yanıtla.

Thought: Kullanıcı THYAO hissesinin F/K oranını sordu. Güncel fiyat ve EPS verisine ihtiyacım var.
Action: fetch_market_data
Action Input: {{"ticker_symbol": "THYAO.IS"}}
"""



class ReActParser:

    _THOUGHT_RE = re.compile(
        r"Thought\s*:\s*(.+?)(?=\nAction\s*:|\Z)", re.DOTALL | re.IGNORECASE
    )
    _ACTION_RE = re.compile(
        r"Action\s*:\s*(.+?)(?=\nAction Input\s*:|\Z)", re.DOTALL | re.IGNORECASE
    )
    _INPUT_RE = re.compile(
        r"Action Input\s*:\s*(.+)", re.DOTALL | re.IGNORECASE
    )

    @classmethod
    def parse(cls, raw: str) -> dict:
        result = {
            "thought"      : "",
            "action"       : "",
            "action_input" : {},
            "parse_error"  : None,
        }

        m = cls._THOUGHT_RE.search(raw)
        result["thought"] = m.group(1).strip() if m else cls._fallback_line(raw, "thought")

        m = cls._ACTION_RE.search(raw)
        action_raw = m.group(1).strip() if m else cls._fallback_line(raw, "action")
        result["action"] = action_raw.split("\n")[0].strip()                      

        m = cls._INPUT_RE.search(raw)
        if m:
            input_raw = m.group(1).strip()
            result["action_input"] = cls._safe_json(input_raw)
        else:
            result["parse_error"] = "Action Input satırı bulunamadı."

        return result


    @staticmethod
    def _fallback_line(text: str, label: str) -> str:
        for line in text.splitlines():
            if line.lower().startswith(label.lower()):
                return line.split(":", 1)[-1].strip()
        return ""

    @staticmethod
    def _safe_json(text: str) -> dict | str:
        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block:
            text = code_block.group(1)

        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            try:
                return json.loads(text.replace("'", '"'))
            except Exception:
                return text                            



class BaseReActAgent(ABC):

    MAX_STEPS: int = MAX_AGENT_STEPS                                                        
    LOOP_REPEAT_THRESHOLD: int = 2                                                      

    def __init__(self, hybrid_client: Optional[Any] = None):
        from src.tools.hybrid_llm import get_hybrid_llm_client
        self._hybrid_client = hybrid_client or get_hybrid_llm_client()
        self._client = getattr(self._hybrid_client, "gemini_client", None)
        self._model_name = GEMINI_MODEL
        self._tools: dict[str, ToolDefinition] = {}
        self._build_tools()


    @abstractmethod
    def _build_tools(self) -> None:
        ...

    def _register_tool(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool


    def _build_system_prompt(self) -> str:
        tool_block = "\n".join(t.to_prompt_block() for t in self._tools.values())
        return REACT_SYSTEM_PROMPT.format(tool_descriptions=tool_block)


    def _execute_tool(self, action: str, action_input: dict | str) -> str:
        tool = self._tools.get(action)
        if not tool:
            return f"[HATA] '{action}' adlı araç bulunamadı. Mevcut araçlar: {list(self._tools.keys())}"

        try:
            if isinstance(action_input, str):
                try:
                    action_input = json.loads(action_input)
                except Exception:
                    action_input = {"raw_input": action_input}

            raw_result = tool.func(action_input) if isinstance(action_input, dict) else tool.func({})

            return json.dumps(raw_result, ensure_ascii=False, default=str, indent=2)

        except Exception as exc:
            logger.exception("Tool execution error: %s", action)
            return f"[HATA] Araç çalıştırılırken istisna oluştu: {exc}"


    @staticmethod
    def _step_fingerprint(action: str, action_input: dict | str) -> str:
        payload = f"{action}::{json.dumps(action_input, sort_keys=True, default=str)}"
        return hashlib.md5(payload.encode()).hexdigest()

    def _build_loop_intervention(self, repeated_action: str, repeated_input: dict) -> str:
        return (
            f"\n\n[SİSTEM UYARISI] '{repeated_action}' aracını aynı argümanlarla "
            f"({json.dumps(repeated_input, default=str)}) zaten çağırdın ve sonucu aldın. "
            "Aynı adımı TEKRARLAMA. Farklı bir araç kullan veya mevcut bilgilerle "
            "Final Answer üret."
        )


    def run(self, query: str) -> AgentRunResult:
        system_prompt = self._build_system_prompt()
        conversation_history: list[str] = []
        trace: list[TraceStep] = []
        seen_fingerprints: dict[str, int] = {}                                  
        stopped_by = "max_steps"
        final_answer = ""

        user_turn = f"Kullanıcı Sorusu: {query}"
        conversation_history.append(f"[USER]\n{user_turn}")

        for step_idx in range(1, self.MAX_STEPS + 1):
            logger.info("[Step %d/%d] Calling LLM...", step_idx, self.MAX_STEPS)

            full_prompt = system_prompt + "\n\n" + "\n\n".join(conversation_history)
            try:
                resp = self._hybrid_client.generate(
                    prompt=full_prompt,
                    task_type="reasoning",
                    temperature=0.2,
                )
                raw_llm_output = resp.text if resp and resp.text else ""
                if not raw_llm_output:
                    raise RuntimeError("LLM boş yanıt döndürdü")
            except Exception as exc:
                logger.error("LLM API error at step %d: %s", step_idx, exc)
                raw_llm_output = (
                    f"Thought: LLM API hatası oluştu.\n"
                    f"Action: Final Answer\n"
                    f"Action Input: Üzgünüm, şu an hizmet veremiyorum. Hata: {exc}"
                )

            logger.debug("[Step %d] Raw LLM output:\n%s", step_idx, raw_llm_output)

            parsed = ReActParser.parse(raw_llm_output)
            thought       = parsed["thought"]
            action        = parsed["action"]
            action_input  = parsed["action_input"]
            parse_error   = parsed.get("parse_error")

            is_final = action.strip().lower() in ("final answer", "final_answer")

            if is_final:
                final_answer = (
                    action_input
                    if isinstance(action_input, str)
                    else json.dumps(action_input, ensure_ascii=False)
                )
                trace.append(TraceStep(
                    step_index   = step_idx,
                    thought      = thought,
                    action       = action,
                    action_input = action_input,
                    observation  = "[Final Answer üretildi]",
                    is_final     = True,
                ))
                stopped_by = "final_answer"
                break

            fp = self._step_fingerprint(action, action_input)
            seen_fingerprints[fp] = seen_fingerprints.get(fp, 0) + 1

            loop_intervention = ""
            if seen_fingerprints[fp] >= self.LOOP_REPEAT_THRESHOLD:
                logger.warning(
                    "[Step %d] Loop detected: '%s' repeated %d times.",
                    step_idx, action, seen_fingerprints[fp]
                )
                loop_intervention = self._build_loop_intervention(action, action_input)
                stopped_by = "loop_guard"
                conversation_history.append(f"[SYSTEM INTERVENTION]{loop_intervention}")
                trace.append(TraceStep(
                    step_index   = step_idx,
                    thought      = thought,
                    action       = action,
                    action_input = action_input,
                    observation  = f"[LOOP GUARD] Tekrar algılandı: {loop_intervention}",
                    error        = "loop_detected",
                ))
                continue                                          

            observation = self._execute_tool(action, action_input)

            trace.append(TraceStep(
                step_index   = step_idx,
                thought      = thought,
                action       = action,
                action_input = action_input,
                observation  = observation,
                error        = parse_error,
            ))

            conversation_history.append(
                f"[ASSISTANT — Step {step_idx}]\n"
                f"Thought: {thought}\n"
                f"Action: {action}\n"
                f"Action Input: {json.dumps(action_input, ensure_ascii=False, default=str)}\n"
                f"Observation: {observation}"
            )

        if not final_answer:
            final_answer = (
                f"Maksimum adım sayısına ({self.MAX_STEPS}) ulaşıldı. "
                "Mevcut bilgilerle kesin bir yanıt üretilemedi. "
                "Lütfen soruyu daha spesifik biçimde tekrar sorun."
            )

        return AgentRunResult(
            final_answer = final_answer,
            trace        = trace,
            total_steps  = len(trace),
            stopped_by   = stopped_by,
            query        = query,
        )
