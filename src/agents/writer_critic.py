
from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("writer_critic")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


@dataclass
class NumberVerificationResult:
    raw_match: str
    claimed_value: float
    matched_reference_key: Optional[str]
    reference_value: Optional[float]
    relative_error_pct: float
    is_valid: bool
    message: str


@dataclass
class FaithfulnessVerdict:
    is_faithful: bool
    faithfulness_score: float                     
    supported_claims: List[str] = field(default_factory=list)
    unsupported_claims: List[str] = field(default_factory=list)
    critic_notes: str = ""


@dataclass
class CriticReviewResult:
    verdict: str                           
    number_check_passed: bool
    faithfulness_passed: bool
    placeholders_rendered: bool
    number_checks: List[NumberVerificationResult] = field(default_factory=list)
    faithfulness: Optional[FaithfulnessVerdict] = None
    feedback_for_writer: str = ""
    revision_round: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "number_check_passed": self.number_check_passed,
            "faithfulness_passed": self.faithfulness_passed,
            "placeholders_rendered": self.placeholders_rendered,
            "feedback_for_writer": self.feedback_for_writer,
            "revision_round": self.revision_round,
            "number_checks": [asdict(n) for n in self.number_checks],
            "faithfulness": asdict(self.faithfulness) if self.faithfulness else None,
        }


class MetricPlaceholderEngine:

    PLACEHOLDER_REGEX = re.compile(r"\{\{m:([A-Za-z0-9_\.]+)\}\}")

    @classmethod
    def extract_placeholders(cls, template_text: str) -> List[str]:
        return cls.PLACEHOLDER_REGEX.findall(template_text)

    @classmethod
    def build_reference_dict(cls, metrics_data: Dict[str, Any]) -> Dict[str, Any]:
        flat_map: Dict[str, Any] = {}

        for ticker, data in metrics_data.items():
            t_upper = ticker.upper()

            if "cagr_revenue_pct" in data and data["cagr_revenue_pct"] is not None:
                cagr_val = data["cagr_revenue_pct"]
                flat_map[f"{t_upper}.revenue_cagr"] = f"%{cagr_val:.2f}"
                flat_map[f"{t_upper}.cagr"] = f"%{cagr_val:.2f}"
                flat_map[f"{t_upper}.cagr_raw"] = float(cagr_val)

            yearly_list = data.get("yearly_financials", [])
            for yf in yearly_list:
                fy = yf.get("fy")
                if not fy:
                    continue

                if yf.get("revenue") is not None:
                    rev = yf["revenue"]
                    flat_map[f"{t_upper}.revenue_{fy}"] = f"${rev:,.0f}"
                    flat_map[f"{t_upper}.revenue_{fy}_raw"] = float(rev)

                if yf.get("gross_margin_pct") is not None:
                    gm = yf["gross_margin_pct"]
                    flat_map[f"{t_upper}.gross_margin_{fy}"] = f"%{gm:.2f}"
                    flat_map[f"{t_upper}.gross_margin_{fy}_raw"] = float(gm)

                if yf.get("operating_margin_pct") is not None:
                    om = yf["operating_margin_pct"]
                    flat_map[f"{t_upper}.operating_margin_{fy}"] = f"%{om:.2f}"
                    flat_map[f"{t_upper}.operating_margin_{fy}_raw"] = float(om)

                if yf.get("net_margin_pct") is not None:
                    nm = yf["net_margin_pct"]
                    flat_map[f"{t_upper}.net_margin_{fy}"] = f"%{nm:.2f}"
                    flat_map[f"{t_upper}.net_margin_{fy}_raw"] = float(nm)

            for k, v in data.items():
                if isinstance(v, (int, float, str)):
                    flat_map[f"{t_upper}.{k}"] = v

        return flat_map

    @classmethod
    def render(
        cls,
        template_text: str,
        metrics_data: Dict[str, Any],
        strict: bool = False,
    ) -> Tuple[str, List[str]]:
        flat_map = cls.build_reference_dict(metrics_data)
        missing_keys: List[str] = []

        def _replacer(match: re.Match) -> str:
            key = match.group(1).strip()
            if key in flat_map:
                return str(flat_map[key])
            for k, v in flat_map.items():
                if k.lower() == key.lower():
                    return str(v)

            missing_keys.append(key)
            if strict:
                raise KeyError(f"Eksik metrik yer tutucusu: '{key}'")
            return f"{{{{MISSING:{key}}}}}"

        rendered_text = cls.PLACEHOLDER_REGEX.sub(_replacer, template_text)
        return rendered_text, missing_keys


class NumberVerifier:

    NUMBER_PATTERN = re.compile(
        r"""
        (?:[₺\$€£]\s*)?                   # Opsiyonel para birimi
        (-?\d{1,3}(?:,\d{3})+(?:\.\d+)?   # 1,000 veya 394,328,000,000
        |-?\d+\.\d+                       # 43.31 veya 7.81
        |-?\d+)                           # Tam sayı
        (?:\s*%)?                         # Opsiyonel yüzde
        """,
        re.VERBOSE,
    )

    @classmethod
    def extract_numbers(cls, text: str) -> List[Tuple[str, float]]:
        matches = cls.NUMBER_PATTERN.finditer(text)
        numbers: List[Tuple[str, float]] = []

        for m in matches:
            raw_str = m.group(0).strip()
            num_str = m.group(1).replace(",", "").strip()

            try:
                val = float(num_str)
            except ValueError:
                continue

            if val.is_integer() and 2010 <= int(val) <= 2035:
                continue

            if val.is_integer() and 1 <= int(val) <= 10 and ("." in raw_str or raw_str.startswith("#")):
                continue

            numbers.append((raw_str, val))

        return numbers

    @classmethod
    def build_numerical_pool(cls, metrics_data: Dict[str, Any]) -> Dict[str, float]:
        pool: Dict[str, float] = {}

        flat_map = MetricPlaceholderEngine.build_reference_dict(metrics_data)
        for k, v in flat_map.items():
            if isinstance(v, (int, float)):
                pool[k] = float(v)
            elif isinstance(v, str):
                clean_s = v.replace("$", "").replace("%", "").replace(",", "").strip()
                try:
                    pool[k] = float(clean_s)
                except ValueError:
                    pass

        return pool

    @classmethod
    def verify_numbers(
        cls,
        report_text: str,
        metrics_data: Dict[str, Any],
        tolerance_pct: float = 1.0,
    ) -> List[NumberVerificationResult]:
        claims = cls.extract_numbers(report_text)
        pool = cls.build_numerical_pool(metrics_data)
        results: List[NumberVerificationResult] = []

        for raw_str, claimed_val in claims:
            best_match_key = None
            best_ref_val = None
            min_error_pct = float("inf")

            for ref_key, ref_val in pool.items():
                if ref_val == 0.0:
                    diff_pct = 0.0 if claimed_val == 0.0 else 100.0
                else:
                    diff_pct = (abs(claimed_val - ref_val) / abs(ref_val)) * 100.0

                if diff_pct < min_error_pct:
                    min_error_pct = diff_pct
                    best_match_key = ref_key
                    best_ref_val = ref_val

            is_valid = min_error_pct <= tolerance_pct

            if is_valid:
                msg = f"Onaylandı: {raw_str} -> {best_match_key} (Hata: %{min_error_pct:.2f} <= %{tolerance_pct})"
            else:
                msg = (
                    f"RED: '{raw_str}' ({claimed_val}) referans havuzunda bulunamadı! "
                    f"En yakın referans '{best_match_key}' ({best_ref_val}), sapma: %{min_error_pct:.2f} > %{tolerance_pct}"
                )

            results.append(
                NumberVerificationResult(
                    raw_match=raw_str,
                    claimed_value=claimed_val,
                    matched_reference_key=best_match_key,
                    reference_value=best_ref_val,
                    relative_error_pct=round(min_error_pct, 2) if min_error_pct != float("inf") else 999.0,
                    is_valid=is_valid,
                    message=msg,
                )
            )

        return results


class FaithfulnessJudge:

    JUDGE_PROMPT_TEMPLATE = """\
Sen bağımsız bir Baş Finans Denetçisisin (LLM-as-a-Judge).
Görevin, Analist tarafından yazılan rapordaki metinsel iddiaların verilen 10-K kaynak metni
tarafından doğrudan ve eksiksiz desteklenip desteklenmediğini (Faithfulness) denetlemektir.

[KAYNAK 10-K METİNLERİ (GROUND TRUTH)]:
{context_chunks}

[DEĞERLENDİRİLECEK RAPOR]:
{report_text}

Değerlendirme Kuralları:
1. Raporda geçen iddialar kaynakta açıkça yazıyor mu?
2. Kaynakta olmayan spekülasyon veya çarpıtma var mı?
3. Yanıtını KESİNLİKLE aşağıdaki JSON formatında ver:
{{
  "faithfulness_score": 0.0 - 1.0,
  "is_faithful": true / false,
  "supported_claims": ["Desteklenen iddia 1", ...],
  "unsupported_claims": ["Kaynaksız veya çarpıtılmış iddia 1", ...],
  "critic_notes": "Eleştiri ve revizyon notları"
}}
"""

    @classmethod
    def evaluate(
        cls,
        report_text: str,
        context_chunks: List[Dict[str, Any]],
        metrics_data: Optional[Dict[str, Any]] = None,
        gemini_client: Optional[Any] = None,
    ) -> FaithfulnessVerdict:
        context_parts = [c.get("text", "") for c in context_chunks]

        if metrics_data:
            flat_metrics = MetricPlaceholderEngine.build_reference_dict(metrics_data)
            metrics_summary_text = " ".join([f"{k} {v}" for k, v in flat_metrics.items()])
            context_parts.append(metrics_summary_text)

        combined_context = "\n---\n".join(context_parts)

        if not combined_context.strip():
            return FaithfulnessVerdict(
                is_faithful=False,
                faithfulness_score=0.0,
                unsupported_claims=["Hiçbir 10-K veya metrik kaynak metni sağlanmadı."],
                critic_notes="Kaynak metin olmadan iddialar doğrulanamaz.",
            )

        if gemini_client is not None:
            try:
                prompt = cls.JUDGE_PROMPT_TEMPLATE.format(
                    context_chunks=combined_context[:8000],
                    report_text=report_text[:4000],
                )
                response = gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                )
                raw_out = response.text.strip()
                json_match = re.search(r"\{.*\}", raw_out, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                    return FaithfulnessVerdict(
                        is_faithful=bool(parsed.get("is_faithful", False)),
                        faithfulness_score=float(parsed.get("faithfulness_score", 0.0)),
                        supported_claims=parsed.get("supported_claims", []),
                        unsupported_claims=parsed.get("unsupported_claims", []),
                        critic_notes=parsed.get("critic_notes", ""),
                    )
            except Exception as e:
                logger.warning("[FaithfulnessJudge] Gemini API çağrısı başarısız, deterministik denetçiye geçiliyor: %s", e)

        sentences = [
            s.strip() for s in re.split(r"[.!?\n]", report_text)
            if len(s.strip().split()) >= 3 and not s.strip().startswith(("#", "|", "-"))
        ]

        if not sentences:
            return FaithfulnessVerdict(is_faithful=True, faithfulness_score=1.0)

        context_lower = combined_context.lower()
        supported: List[str] = []
        unsupported: List[str] = []

        financial_terms = {"brüt", "marj", "marjı", "gelir", "geliri", "cagr", "revenue", "margin", "profit"}

        for sent in sentences:
            words = [w.lower() for w in re.findall(r"\b[A-Za-zçğıöşüÇĞİÖŞÜ0-9]{3,}\b", sent)]
            if not words:
                continue

            is_financial_statement = any(t in words for t in financial_terms) and any(c.isdigit() for c in sent)

            matches = sum(1 for w in words if w in context_lower)
            match_ratio = matches / len(words)

            if match_ratio >= 0.35 or is_financial_statement:
                supported.append(sent)
            else:
                unsupported.append(f"Kaynakta bulunamayan ifade: '{sent}'")

        score = len(supported) / max(len(sentences), 1)
        is_faithful = score >= 0.70 and len(unsupported) <= 1

        return FaithfulnessVerdict(
            is_faithful=is_faithful,
            faithfulness_score=round(score, 2),
            supported_claims=supported,
            unsupported_claims=unsupported,
            critic_notes="Deterministik kelime ve semantik örtüşme denetimi tamamlandı.",
        )


class WriterCriticOrchestrator:

    MAX_REVISION_ROUNDS = 2

    def __init__(self, gemini_client: Optional[Any] = None):
        self.gemini_client = gemini_client
        self.placeholder_engine = MetricPlaceholderEngine()
        self.number_verifier = NumberVerifier()
        self.faithfulness_judge = FaithfulnessJudge()

    def review_draft(
        self,
        draft_template: str,
        metrics_data: Dict[str, Any],
        context_chunks: List[Dict[str, Any]],
        revision_round: int = 0,
    ) -> Tuple[CriticReviewResult, str]:
        rendered_text, missing_keys = self.placeholder_engine.render(
            template_text=draft_template,
            metrics_data=metrics_data,
            strict=False,
        )

        placeholders_ok = len(missing_keys) == 0

        num_checks = self.number_verifier.verify_numbers(
            report_text=rendered_text,
            metrics_data=metrics_data,
            tolerance_pct=1.0,
        )
        invalid_nums = [c for c in num_checks if not c.is_valid]
        num_ok = len(invalid_nums) == 0

        faithfulness = self.faithfulness_judge.evaluate(
            report_text=rendered_text,
            context_chunks=context_chunks,
            metrics_data=metrics_data,
            gemini_client=self.gemini_client,
        )

        is_approved = placeholders_ok and num_ok and faithfulness.is_faithful

        verdict_str = "APPROVED" if is_approved else "REJECTED"

        feedback_lines = []
        if not placeholders_ok:
            feedback_lines.append(f"❌ EKSİK YER TUTUCULAR: {', '.join(missing_keys)} tool çıktısında bulunamadı.")

        if not num_ok:
            feedback_lines.append(f"❌ SAYISAL TUTARSIZLIK (%1 tolerans aşıldı): {len(invalid_nums)} adet kaynaksız sayı tespit edildi:")
            for inv in invalid_nums:
                feedback_lines.append(f"   - {inv.message}")

        if not faithfulness.is_faithful:
            feedback_lines.append(f"❌ METİNSEL SADAKATSİZLİK (Skor: {faithfulness.faithfulness_score}):")
            for unsup in faithfulness.unsupported_claims[:3]:
                feedback_lines.append(f"   - {unsup}")

        feedback_text = "\n".join(feedback_lines)

        review = CriticReviewResult(
            verdict=verdict_str,
            number_check_passed=num_ok,
            faithfulness_passed=faithfulness.is_faithful,
            placeholders_rendered=placeholders_ok,
            number_checks=num_checks,
            faithfulness=faithfulness,
            feedback_for_writer=feedback_text,
            revision_round=revision_round,
        )

        return review, rendered_text

    def execute_writer_critic_loop(
        self,
        writer_fn: Any,                                       
        metrics_data: Dict[str, Any],
        context_chunks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        feedback: Optional[str] = None
        current_round = 0
        final_rendered = ""
        last_review = None

        while current_round <= self.MAX_REVISION_ROUNDS:
            logger.info("[Writer-Critic] Tur %d başlıyor (Maks: %d)...", current_round, self.MAX_REVISION_ROUNDS)

            draft_template = writer_fn(feedback=feedback, round_num=current_round)

            review, final_rendered = self.review_draft(
                draft_template=draft_template,
                metrics_data=metrics_data,
                context_chunks=context_chunks,
                revision_round=current_round,
            )
            last_review = review

            if review.verdict == "APPROVED":
                logger.info("[Writer-Critic] Taslak Tur %d'de ONAYLANDI!", current_round)
                return {
                    "status": "APPROVED",
                    "total_rounds": current_round,
                    "final_report": final_rendered,
                    "review": review.to_dict(),
                }

            logger.warning("[Writer-Critic] Taslak Tur %d'de REDDEDİLDİ! Gerekçe:\n%s", current_round, review.feedback_for_writer)
            feedback = review.feedback_for_writer
            current_round += 1

        logger.warning("[Writer-Critic] Azami revizyon turu (%d) aşıldı! Uyarı notuyla sonlandırılıyor.", self.MAX_REVISION_ROUNDS)
        warning_header = (
            "> ⚠️ **DİKKAT — DOĞRULAMA UYARISI:** Bu rapor azami revizyon turuna ulaştığı için "
            "bazı iddialar Critic tarafından tam onaylanamamıştır. Detaylar rapor sonunda belirtilmiştir.\n\n"
        )
        return {
            "status": "FORCE_APPROVED_WITH_WARNINGS",
            "total_rounds": self.MAX_REVISION_ROUNDS,
            "final_report": warning_header + final_rendered,
            "review": last_review.to_dict() if last_review else {},
        }
