
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Union

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from src.tools.edgar_cleaner import EdgarFactsCleaner
from src.tools.filing_rag import EdgarFilingRAG
from src.tools.financial_calculator import FinancialCalculator, compare_companies
from src.tools.market_data import MarketDataFetcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("finsight_mcp")

mcp = FastMCP(
    name="FinSight-EDGAR-MCP",
    instructions=(
        "FinSight kurumsal finansal analiz ve SEC EDGAR MCP sunucusu. "
        "Şirketlerin 10-K metinlerini arayabilir, XBRL finansallarını temizlenmiş "
        "olarak alabilir, hisse verisi çekebilir ve deterministik rasyo hesabı yapabilirsiniz."
    ),
)

_edgar_cleaner: Optional[EdgarFactsCleaner] = None
_filing_rag: Optional[EdgarFilingRAG] = None


def get_cleaner() -> EdgarFactsCleaner:
    global _edgar_cleaner
    if _edgar_cleaner is None:
        yaml_path = ROOT_DIR / "metrics.yaml"
        _edgar_cleaner = EdgarFactsCleaner(metrics_yaml_path=yaml_path)
    return _edgar_cleaner


def get_rag() -> EdgarFilingRAG:
    global _filing_rag
    if _filing_rag is None:
        _filing_rag = EdgarFilingRAG(raw_data_dir=ROOT_DIR / "data" / "raw")
        _seed_rag_index(_filing_rag)
    return _filing_rag


def _seed_rag_index(rag: EdgarFilingRAG):
    sample_text = (
        "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\nFORM 10-K\n\n"
        "TABLE OF CONTENTS\n"
        "Item 1. Business ........................... Page 1\n"
        "Item 1A. Risk Factors ....................... Page 8\n"
        "Item 7. Management's Discussion ............ Page 25\n\n"
        + ("Introductory regulatory text.\n" * 30)
        + "\nITEM 1. Business\n"
        "Apple Inc. designs, manufactures and markets smartphones, personal computers, tablets, "
        "wearables and accessories, and sells a variety of related services.\n"
        "The Company's fiscal year ends on the last Saturday of September.\n"
        "iPhone is the Company's flagship smartphone line based on its proprietary iOS operating system.\n\n"
        + "\nITEM 1A. Risk Factors\n"
        "The Company's business and financial results can be adversely affected by unfavorable global economic "
        "conditions, international trade tensions, and semiconductor supply chain disruptions in Taiwan and Asia.\n"
        "Regulatory scrutiny including the European Digital Markets Act (DMA) and US DOJ antitrust lawsuits "
        "could force modifications to the App Store business model and commission rates.\n\n"
        + "\nITEM 1B. Unresolved Staff Comments\nNone.\n\n"
        + "\nITEM 7. Management's Discussion and Analysis of Financial Condition and Results of Operations\n"
        "Total net sales were $394.3 billion in 2024, up 2% compared to 2023.\n"
        "Products net sales were $298.1 billion, while Services net sales reached a new record of $96.2 billion.\n"
        "Gross margin expanded to 46.2%, driven by services mix and lower component costs.\n"
        "Operating income reached $123.2 billion, demonstrating operational discipline.\n\n"
        + "\nITEM 7A. Quantitative and Qualitative Disclosures\nInterest rate derivatives.\n"
    )
    rag.index_filing(
        html_or_text=sample_text,
        ticker="AAPL",
        form="10-K",
        fy=2024,
        accn="0000320193-24-000123",
        url="https://www.sec.gov/edgar/data/320193/000032019324000123/aapl-20240928.htm",
        is_already_clean_text=True,
    )


@mcp.tool()
def resolve_ticker_to_cik(
    ticker: Annotated[
        str,
        Field(
            description="Borsa hisse senedi sembolü (Örnek: 'AAPL', 'MSFT', 'TSLA')",
            min_length=1,
            max_length=10,
        ),
    ],
) -> Dict[str, Any]:
    logger.info("[MCP] resolve_ticker_to_cik: %s", ticker)
    ticker_clean = ticker.strip().upper()

    tickers_file = ROOT_DIR / "data" / "raw" / "company_tickers.json"
    if not tickers_file.exists():
        return {
            "success": False,
            "error": "company_tickers.json yerel diskte bulunamadı. Lütfen download_edgar.py çalıştırın.",
        }

    try:
        with open(tickers_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        for item in data.values():
            if str(item.get("ticker", "")).upper() == ticker_clean:
                cik_int = int(item["cik_str"])
                return {
                    "success": True,
                    "ticker": ticker_clean,
                    "cik": cik_int,
                    "cik_10": str(cik_int).zfill(10),
                    "title": item.get("title", ""),
                }

        return {
            "success": False,
            "error": f"'{ticker_clean}' sembolüne ait CIK numarası bulunamadı.",
        }
    except Exception as e:
        logger.error("[MCP] resolve_ticker_to_cik hatası: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool()
def get_company_facts(
    cik: Annotated[
        str,
        Field(
            description="10 haneli sıfır dolgulu CIK numarası (örn: '0000320193') veya hisse kodu",
        ),
    ],
    concept: Annotated[
        Optional[str],
        Field(
            description="İstenen US-GAAP kavramı veya metrik (örn: 'Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax')",
            default=None,
        ),
    ] = None,
    years: Annotated[
        Optional[Union[int, List[int]]],
        Field(description="Mali yıl veya yıllar (örn: 2024 veya [2022, 2023, 2024])", default=None),
    ] = None,
    unit: Annotated[
        str,
        Field(description="Birim filtresi (varsayılan: 'USD')", default="USD"),
    ] = "USD",
    start_year: Annotated[
        Optional[int],
        Field(description="Başlangıç mali yılı filtresi (geriye dönük uyumluluk)", default=2018),
    ] = 2018,
    end_year: Annotated[
        Optional[int],
        Field(description="Bitiş mali yılı filtresi (geriye dönük uyumluluk)", default=2026),
    ] = 2026,
    clean_series: Annotated[
        bool,
        Field(description="Temizlenmiş gelir serisi, marjlar ve CAGR özetini hesapla", default=True),
    ] = True,
) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    logger.info("[MCP] get_company_facts: CIK=%s, concept=%s, years=%s, unit=%s", cik, concept, years, unit)
    cik_str = str(cik).strip()

    if not cik_str.isdigit():
        res = resolve_ticker_to_cik(cik_str)
        if not res.get("success"):
            return res
        cik_str = res["cik_10"]
    else:
        cik_str = cik_str.zfill(10)

    facts_path = ROOT_DIR / "data" / "raw" / cik_str / f"companyfacts_{cik_str}.json"
    if not facts_path.exists():
        return {
            "success": False,
            "error": f"CIK {cik_str} için yerel companyfacts dosyası bulunamadı: {facts_path.name}",
        }

    try:
        with open(facts_path, "r", encoding="utf-8") as f:
            facts = json.load(f)

        if concept:
            us_gaap = facts.get("facts", {}).get("us-gaap", {})
            concept_data = us_gaap.get(concept)
            if not concept_data:
                cleaner = get_cleaner()
                tag_priority = cleaner.metrics_config.get("metrics", {}).get(concept, {}).get("tags_priority", [])
                for alt_tag in tag_priority:
                    if alt_tag in us_gaap:
                        concept_data = us_gaap[alt_tag]
                        concept = alt_tag
                        break

            if not concept_data:
                return []

            units_data = concept_data.get("units", {})
            target_unit_items = units_data.get(unit, units_data.get("USD", []))

            target_years_list = None
            if years is not None:
                target_years_list = [years] if isinstance(years, int) else list(years)

            results: List[Dict[str, Any]] = []
            seen_periods: Dict[str, Dict[str, Any]] = {}

            for item in target_unit_items:
                fy = item.get("fy")
                form = item.get("form", "")
                fp = item.get("fp", "")
                val = item.get("val")

                if target_years_list and fy not in target_years_list:
                    continue
                if fp != "FY" and "10-K" not in form:
                    continue

                end_date = item.get("end", "")
                filed_date = item.get("filed", "")
                period_key = f"{fy}_{fp}_{end_date}"

                entry = {
                    "fy": fy,
                    "fp": fp,
                    "form": form,
                    "value": val,
                    "unit": unit,
                    "end": end_date,
                    "filed": filed_date,
                    "accn": item.get("accn", ""),
                    "tag": concept,
                }

                if period_key not in seen_periods or filed_date > seen_periods[period_key]["filed"]:
                    seen_periods[period_key] = entry

            results = sorted(list(seen_periods.values()), key=lambda x: (x.get("fy") or 0, x.get("end") or ""))
            return results

        if not clean_series:
            return {
                "success": True,
                "cik": cik_str,
                "entityName": facts.get("entityName"),
                "facts_count": len(facts.get("facts", {}).get("us-gaap", {})),
            }

        cleaner = get_cleaner()
        eff_start = min(years) if isinstance(years, list) and years else (years if isinstance(years, int) else start_year)
        eff_end = max(years) if isinstance(years, list) and years else (years if isinstance(years, int) else end_year)
        summary = cleaner.generate_comprehensive_summary(
            facts, start_fy=eff_start, end_fy=eff_end
        )
        return {
            "success": True,
            "data": summary,
        }
    except Exception as e:
        logger.error("[MCP] get_company_facts hatası: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool()
def search_filings(
    query: Annotated[
        str,
        Field(description="Arama sorgusu (örn: 'semiconductor supply chain Taiwan')"),
    ],
    ticker: Annotated[
        str,
        Field(description="Hisse kodu (örn: 'AAPL')", default="AAPL"),
    ] = "AAPL",
    fy: Annotated[
        Optional[int],
        Field(description="Mali yıl filtresi (örn: 2024) — Yanlış yıl gelmesini önler", default=None),
    ] = None,
    section: Annotated[
        Optional[str],
        Field(
            description="Bölüm filtresi: 'item_1' (Business), 'item_1a' (Risk Factors), 'item_7' (MD&A)",
            default=None,
        ),
    ] = None,
    top_k: Annotated[
        int,
        Field(description="Döndürülecek sonuç sayısı", default=3, ge=1, le=10),
    ] = 3,
) -> Dict[str, Any]:
    logger.info("[MCP] search_filings: query='%s', ticker=%s, fy=%s, section=%s", query, ticker, fy, section)
    rag = get_rag()
    results = rag.search_filings(
        query=query,
        ticker=ticker,
        fy=fy,
        section=section,
        top_k=top_k,
    )
    return {
        "success": True,
        "query": query,
        "results_count": len(results),
        "results": [r.to_dict() for r in results],
    }


@mcp.tool()
def get_filing_section(
    ticker: Annotated[
        str,
        Field(description="Hisse kodu (örn: 'AAPL')"),
    ],
    fy: Annotated[
        int,
        Field(description="Mali yıl (örn: 2024)"),
    ],
    section: Annotated[
        str,
        Field(description="Bölüm adı: 'item_1' (Business), 'item_1a' (Risk Factors), 'item_7' (MD&A)"),
    ],
) -> Dict[str, Any]:
    logger.info("[MCP] get_filing_section: %s FY%d section=%s", ticker, fy, section)
    rag = get_rag()
    text = rag.get_filing_section(ticker=ticker, fy=fy, section=section)
    if text is None:
        return {
            "success": False,
            "error": f"'{ticker}' için FY{fy} ve '{section}' bölümü bulunamadı.",
        }
    return {
        "success": True,
        "ticker": ticker.upper(),
        "fy": fy,
        "section": section.lower(),
        "text": text,
    }


@mcp.tool(name="compute_metrics")
def compute_metrics_tool(
    revenue: Annotated[float, Field(description="Net satışlar / gelir (pozitif)")],
    gross_profit: Annotated[Optional[float], Field(default=None, description="Brüt kâr")] = None,
    operating_income: Annotated[Optional[float], Field(default=None, description="Faaliyet kârı")] = None,
    net_income: Annotated[Optional[float], Field(default=None, description="Net kâr")] = None,
    previous_revenue: Annotated[Optional[float], Field(default=None, description="Önceki yıl geliri")] = None,
    cagr_start_value: Annotated[Optional[float], Field(default=None, description="CAGR başlangıç değeri")] = None,
    cagr_end_value: Annotated[Optional[float], Field(default=None, description="CAGR bitiş değeri")] = None,
    cagr_years: Annotated[Optional[int], Field(default=None, description="CAGR yıl sayısı")] = None,
) -> Dict[str, Any]:
    payload = {
        "revenue": revenue,
        "gross_profit": gross_profit,
        "operating_income": operating_income,
        "net_income": net_income,
        "previous_revenue": previous_revenue,
        "cagr_start_value": cagr_start_value,
        "cagr_end_value": cagr_end_value,
        "cagr_years": cagr_years,
    }
    output = FinancialCalculator.compute_metrics(payload, strict=False)
    return output.model_dump(mode="json")


compute_financial_metrics = compute_metrics_tool


@mcp.tool(name="compare_companies")
def compare_companies_tool(
    tickers: Annotated[
        List[str],
        Field(description="Karşılaştırılacak şirketlerin hisse sembolleri (Örn: ['AAPL', 'MSFT', 'NVDA'])"),
    ],
    metrics: Annotated[
        Optional[List[str]],
        Field(description="Karşılaştırılacak metrikler (Örn: ['revenue', 'growth', 'gross_margin', 'net_margin'])", default=None),
    ] = None,
    years: Annotated[
        Optional[List[int]],
        Field(description="Mali yıllar listesi (Örn: [2022, 2023, 2024])", default=None),
    ] = None,
) -> Dict[str, Any]:
    logger.info("[MCP] compare_companies: tickers=%s, metrics=%s, years=%s", tickers, metrics, years)
    return compare_companies(tickers=tickers, metrics=metrics, years=years)


@mcp.tool()
def fetch_market_data(
    ticker: Annotated[str, Field(description="Borsa hisse sembolü (örn: 'AAPL', 'THYAO.IS')")],
) -> Dict[str, Any]:
    fetcher = MarketDataFetcher()
    return fetcher.fetch(ticker)


def main():
    parser = argparse.ArgumentParser(description="FinSight FastMCP Server")
    parser.add_argument("--sse", action="store_true", help="SSE (HTTP) modunda çalıştır")
    parser.add_argument("--port", type=int, default=8000, help="SSE portu (varsayılan: 8000)")
    args = parser.parse_args()

    if args.sse:
        logger.info("FinSight MCP Sunucusu SSE modunda başlatılıyor (Port: %d)...", args.port)
        mcp.run(transport="sse")
    else:
        logger.info("FinSight MCP Sunucusu stdio modunda başlatılıyor...")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
