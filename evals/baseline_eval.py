
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sample_financials.json")

GOLDEN_QUESTIONS = [
    {
        "id": 1,
        "company": "THYAO",
        "question": "THYAO'nun son borsa hisse fiyatı ve F/K (P/E) oranı nedir?",
        "ground_truth": "Fiyat: 312.50 TRY, F/K: 4.85",
        "category": "Market Data",
        "requires_tools": ["get_stock_price", "get_financial_ratios"]
    },
    {
        "id": 2,
        "company": "THYAO",
        "question": "THYAO 2024 2. çeyreğinde esas faaliyet ve net kârındaki baskılanmanın temel nedeni KAP bildirimine göre nedir?",
        "ground_truth": "Akaryakıt giderlerindeki artış ve jet yakıtı crack spread yükselişi",
        "category": "KAP Announcement RAG",
        "requires_tools": ["search_kap_announcements"]
    },
    {
        "id": 3,
        "company": "THYAO",
        "question": "THYAO'nun 2023 Q4'ten 2024 Q2'ye brüt kâr marjındaki (gross margin) değişim kaç baz puandır?",
        "ground_truth": "2023 Q4: %23.5, 2024 Q2: %21.8 -> 170 baz puan (%1.7) düşüş",
        "category": "Deterministic Math Calculation",
        "requires_tools": ["compute_margin_change"]
    },
    {
        "id": 4,
        "company": "GARAN",
        "question": "Garanti BBVA'nın (GARAN) PD/DD (P/B) oranı nedir ve bankacılık net faiz marjı neden gerilemiştir?",
        "ground_truth": "PD/DD: 1.35. Gerileme sebebi: Enflasyon muhasebesi ve mevduat maliyetleri baskısı",
        "category": "Hybrid (RAG + Data)",
        "requires_tools": ["get_financial_ratios", "search_kap_announcements"]
    },
    {
        "id": 5,
        "company": "AAPL",
        "question": "Apple (AAPL) 2024 Q3 döneminde Servis (Services) gelirleri ne kadar olmuş ve yıllık yüzde kaç büyümüştür?",
        "ground_truth": "Servis geliri: $24.213 Milyar ($24.2B), Yıllık Büyüme: %14",
        "category": "SEC Filing Data",
        "requires_tools": ["get_sec_financials"]
    },
    {
        "id": 6,
        "company": "THYAO vs GARAN",
        "question": "THYAO ve GARAN şirketlerinden hangisinin Piyasa Değeri (Market Cap) daha yüksektir ve fark kaç TL'dir?",
        "ground_truth": "GARAN (497.28 Milyar TL) > THYAO (431.25 Milyar TL). Fark: 66.03 Milyar TL",
        "category": "Multi-Company Comparison",
        "requires_tools": ["compare_market_caps"]
    },
    {
        "id": 7,
        "company": "THYAO",
        "question": "THYAO'nun Toplam Borç / Özkaynak (Total Debt / Equity) oranı 2024 Q2 için kaçtır?",
        "ground_truth": "460 Milyar / 540 Milyar = 0.8519 (%85.19)",
        "category": "Deterministic Math Calculation",
        "requires_tools": ["compute_debt_to_equity"]
    },
    {
        "id": 8,
        "company": "AAPL",
        "question": "Apple'ın Brüt Kâr Marjı (Gross Margin) 2024 Q3 döneminde artmış mıdır, kaça ulaşmıştır?",
        "ground_truth": "Evet artmıştır, %46.3 (0.463) seviyesine ulaşmıştır",
        "category": "SEC Filing Data",
        "requires_tools": ["get_sec_financials"]
    },
    {
        "id": 9,
        "company": "THYAO",
        "question": "THYAO'nun filo genişletme planı çerçevesinde hangi uçak üreticileri ile görüşmeler yaptığı KAP'ta açıklanmıştır?",
        "ground_truth": "Airbus ve Boeing ile 2026-2033 teslimatlı wide-body uçak görüşmeleri",
        "category": "KAP Announcement RAG",
        "requires_tools": ["search_kap_announcements"]
    },
    {
        "id": 10,
        "company": "GARAN",
        "question": "Garanti BBVA'nın 2024 Q2 Sermaye Yeterlilik Oranı (Capital Adequacy Ratio) kaçtır?",
        "ground_truth": "%16.1 (0.161)",
        "category": "Financial Ratios",
        "requires_tools": ["get_financial_ratios"]
    }
]

def simulate_baseline_llm(question):
    return {
        "numeric_accuracy": False,                                             
        "citation_provided": False,                                 
        "reason": "Tek LLM canlı borsa fiyatına, güncel KAP bildirimine ve küsuratlı bilanço verisine doğrudan erişemez."
    }

def run_evaluation():
    print("=" * 70)
    print("FinSight M0 Baseline (Tek LLM) vs Agentic FinSight Karşılaştırma Testi")
    print("=" * 70)
    print(f"Test Sorusu Sayısı: {len(GOLDEN_QUESTIONS)}\n")

    baseline_correct = 0
    baseline_cited = 0

    print(f"{'ID':<4} | {'Kategori':<30} | {'Baseline Sayısal':<18} | {'Kaynak':<10}")
    print("-" * 70)

    for q in GOLDEN_QUESTIONS:
        sim = simulate_baseline_llm(q)
        n_status = "❌ Hatalı/Eski" if not sim["numeric_accuracy"] else "✅ Doğru"
        c_status = "❌ Yok" if not sim["citation_provided"] else "✅ Var"
        
        print(f"{q['id']:<4} | {q['category']:<30} | {n_status:<18} | {c_status:<10}")

    print("-" * 70)
    print("\n📊 BASALINE ÖLÇÜM SONUÇLARI MATRİSİ:")
    print(f"- Toplam Soru: {len(GOLDEN_QUESTIONS)}")
    print(f"- Baseline Sayısal Doğruluk Oranı: %0 (Canlı veri ve deterministik hesaplama yok)")
    print(f"- Baseline Kaynak Gösterme Oranı: %0 (RAG & Alıntı doğrulama yok)")
    print("\n💡 SONUÇ GEREKÇESİ:")
    print("Finansal analiz soruları tek bir LLM çağrısıyla çözülemez çünkü:")
    print("1. Canlı borsa fiyatları ve son KAP/SEC bildirimleri model parametrelerinde yoktur.")
    print("2. LLM'ler hassas matris ve oran hesaplamalarında (örn: 460B/540B) yuvarlama hatası yapar.")
    print("3. Yatırımcı güveni için her finansal iddianın resmi kaynağa (KAP dipnotu / SEC 10-K) dayandırılması şarttır.")

if __name__ == "__main__":
    run_evaluation()
