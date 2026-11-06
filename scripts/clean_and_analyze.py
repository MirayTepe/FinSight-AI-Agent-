                      

import argparse
import json
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

from src.tools.edgar_cleaner import EdgarFactsCleaner


def main():
    parser = argparse.ArgumentParser(
        description="SEC EDGAR XBRL companyfacts temizleme, etiket birleştirme ve rasyo analizi."
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Doğrudan companyfacts JSON dosya yolu.",
    )
    parser.add_argument(
        "--cik",
        type=str,
        default="0000320193",
        help="10 haneli CIK numarası (varsayılan: 0000320193 - AAPL)",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2015,
        help="Başlangıç mali yılı (FY)",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2026,
        help="Bitiş mali yılı (FY)",
    )
    parser.add_argument(
        "--metrics-yaml",
        type=str,
        default="metrics.yaml",
        help="metrics.yaml dosya yolu",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        help="Sonuçları JSON dosyasına kaydetmek için dosya yolu",
    )

    args = parser.parse_args()

    if args.file:
        file_path = Path(args.file)
    else:
        cik_clean = str(args.cik).zfill(10)
        file_path = ROOT_DIR / "data" / "raw" / cik_clean / f"companyfacts_{cik_clean}.json"

    if not file_path.exists():
        print(f"[HATA] Dosya bulunamadı: {file_path}")
        print("Lütfen önce veriyi indirin veya geçerli bir dosya yolu verin:")
        print("  python scripts/download_edgar.py --tickers AAPL")
        sys.exit(1)

    print(f"\n📂 Veri Yükleniyor: {file_path.name}...")
    with open(file_path, "r", encoding="utf-8") as f:
        facts = json.load(f)

    cleaner = EdgarFactsCleaner(metrics_yaml_path=ROOT_DIR / args.metrics_yaml)
    summary = cleaner.generate_comprehensive_summary(
        facts, start_fy=args.start_year, end_fy=args.end_year
    )

    print("=" * 115)
    print(f"📊 FINSIGHT FİNANSAL TABLO VE RASYOLAR: {summary['entity_name']} (CIK: {summary['cik']})")
    print("=" * 115)
    print(
        f"{'FY':<6} | {'Form':<7} | {'Filed':<10} | {'Gelir (Revenue)':<17} | "
        f"{'Brüt Marj':<9} | {'Faal. Marj':<10} | {'Net Marj':<9} | {'Kaynak XBRL Etiketi'}"
    )
    print("-" * 115)

    for item in summary["yearly_financials"]:
        fy = item["fy"]
        form = item.get("form") or "-"
        filed = item.get("filed") or "-"
        rev = f"${item['revenue']:,.0f}" if item["revenue"] else "-"
        gm = f"%{item['gross_margin_pct']:.2f}" if item["gross_margin_pct"] else "-"
        om = f"%{item['operating_margin_pct']:.2f}" if item["operating_margin_pct"] else "-"
        nm = f"%{item['net_margin_pct']:.2f}" if item["net_margin_pct"] else "-"
        tag = item.get("revenue_tag") or "-"

        print(
            f"{fy:<6} | {form:<7} | {filed:<10} | {rev:>17} | {gm:>9} | {om:>10} | {nm:>9} | {tag}"
        )

    print("-" * 115)
    if summary["cagr_revenue_pct"] is not None:
        print(
            f"📈 Gelir Bileşik Yıllık Büyüme Oranı (CAGR) [{summary['cagr_period']}]: %{summary['cagr_revenue_pct']:.2f}"
        )
    print("=" * 115)

    if args.output_json:
        out_p = Path(args.output_json)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Sonuçlar kaydedildi: {out_p}")


if __name__ == "__main__":
    main()
