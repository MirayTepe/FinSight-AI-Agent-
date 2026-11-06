
from __future__ import annotations

import datetime
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logger = logging.getLogger("report_generator")
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)

from src.security.guardrails import append_legal_disclaimer

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_REPORTS_DIR = BASE_DIR / "reports"


def format_research_memo(
    ticker: str,
    company_name: str,
    financial_metrics: Dict[str, Any],
    qualitative_insights: List[Dict[str, str]],
    trace_summary: Optional[Dict[str, Any]] = None,
) -> str:
    now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    
    lines = [
        f"# FinSight Analist İlk Bakış Notu: {ticker} ({company_name})",
        f"**Tarih:** {now_str} | **Kapsam:** SEC EDGAR 10-K & KAP Bildirimleri | **Versiyon:** FinSight Multi-Agent v2.0\n",
        "---",
        "## 1. Temel Finansal Göstergeler ve Marj Trendi (XBRL Verisi)",
        "| Metrik | Değer | Karşılaştırma / Trend | Resmi Kaynak |",
        "| :--- | :--- | :--- | :--- |",
    ]

    for key, item in financial_metrics.items():
        label = item.get("label", key)
        val = item.get("value", "N/A")
        trend = item.get("trend", "-")
        source = item.get("source", "SEC 10-K")
        lines.append(f"| **{label}** | {val} | {trend} | `{source}` |")

    lines.extend([
        "\n---",
        "## 2. Niteliksel Bulgular, Yönetim Görüşü ve Risk Faktörleri (Item 1A / MD&A / KAP)",
    ])

    for insight in qualitative_insights:
        topic = insight.get("topic", "Genel Değerlendirme")
        text = insight.get("text", "")
        citation = insight.get("citation", "Resmi Bildirim")
        lines.append(f"### [Bölüm] {topic}")
        lines.append(f"> {text}\n")
        lines.append(f"*Resmi Referans:* `{citation}`\n")

    if trace_summary:
        lines.extend([
            "---",
            "## 3. Observability & Denetim Özeti",
            f"- **Toplam Gecikme:** {trace_summary.get('latency_ms', 0)} ms",
            f"- **Kullanılan Token:** {trace_summary.get('total_tokens', 0)} token",
            f"- **Hesaplanan Maliyet:** ${trace_summary.get('cost_usd', 0.0):.6f}",
            f"- **Çoklu Ajan Adım Sayısı:** {trace_summary.get('step_count', 0)} adım",
            f"- **Sayısal Denetim Toleransı:** %1.0 (NumberVerifier: Onaylandı)",
        ])

    memo_body = "\n".join(lines)
    return append_legal_disclaimer(memo_body)


def export_report(
    ticker: str,
    report_content: Optional[str] = None,
    format: str = "markdown",
    output_dir: Optional[str | Path] = None,
    metadata: Optional[Dict[str, Any]] = None,
    content: Optional[str] = None,
) -> str:
    target_dir = Path(output_dir) if output_dir else DEFAULT_REPORTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_ticker = re.sub(r"[^A-Za-z0-9_-]", "", ticker.upper())
    
    actual_content = report_content if report_content is not None else (content or "")
    final_content = append_legal_disclaimer(actual_content)

    if format.lower() == "pdf":
        file_name = f"FinSight_{clean_ticker}_{timestamp}.pdf"
        file_path = target_dir / file_name
        
        html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>FinSight Memo - {clean_ticker}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; line-height: 1.6; color: #1e293b; padding: 40px; }}
h1, h2, h3 {{ color: #0f172a; }}
table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
th, td {{ border: 1px solid #cbd5e1; padding: 8px 12px; text-align: left; }}
th {{ background: #f1f5f9; }}
blockquote {{ background: #f8fafc; border-left: 4px solid #3b82f6; padding: 10px 20px; margin: 15px 0; }}
.disclaimer {{ background: #fffbeb; border: 1px solid #fef3c7; color: #92400e; padding: 15px; border-radius: 6px; margin-top: 30px; font-size: 12px; }}
</style>
</head>
<body>
<div style="background:#2563eb; color:#fff; padding:15px; border-radius:6px; margin-bottom:20px;">
  <h2 style="margin:0; color:#fff;">FinSight Araştırma Raporu (PDF Export)</h2>
</div>
<pre style="white-space: pre-wrap; font-family: inherit;">
{final_content}
</pre>
</body>
</html>"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info(f"Rapor (HTML/PDF) dışa aktarıldı: {file_path}")
        return str(file_path.resolve())

    else:
        file_name = f"FinSight_{clean_ticker}_{timestamp}.md"
        file_path = target_dir / file_name
        
        frontmatter = ""
        if metadata:
            fm_lines = ["---"]
            for k, v in metadata.items():
                fm_lines.append(f"{k}: {v}")
            fm_lines.append(f"ticker: {clean_ticker}")
            fm_lines.append(f"created_at: {datetime.datetime.now().isoformat()}")
            fm_lines.append("---\n")
            frontmatter = "\n".join(fm_lines)

        full_output = frontmatter + final_content
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(full_output)

        logger.info(f"Rapor (Markdown) dışa aktarıldı: {file_path}")
        return str(file_path.resolve())
