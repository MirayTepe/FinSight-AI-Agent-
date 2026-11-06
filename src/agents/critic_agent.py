
from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ClaimCheck:
    raw_text: str                                                           
    claimed_value: float                                     
    matched_key: str | None                                      
    source_value: float | None                               
    is_valid: bool                               
    tolerance_pct: float                                  
    note: str = ""                              


@dataclass
class CriticVerdict:
    decision: str                                                    
    checks: list[ClaimCheck] = field(default_factory=list)
    feedback: str = ""
    invalid_count: int = 0
    total_count: int = 0

    @property
    def approval_rate(self) -> float:
        if self.total_count == 0:
            return 1.0
        return (self.total_count - self.invalid_count) / self.total_count



class CriticAgent:

    DEFAULT_TOLERANCE_PCT: float = 2.0                   

    _NUMBER_PATTERN = re.compile(
        r"""
        (?:                     # Önek (opsiyonel)
            [₺\$€£%]            # Para birimi veya yüzde
            \s*
        )?
        (                       # Ana sayı grubu
            -?                  # Negatif olabilir
            \d{1,3}             # 1-3 basamak
            (?:[.,]\d{3})*      # Binlik ayraç (1.234.567 veya 1,234,567)
            (?:[.,]\d+)?        # Ondalık kısım
            |
            -?\d+               # Tam sayı
        )
        (?:                     # Sonek (opsiyonel)
            \s*
            (?:x|%|TRY|USD|EUR|Milyar|Milyon|milyar|milyon|bn|mn)?
        )
        """,
        re.VERBOSE,
    )

    def __init__(self, tolerance_pct: float = DEFAULT_TOLERANCE_PCT):
        self.tolerance_pct = tolerance_pct


    def verify(self, report_markdown: str, raw_data: dict[str, Any]) -> CriticVerdict:
        reference_pool = self._build_reference_pool(raw_data)
        logger.debug("[CriticAgent] Referans havuzu: %s", list(reference_pool.keys()))

        claims = self._extract_claims(report_markdown)
        logger.info("[CriticAgent] %d sayısal iddia tespit edildi.", len(claims))

        checks: list[ClaimCheck] = []
        for raw_text, value in claims:
            check = self._match_claim(raw_text, value, reference_pool)
            checks.append(check)

        invalid = [c for c in checks if not c.is_valid]
        total = len(checks)

        if not invalid:
            return CriticVerdict(
                decision     = "APPROVED",
                checks       = checks,
                feedback     = "",
                invalid_count= 0,
                total_count  = total,
            )
        else:
            feedback = self._build_feedback(invalid, raw_data)
            return CriticVerdict(
                decision     = "REJECTED",
                checks       = checks,
                feedback     = feedback,
                invalid_count= len(invalid),
                total_count  = total,
            )


    def _build_reference_pool(self, raw_data: dict[str, Any]) -> dict[str, float]:
        pool: dict[str, float] = {}
        self._flatten(raw_data, prefix="", pool=pool)
        return pool

    def _flatten(self, obj: Any, prefix: str, pool: dict[str, float]) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                new_key = f"{prefix}.{k}" if prefix else k
                self._flatten(v, new_key, pool)
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                self._flatten(v, f"{prefix}[{i}]", pool)
        else:
            try:
                num = float(str(obj).replace(",", "").replace(" ", ""))
                if not (math.isnan(num) or math.isinf(num)):
                    pool[prefix] = num
            except (ValueError, TypeError):
                pass                                       


    _CALC_CONTEXT_RE = re.compile(
        r"[-\d.,]+\s*[/÷×*]\s*[-\d.,]+\s*=\s*[-\d.,]+"
    )

    _CLAIM_LINE_RE = re.compile(
        r"(?:^\s*\||\s*[-•*]\s|\s*\d+\.\s)",                                           
        re.MULTILINE,
    )

    def _extract_claims(self, text: str) -> list[tuple[str, float]]:
        calc_spans: list[tuple[int, int]] = [
            (m.start(), m.end()) for m in self._CALC_CONTEXT_RE.finditer(text)
        ]
        header_spans: list[tuple[int, int]] = [
            (m.start(), m.end()) for m in re.finditer(r"^#+.*$", text, re.MULTILINE)
        ]
        range_spans: list[tuple[int, int]] = [
            (m.start(), m.end()) for m in re.finditer(r"\([^)]*\b\d+\s*[-–]\s*\d+[^)]*\)", text)
        ]
        ignored_spans = calc_spans + header_spans + range_spans

        claims: list[tuple[str, float]] = []
        seen_values: set[float] = set()

        for match in self._NUMBER_PATTERN.finditer(text):
            pos = match.start()

            in_ignored = any(s <= pos <= e for s, e in ignored_spans)
            if in_ignored:
                continue

            raw = match.group(1).replace(",", ".")
            parts = raw.split(".")
            if len(parts) > 2:
                raw = "".join(parts[:-1]) + "." + parts[-1]

            try:
                val = float(raw)
            except ValueError:
                continue

            if abs(val) < 0.01 or val in seen_values:
                continue

            seen_values.add(val)
            context = text[max(0, match.start() - 50): match.end() + 50]
            claims.append((context.strip(), val))

        return claims


    def _match_claim(
        self,
        raw_text: str,
        claimed: float,
        pool: dict[str, float],
    ) -> ClaimCheck:
        best_key: str | None = None
        best_ref: float | None = None
        best_diff: float = float("inf")

        scale_variants = [1.0, 1e6, 1e9, 1e-6, 1e-9, 100.0, 0.01]

        for key, ref_val in pool.items():
            if ref_val == 0:
                continue
            for scale in scale_variants:
                scaled_claimed = claimed * scale
                diff_pct = abs(scaled_claimed - ref_val) / abs(ref_val) * 100
                if diff_pct < best_diff:
                    best_diff = diff_pct
                    best_key = key
                    best_ref = ref_val

        is_valid = best_diff <= self.tolerance_pct
        note = (
            f"OK — {best_key}={best_ref} ile %{best_diff:.2f} sapma"
            if is_valid
            else f"HATA — En yakın: {best_key}={best_ref}, sapma %{best_diff:.1f}"
        )

        return ClaimCheck(
            raw_text      = raw_text[:80],
            claimed_value = claimed,
            matched_key   = best_key,
            source_value  = best_ref,
            is_valid      = is_valid,
            tolerance_pct = self.tolerance_pct,
            note          = note,
        )


    def _build_feedback(
        self,
        invalid_checks: list[ClaimCheck],
        raw_data: dict[str, Any],
    ) -> str:
        lines = [
            "## Critic Revizyon Talebi",
            "",
            f"Raporda **{len(invalid_checks)}** doğrulanamayan sayısal iddia tespit edildi.",
            "Lütfen aşağıdaki değerleri ham veri kaynağıyla uyumlu hale getir:",
            "",
        ]

        for i, check in enumerate(invalid_checks, 1):
            lines.append(f"### Sorun {i}")
            lines.append(f"- **Rapordan alınan metin:** `{check.raw_text}`")
            lines.append(f"- **İddia edilen değer:** `{check.claimed_value}`")
            if check.source_value is not None:
                lines.append(f"- **Ham verideki en yakın değer:** `{check.source_value}` (alan: `{check.matched_key}`)")
                lines.append(f"- **Sapma:** %{abs(check.claimed_value - check.source_value) / max(abs(check.source_value), 1e-9) * 100:.1f}")
            else:
                lines.append("- **Ham veride eşleşen değer bulunamadı** — bu değeri kaldır veya 'Veri mevcut değil' yaz.")
            lines.append("")

        lines += [
            "---",
            "**Düzeltme Kuralı:** Yalnızca belirtilen değerleri güncelle.",
            "Ham veride olmayan hiçbir yeni sayısal değer ekleme.",
        ]

        return "\n".join(lines)
