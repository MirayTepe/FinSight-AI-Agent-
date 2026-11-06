import yfinance as yf
from decimal import Decimal
from typing import Dict, Any

class MarketDataFetcher:

    @staticmethod
    def fetch_fundamentals(ticker_symbol: str) -> Dict[str, Any]:
        try:
            ticker = yf.Ticker(ticker_symbol.strip().upper())
            
            info = ticker.info
            
            if not info or "regularMarketPrice" not in info and "currentPrice" not in info:
                current_price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
                if not current_price:
                    return {
                        "success": False,
                        "error_code": "TICKER_NOT_FOUND",
                        "message": f"'{ticker_symbol}' sembolü için geçerli piyasa verisi bulunamadı."
                    }
            
            price = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
            eps = info.get("trailingEps") or 0.0
            book_value = info.get("bookValue") or 0.0
            market_cap = info.get("marketCap") or 0
            
            return {
                "success": True,
                "ticker": ticker_symbol.upper(),
                "currency": info.get("currency", "USD"),
                "current_price": Decimal(str(price)),
                "eps": Decimal(str(eps)),
                "book_value_per_share": Decimal(str(book_value)),
                "market_cap": market_cap
            }

        except Exception as e:
            return {
                "success": False,
                "error_code": "MARKET_API_EXCEPTION",
                "message": f"Piyasa verisi çekilirken hata oluştu: {str(e)}. Lütfen daha sonra tekrar deneyin veya alternatif veri kaynağı kullanın."
            }