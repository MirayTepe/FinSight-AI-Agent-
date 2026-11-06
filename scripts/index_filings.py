                      

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.tools.filing_rag import EdgarFilingRAG


def main():
    parser = argparse.ArgumentParser(
        description="10-K RAG CLI: Bölüm bazlı hibrit arama (BM25 + Vektör + RRF)."
    )
    parser.add_argument("--query", type=str, help="Arama sorgusu")
    parser.add_argument("--ticker", type=str, default="AAPL", help="Hisse kodu (örn: AAPL)")
    parser.add_argument("--fy", type=int, default=2024, help="Mali yıl filtresi (örn: 2024)")
    parser.add_argument(
        "--section",
        type=str,
        choices=["item_1", "item_1a", "item_7"],
        default=None,
        help="Bölüm filtresi (item_1=Business, item_1a=Risk Factors, item_7=MD&A)",
    )
    parser.add_argument(
        "--get-section",
        type=str,
        choices=["item_1", "item_1a", "item_7"],
        help="Doğrudan tam bölüm metnini getirir (RAG aramasını atlar)",
    )
    parser.add_argument("--top-k", type=int, default=3, help="Döndürülecek sonuç sayısı")

    args = parser.parse_args()

    rag = EdgarFilingRAG()

    sample_text = (
        "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\n"
        "FORM 10-K\n\n"
        "TABLE OF CONTENTS\n"
        "Item 1. Business ........................... Page 1\n"
        "Item 1A. Risk Factors ....................... Page 8\n"
        "Item 7. Management's Discussion ............ Page 25\n\n"
        + ("Introductory regulatory text.\n" * 30)
        + "\nITEM 1. Business\n"
        "Apple Inc. designs, manufactures and markets smartphones, personal computers, tablets, "
        "wearables and accessories, and sells a variety of related services.\n"
        "The Company's fiscal year is the 52- or 53-week period that ends on the last Saturday of September.\n"
        "iPhone is the Company's line of smartphones based on its iOS operating system.\n\n"
        + "\nITEM 1A. Risk Factors\n"
        "The Company's business, results of operations and financial condition can be adversely affected by "
        "unfavorable global economic conditions, international trade disputes, and tariff policies.\n"
        "The Company relies on single-source and limited-source suppliers for components including advanced "
        "semiconductor foundry wafer manufacturing in Asia. Any disruption in Taiwan could cause major delays.\n"
        "Regulatory scrutiny including the European Digital Markets Act (DMA) and US Department of Justice (DOJ) "
        "antitrust lawsuits could force modifications to the App Store business model.\n\n"
        + "\nITEM 1B. Unresolved Staff Comments\nNone.\n\n"
        + "\nITEM 7. Management's Discussion and Analysis of Financial Condition and Results of Operations\n"
        "Total net sales were $394.3 billion in 2024, up 2% compared to 2023.\n"
        "Products net sales were $298.1 billion, while Services net sales reached a new record of $96.2 billion.\n"
        "Gross margin expanded to 46.2%, compared to 44.1% in 2023, driven by services mix and cost savings.\n"
        "Operating income reached $123.2 billion, reflecting strong discipline in research and development.\n\n"
        + "\nITEM 7A. Quantitative and Qualitative Disclosures\nInterest rate management.\n"
    )

    rag.index_filing(
        html_or_text=sample_text,
        ticker=args.ticker,
        form="10-K",
        fy=args.fy,
        accn="0000320193-24-000123",
        url="https://www.sec.gov/edgar/data/320193/000032019324000123/aapl-20240928.htm",
        is_already_clean_text=True,
    )

    if args.get_section:
        sec_text = rag.get_filing_section(args.ticker, args.fy, args.get_section)
        print("=" * 80)
        print(f"📄 BÖLÜM TAM METNİ: {args.ticker} | FY{args.fy} | {args.get_section.upper()}")
        print("=" * 80)
        print(sec_text)
        return

    if not args.query:
        print("[!] Lütfen bir arama sorgusu verin: --query '...'")
        return

    print("=" * 80)
    print(f"🔍 FINSIGHT 10-K RAG HİBRİT ARAMA (RRF: BM25 + Vektör)")
    print(f"   Sorgu: '{args.query}' | Ticker: {args.ticker} | Yıl Filtresi: {args.fy} | Bölüm: {args.section}")
    print("=" * 80)

    results = rag.search_filings(
        query=args.query,
        ticker=args.ticker,
        fy=args.fy,
        section=args.section,
        top_k=args.top_k,
    )

    if not results:
        print("Sonuç bulunamadı.")
        return

    for rank, res in enumerate(results, 1):
        c = res.chunk
        print(f"\n[{rank}] Skor: {res.score:.4f} | BM25 Sırası: {res.bm25_rank} | Vektör Sırası: {res.dense_rank}")
        print(f"    Metadata: {c.ticker} | {c.form} | FY{c.fy} | {c.section_name} | Chunk: {c.chunk_id}")
        print(f"    URL: {c.url}")
        print(f"    Alıntı:\n    \"{c.text}\"")
        print("-" * 80)


if __name__ == "__main__":
    main()

