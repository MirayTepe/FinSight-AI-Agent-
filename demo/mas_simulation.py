
from __future__ import annotations

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

from src.agents.analyst_agent import AnalystAgent, AnalystInput, AnalystOutput
from src.agents.critic_agent import CriticAgent, CriticVerdict, ClaimCheck
from src.agents.orchestrator import DataAgent, Orchestrator, OrchestratorResult, PipelineStep


MOCK_RAW_DATA = {
    "success"             : True,
    "ticker"              : "THYAO.IS",
    "currency"            : "TRY",
    "current_price"       : "285.50",
    "eps"                 : "42.30",
    "book_value_per_share": "180.75",
    "market_cap"          : 240_000_000_000,                   
    "pe_ratio_calculated" : 6.75,
    "pb_ratio_calculated" : 1.58,
}


class MockDataAgent(DataAgent):
    def fetch(self, ticker: str) -> dict:
        print(f"  [DataAgent] Mock veri döndürülüyor: {ticker}")
        return MOCK_RAW_DATA



DRAFT_REPORT_WITH_HALLUCINATION = """\

| Gösterge              | Değer       | Kaynak                  |
|-----------------------|-------------|-------------------------|
| Güncel Fiyat          | 285.50 TRY  | current_price           |
| Hisse Başına Kâr (EPS)| **55.00 TRY**   | eps (YANLIŞ - hallucination) |
| Defter Değeri/Hisse   | 180.75 TRY  | book_value_per_share    |
| Piyasa Değeri         | 240 Milyar TRY | market_cap           |

- **F/K Oranı:** 285.50 / 55.00 = **5.19x** ← (Yanlış hesap — EPS hatalı)
- **PD/DD Oranı:** 285.50 / 180.75 = **1.58x**

THYAO hissesi havacılık sektörü ortalamasının altında F/K ile işlem görmektedir.
"""

REVISED_REPORT_CORRECT = """\

| Gösterge              | Değer       | Kaynak                  |
|-----------------------|-------------|-------------------------|
| Güncel Fiyat          | 285.50 TRY  | current_price           |
| Hisse Başına Kâr (EPS)| 42.30 TRY   | eps                     |
| Defter Değeri/Hisse   | 180.75 TRY  | book_value_per_share    |
| Piyasa Değeri         | 240 Milyar TRY | market_cap           |

- **F/K Oranı:** 285.50 / 42.30 = **6.75x**
- **PD/DD Oranı:** 285.50 / 180.75 = **1.58x**

THYAO hissesi 6.75x F/K oranıyla havacılık sektörünün küresel ortalamasının (12-18x) altındadır.
"""

class MockAnalystAgent(AnalystAgent):
    _call_count = 0

    def run(self, analyst_input: AnalystInput) -> AnalystOutput:
        self._call_count += 1
        if analyst_input.revision_round == 0:
            report = DRAFT_REPORT_WITH_HALLUCINATION
            print("  [AnalystAgent] Tur 0: Hallucination içeren taslak rapor üretildi.")
        else:
            report = REVISED_REPORT_CORRECT
            print(f"  [AnalystAgent] Tur {analyst_input.revision_round}: Revize edilmiş rapor üretildi.")

        return AnalystOutput(
            ticker          = analyst_input.ticker,
            report_markdown = report,
            revision_round  = analyst_input.revision_round,
            raw_data_used   = analyst_input.raw_data,
        )



BOLD   = "\033[1m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
RESET  = "\033[0m"


def render_pipeline(result: OrchestratorResult) -> None:
    print(f"\n{'='*70}")
    print(f"{BOLD}[FinSight] Multi-Agent Pipeline Sonucu{RESET}")
    print(f"{'='*70}")
    print(f"{BOLD}Ticker       :{RESET} {result.ticker}")
    print(f"{BOLD}Nihai Karar  :{RESET} {_verdict_color(result.verdict)}{result.verdict}{RESET}")
    print(f"{BOLD}Revizyon Turu:{RESET} {result.total_revision_rounds}")
    print(f"{'='*70}\n")

    print(f"{BOLD}--- Pipeline Adimlari ---{RESET}")
    for step in result.pipeline_steps:
        icon = "[OK]" if step.status == "success" else "[FAIL]"
        color = GREEN if step.status == "success" else RED
        print(f"  {color}{icon}{RESET} [{step.agent}] {step.step_name} (tur={step.round})")
        print(f"       {step.summary}")
        if step.details:
            for k, v in step.details.items():
                print(f"       {YELLOW}{k}{RESET}: {v}")
        print()

    print(f"{BOLD}--- Critic Son Ozeti ---{RESET}")
    for k, v in result.critic_checks_summary.items():
        print(f"  {YELLOW}{k}{RESET}: {v}")

    print(f"\n{BOLD}--- Final Rapor ---{RESET}")
    print(result.final_report)

    print(f"\n{BOLD}--- JSON Pipeline Log (UI icin) ---{RESET}")
    log = result.to_dict()
    log.pop("final_report", None)                                         
    print(json.dumps(log, ensure_ascii=False, indent=2))


def _verdict_color(v: str) -> str:
    if "APPROVED" in v and "FORCE" not in v:
        return GREEN
    if "FORCE" in v:
        return YELLOW
    return RED



if __name__ == "__main__":
    print(f"\n{BOLD}FinSight Multi-Agent Simulation Basliyor...{RESET}\n")

    orchestrator = Orchestrator(
        data_agent    = MockDataAgent(),
        analyst_agent = MockAnalystAgent(),
        critic_agent  = CriticAgent(tolerance_pct=2.0),
    )

    result = orchestrator.run("THYAO.IS")
    render_pipeline(result)

