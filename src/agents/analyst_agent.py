
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from google import genai

from src.config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)


ANALYST_SYSTEM_PROMPT = """\
Sen FinSight'ın Analist Agent'ısın.

Sana sağlanan HAM VERİ JSON'ını kullanarak profesyonel bir finansal analiz raporu yaz.
Hiçbir zaman kendi başına veri üretme veya tahmin etme — yalnızca sağlanan veriyi kullan.

Raporunu aşağıdaki Markdown yapısında sun:


| Gösterge | Değer | Kaynak |
|----------|-------|--------|
| (her satırda bir metrik) | (hesaplanan değer) | (ham_veri alanı) |

(F/K, PD/DD, ROE gibi oranlar için yorumlar — hesaplamalarını göster)

(SWOT veya kısa değerlendirme)

1. Raporda yazdığın HER sayısal değer için "Kaynak" sütununda ham_veri alanını belirt.
2. Ham veride olmayan hiçbir sayısal iddiada bulunma. Bilmiyorsan "Veri mevcut değil" yaz.
3. Hesaplamalarını şeffaf göster: örn. F/K = 285.50 / 42.30 = 6.75
4. Para birimi ve ölçek birimini daima yaz (TRY, %, x, Milyar TRY).
5. Türkçe yaz.
"""



@dataclass
class AnalystInput:
    ticker: str
    raw_data: dict[str, Any]                                                 
    critic_feedback: str | None = None                                                          
    revision_round: int = 0                                                    


@dataclass
class AnalystOutput:
    ticker: str
    report_markdown: str                                                  
    revision_round: int
    raw_data_used: dict[str, Any]                                      
    success: bool = True
    error: str | None = None



class AnalystAgent:

    def __init__(self, hybrid_client: Optional[Any] = None):
        from src.tools.hybrid_llm import get_hybrid_llm_client
        self._hybrid_client = hybrid_client or get_hybrid_llm_client()
        self._client = getattr(self._hybrid_client, "gemini_client", None)
        self._model = GEMINI_MODEL

    def run(self, analyst_input: AnalystInput) -> AnalystOutput:
        prompt = self._build_prompt(analyst_input)

        logger.info(
            "[AnalystAgent] Hibrit rapor üretiliyor | Ticker: %s | Revision: %d",
            analyst_input.ticker,
            analyst_input.revision_round,
        )

        try:
            task_type = "draft" if analyst_input.revision_round == 0 else "synthesis"
            resp = self._hybrid_client.generate(
                prompt=prompt,
                task_type=task_type,
                system_prompt=ANALYST_SYSTEM_PROMPT,
            )

            report = resp.text.strip() if resp and resp.text else ""

            return AnalystOutput(
                ticker         = analyst_input.ticker,
                report_markdown= report,
                revision_round = analyst_input.revision_round,
                raw_data_used  = analyst_input.raw_data,
                success        = bool(report),
                error          = resp.error if not report else None,
            )

        except Exception as exc:
            logger.error("[AnalystAgent] LLM hatası: %s", exc)
            return AnalystOutput(
                ticker         = analyst_input.ticker,
                report_markdown= "",
                revision_round = analyst_input.revision_round,
                raw_data_used  = analyst_input.raw_data,
                success        = False,
                error          = str(exc),
            )


    def _build_prompt(self, inp: AnalystInput) -> str:
        raw_json = json.dumps(inp.raw_data, ensure_ascii=False, indent=2, default=str)

        base = (
            f"{ANALYST_SYSTEM_PROMPT}\n\n"
            f"## Analiz Edilecek Hisse\n"
            f"Ticker: **{inp.ticker}**\n\n"
            f"## Ham Veri (Bu verinin DIŞINA çıkma)\n"
            f"```json\n{raw_json}\n```\n"
        )

        if inp.critic_feedback:
            base += (
                f"\n\n## Critic'in Revizyon Talebi (Tur {inp.revision_round})\n"
                f"Aşağıdaki sorunları gidererek raporu yeniden yaz:\n\n"
                f"{inp.critic_feedback}\n\n"
                "⚠️ Yalnızca belirtilen sorunları düzelt. Doğru olan kısımları değiştirme."
            )
        else:
            base += "\n\nRaporu şimdi yaz:"

        return base
