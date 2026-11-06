                      

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("edgar_downloader")


class RateLimiter:
    def __init__(self, max_per_second: float = 10.0):
        self.min_interval = 1.0 / max_per_second
        self.last_request_time = 0.0

    def wait(self) -> None:
        elapsed = time.time() - self.last_request_time
        remaining = self.min_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self.last_request_time = time.time()


class EdgarClient:
    SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
    SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik_10}.json"
    SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_10}.json"

    def __init__(
        self,
        user_agent: str,
        cache_dir: Path,
        max_requests_per_sec: float = 9.0,                                            
    ):
        self.user_agent = self._validate_user_agent(user_agent)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.limiter = RateLimiter(max_per_second=max_requests_per_sec)

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": "data.sec.gov",                                                           
        })

    @staticmethod
    def _validate_user_agent(ua: str) -> str:
        ua = ua.strip()
        if not ua:
            raise ValueError(
                "User-Agent boş olamaz! SEC gereksinimi: 'Isim Soyisim email@ornek.com'"
            )
        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", ua)
        if not email_match:
            logger.warning(
                "User-Agent içinde geçerli bir e-posta adresi tespit edilemedi: '%s'. "
                "SEC IP bloklaması uygulayabilir!", ua
            )
        return ua

    def _get_json(self, url: str, cache_file: Path, force_refresh: bool = False) -> Dict[str, Any]:
        if not force_refresh and cache_file.exists():
            logger.info("  [DISK CACHE] %s", cache_file.name)
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Cache dosyası okunamadı, yeniden indiriliyor: %s (%s)", cache_file, e)

        self.limiter.wait()

        if "data.sec.gov" in url:
            self.session.headers["Host"] = "data.sec.gov"
        elif "www.sec.gov" in url:
            self.session.headers["Host"] = "www.sec.gov"

        logger.info("  [SEC GET] %s", url)
        response = self.session.get(url, timeout=15)

        if response.status_code == 403:
            raise PermissionError(
                f"SEC API 403 Forbidden döndü! User-Agent ('{self.user_agent}') geçersiz olabilir veya rate limit aşıldı."
            )
        elif response.status_code == 404:
            raise FileNotFoundError(f"SEC üzerinde kaynak bulunamadı (404): {url}")
        
        response.raise_for_status()
        data = response.json()

        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return data

    def get_ticker_to_cik_mapping(self, force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
        cache_file = self.cache_dir / "company_tickers.json"
        data = self._get_json(self.SEC_TICKERS_URL, cache_file, force_refresh=force_refresh)

        mapping: Dict[str, Dict[str, Any]] = {}
        for item in data.values():
            ticker = str(item.get("ticker", "")).upper()
            if ticker:
                mapping[ticker] = {
                    "cik": int(item["cik_str"]),
                    "cik_10": str(item["cik_str"]).zfill(10),
                    "ticker": ticker,
                    "title": item.get("title", ""),
                }
        logger.info("Toplam %d adet şirket/ticker eşlemesi yüklendi.", len(mapping))
        return mapping

    def download_company_submissions(self, cik_10: str, force_refresh: bool = False) -> Dict[str, Any]:
        url = self.SEC_SUBMISSIONS_URL.format(cik_10=cik_10)
        cache_file = self.cache_dir / cik_10 / f"submissions_{cik_10}.json"
        return self._get_json(url, cache_file, force_refresh=force_refresh)

    def download_company_facts(self, cik_10: str, force_refresh: bool = False) -> Dict[str, Any]:
        url = self.SEC_FACTS_URL.format(cik_10=cik_10)
        cache_file = self.cache_dir / cik_10 / f"companyfacts_{cik_10}.json"
        return self._get_json(url, cache_file, force_refresh=force_refresh)

    def download_filing_document(
        self, cik_10: str, accession: str, primary_doc: str, force_refresh: bool = False
    ) -> Optional[Path]:
        cik_no_zeros = str(int(cik_10))
        accn_no_hyphens = accession.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_no_zeros}/{accn_no_hyphens}/{primary_doc}"
        cache_file = self.cache_dir / cik_10 / f"{accession}_{primary_doc}"

        if not force_refresh and cache_file.exists():
            logger.info("  [DISK CACHE 10-K] %s", cache_file.name)
            return cache_file

        self.limiter.wait()
        self.session.headers["Host"] = "www.sec.gov"
        logger.info("  [SEC GET 10-K HTML] %s", url)
        try:
            response = self.session.get(url, timeout=30)
            if response.status_code == 200:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_file, "w", encoding="utf-8", errors="replace") as f:
                    f.write(response.text)
                return cache_file
            else:
                logger.warning("10-K dokümanı indirilemedi (%s): %s", response.status_code, url)
        except Exception as e:
            logger.warning("10-K indirme hatası (%s): %s", url, e)
        return None


def process_tickers(
    tickers: List[str],
    user_agent: str,
    output_dir: Path,
    target_forms: Optional[List[str]] = None,
    years: int = 5,
    force_refresh: bool = False,
) -> None:
    client = EdgarClient(user_agent=user_agent, cache_dir=output_dir)

    logger.info("SEC Şirket dizini (company_tickers.json) kontrol ediliyor...")
    mapping = client.get_ticker_to_cik_mapping(force_refresh=force_refresh)

    summary_results = []

    for t in tickers:
        ticker = t.strip().upper()
        if not ticker:
            continue

        info = mapping.get(ticker)
        if not info:
            logger.error("Ticker '%s' SEC dizininde bulunamadı! Atlanıyor.", ticker)
            continue

        cik_10 = info["cik_10"]
        title = info["title"]
        logger.info("\n>>> İşleniyor: %s (CIK: %s - %s)", ticker, cik_10, title)

        try:
            sub_data = client.download_company_submissions(cik_10, force_refresh=force_refresh)

            facts_data = client.download_company_facts(cik_10, force_refresh=force_refresh)
            facts_count = len(facts_data.get("facts", {}).get("us-gaap", {}))
            logger.info("    Company Facts: %d adet US-GAAP metriği başarıyla kaydedildi.", facts_count)

            downloaded_docs = 0
            if target_forms:
                recent_filings = sub_data.get("filings", {}).get("recent", {})
                forms_list = recent_filings.get("form", [])
                accn_list = recent_filings.get("accessionNumber", [])
                doc_list = recent_filings.get("primaryDocument", [])

                matching_indices = [i for i, f in enumerate(forms_list) if f in target_forms]
                logger.info("    Filtrelenen formlar (%s) içinden %d adet bildirim bulundu.", ", ".join(target_forms), len(matching_indices))

                for idx in matching_indices[:years]:
                    accn = accn_list[idx]
                    pdoc = doc_list[idx]
                    if accn and pdoc:
                        saved_path = client.download_filing_document(cik_10, accn, pdoc, force_refresh=force_refresh)
                        if saved_path:
                            downloaded_docs += 1

            summary_results.append({
                "ticker": ticker,
                "cik": cik_10,
                "title": title,
                "status": "SUCCESS",
                "folder": str(output_dir / cik_10),
                "downloaded_10k": downloaded_docs,
            })

        except Exception as e:
            logger.error("Hata oluştu (%s - CIK: %s): %s", ticker, cik_10, e)
            summary_results.append({
                "ticker": ticker,
                "cik": cik_10,
                "title": title,
                "status": f"FAILED: {e}",
            })

    print("\n" + "=" * 70)
    print("SEC EDGAR INDIRME OZETI")
    print("=" * 70)
    for res in summary_results:
        print(f"[{res['status'][:7]}] {res['ticker']} (CIK {res['cik']}) - {res['title']}")
        if "folder" in res:
            print(f"         Dosya Yolu: {res['folder']}")
            if res.get("downloaded_10k", 0) > 0:
                print(f"         Indirilen 10-K Raporu: {res['downloaded_10k']} adet")
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="FinSight SEC EDGAR Otomatik Veri İndirici (Submissions & Facts & 10-K)"
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        required=True,
        help="İndirilecek hisse sembolleri (Örn: --tickers AAPL,MSFT,NVDA veya --tickers AAPL MSFT)",
    )
    parser.add_argument(
        "--user-agent",
        type=str,
        default=os.getenv("SEC_USER_AGENT", "FinSightResearch admin@finsight-agent.org"),
        help="SEC zorunlu User-Agent başlığı ('Ad Soyad ornek@eposta.com'). Varsayılan: SEC_USER_AGENT env değişkeni",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/raw",
        help="Ham verilerin kaydedileceği dizin (Varsayılan: data/raw)",
    )
    parser.add_argument(
        "--forms",
        nargs="*",
        default=None,
        help="Filtrelenecek form türleri (Örn: --forms 10-K 10-Q)",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=5,
        help="İndirilecek/analiz edilecek yıl sayısı (Varsayılan: 5)",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Mevcut disk cache dosyalarını yok sayarak SEC'ten yeniden indir",
    )

    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent.parent
    raw_dir = base_dir / args.output_dir

    clean_tickers = []
    for item in args.tickers:
        for t in item.replace(",", " ").split():
            val = t.strip().upper()
            if val and val not in clean_tickers:
                clean_tickers.append(val)

    process_tickers(
        tickers=clean_tickers,
        user_agent=args.user_agent,
        output_dir=raw_dir,
        target_forms=[f.upper() for f in args.forms] if args.forms else None,
        years=args.years,
        force_refresh=args.force_refresh,
    )


if __name__ == "__main__":
    main()
