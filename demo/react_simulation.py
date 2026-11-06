
import json
import sys
import os

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decimal import Decimal
from src.agents.base_agent import (
    BaseReActAgent, ToolDefinition, ReActParser,
    TraceStep, AgentRunResult
)


def mock_fetch_market_data(args: dict) -> dict:
    ticker = args.get("ticker_symbol", "UNKNOWN")
    if "THYAO" in ticker.upper():
        return {
            "success"            : True,
            "ticker"             : "THYAO.IS",
            "currency"           : "TRY",
            "current_price"      : "285.50",                                    
            "eps"                : "42.30",
            "book_value_per_share": "180.75",
            "market_cap"         : 240000000000,
        }
    return {"success": False, "error_code": "TICKER_NOT_FOUND", "message": f"{ticker} bulunamadı."}


def mock_calculate_pe(args: dict) -> dict:
    price = float(args.get("stock_price", 0))
    eps   = float(args.get("eps", 1))
    if eps <= 0:
        return {"success": False, "error_code": "NEGATIVE_EPS", "message": "EPS sıfır veya negatif."}
    return {"success": True, "pe_ratio": round(price / eps, 2)}



class MockLLM:
    _responses = [
        """\
Thought: Kullanıcı THYAO hissesinin F/K oranını sordu. Önce güncel fiyat ve EPS verisini çekmeliyim.
Action: fetch_market_data
Action Input: {"ticker_symbol": "THYAO.IS"}
""",
        """\
Thought: Piyasa verisini aldım. Fiyat=285.50 TRY, EPS=42.30 TRY. Şimdi F/K oranını hesaplamalıyım.
Action: calculate_pe_ratio
Action Input: {"stock_price": 285.50, "eps": 42.30}
""",
        """\
Thought: F/K oranı hesaplandı: 6.75. Artık kullanıcıya yanıt verebilirim.
Action: Final Answer
Action Input: THYAO (Türk Hava Yolları) hissesinin güncel F/K (Fiyat/Kazanç) oranı **6.75**'tir.

[+] Detaylar:
- Güncel Fiyat: 285,50 TRY
- Hisse Başına Kâr (EPS): 42,30 TRY
- F/K Oranı: 285,50 ÷ 42,30 = **6,75**

Bu oran, havacılık sektörünün küresel ortalamasının (12-18x) oldukça altındadır. Bu durum hissenin değer altında fiyatlandırıldığına veya piyasanın düşük büyüme beklentisi taşıdığına işaret edebilir.
""",
    ]
    _idx = 0

    class _Models:
        def __init__(self, responses, idx_ref):
            self._responses = responses
            self._idx_ref = idx_ref

        def generate_content(self, model: str, contents: str):
            resp = self._responses[self._idx_ref[0] % len(self._responses)]
            self._idx_ref[0] += 1

            class _FakeResponse:
                text = resp
            return _FakeResponse()

    def __init__(self):
        self._idx_ref = [0]
        self.models = MockLLM._Models(self._responses, self._idx_ref)



class SimulationAgent(BaseReActAgent):

    def _build_tools(self) -> None:
        self._register_tool(ToolDefinition(
            name        = "fetch_market_data",
            description = "Hisse senedi için güncel fiyat, EPS ve defter değeri çeker.",
            args_schema = '{"ticker_symbol": "THYAO.IS"}',
            func        = mock_fetch_market_data,
        ))
        self._register_tool(ToolDefinition(
            name        = "calculate_pe_ratio",
            description = "Hisse fiyatı ve EPS kullanarak F/K (P/E) oranını hesaplar.",
            args_schema = '{"stock_price": 285.50, "eps": 42.30}',
            func        = mock_calculate_pe,
        ))

    def run(self, query: str) -> AgentRunResult:
        self._client = MockLLM()
        return super().run(query)



def render_trace(result: AgentRunResult) -> None:
    BOLD  = "\033[1m"
    CYAN  = "\033[96m"
    GREEN = "\033[92m"
    YELLOW= "\033[93m"
    RED   = "\033[91m"
    RESET = "\033[0m"

    print(f"\n{'='*70}")
    print(f"{BOLD}[FinSight] ReAct Simulasyonu{RESET}")
    print(f"{'='*70}")
    print(f"{BOLD}Soru:{RESET} {result.query}")
    print(f"{BOLD}Durdurulma Nedeni:{RESET} {result.stopped_by}")
    print(f"{BOLD}Toplam Adim:{RESET} {result.total_steps}")
    print(f"{'='*70}\n")

    for step in result.trace:
        status = f"{GREEN}[FINAL]{RESET}" if step.is_final else (
                 f"{RED}[LOOP GUARD]{RESET}" if step.error == "loop_detected" else
                 f"{CYAN}[STEP {step.step_index}]{RESET}")

        print(f"{'─'*60}")
        print(f"{status}  [{step.timestamp}]")
        print(f"\n{YELLOW}Thought:{RESET}\n  {step.thought}")
        print(f"\n{YELLOW}Action:{RESET}  {step.action}")
        print(f"\n{YELLOW}Input:{RESET}\n  {json.dumps(step.action_input, ensure_ascii=False, indent=4)}")
        print(f"\n{YELLOW}Observation:{RESET}")
        obs = step.observation
        try:
            parsed_obs = json.loads(obs)
            obs = json.dumps(parsed_obs, ensure_ascii=False, indent=4)
        except Exception:
            pass
        for line in obs.splitlines():
            print(f"  {line}")
        print()

    print(f"{'='*70}")
    print(f"{BOLD}{GREEN}[FINAL ANSWER]:{RESET}")
    print(f"\n{result.final_answer}")
    print(f"{'='*70}\n")

    print(f"{BOLD}[JSON Trace - UI'ye Aktarilabilir]:{RESET}")
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    agent = SimulationAgent()
    result = agent.run("THYAO hissesinin F/K oranı nedir?")
    render_trace(result)
