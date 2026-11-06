
from pathlib import Path
import sys
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.tools.filing_rag import (
    EdgarFilingRAG,
    FilingChunker,
    FilingHybridIndex,
    TenKHtmlParser,
    TenKSectionExtractor,
)


class TestFilingRAG(unittest.TestCase):

    def test_html_and_ixbrl_cleaning(self):
        sample_html = """
        <html>
        <head>
            <style>body { font-family: Arial; }</style>
            <script>console.log("tracking code");</script>
        </head>
        <body>
            <div style="display: none;">Bu gizli metin silinmelidir.</div>
            <ix:hidden>Bu ixbrl gizli blogu da silinmelidir.</ix:hidden>
            
            <p>Apple Inc. designs, manufactures and markets smartphones.</p>
            
            <!-- iXBRL unwrap testi -->
            <p>Our net sales under <ix:nonNumeric name="us-gaap:Revenue">ASC 606</ix:nonNumeric> grew significantly.</p>
            
            <!-- Sayısal Bilanço Tablosu (Silinmeli) -->
            <table>
                <tr><td>Cash</td><td>$10,000</td><td>$15,000</td></tr>
                <tr><td>Debt</td><td>$5,000</td><td>$4,000</td></tr>
            </table>

            <!-- Metinsel Açıklama Tablosu (Metin Olarak Korunmalı) -->
            <table>
                <tr><td>Risk Category</td><td>Operational and Geopolitical</td></tr>
            </table>
        </body>
        </html>
        """

        cleaned = TenKHtmlParser.clean_html(sample_html)

        self.assertNotIn("Bu gizli metin silinmelidir", cleaned)
        self.assertNotIn("ixbrl gizli", cleaned)
        self.assertNotIn("<style>", cleaned)
        self.assertNotIn("console.log", cleaned)
        self.assertNotIn("<ix:nonNumeric", cleaned)

        self.assertIn("Apple Inc. designs, manufactures and markets smartphones.", cleaned)
        self.assertIn("Our net sales under ASC 606 grew significantly.", cleaned)
        self.assertIn("Operational and Geopolitical", cleaned)

        self.assertNotIn("$10,000", cleaned)

    def test_section_extraction_with_toc(self):
        sample_10k_text = (
            "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\n"
            "WASHINGTON, D.C. 20549\n"
            "FORM 10-K\n\n"
            "TABLE OF CONTENTS\n"
            "Item 1. Business ........................................ Page 1\n"
            "Item 1A. Risk Factors .................................... Page 8\n"
            "Item 1B. Unresolved Staff Comments ....................... Page 22\n"
            "Item 7. Management's Discussion and Analysis ............. Page 25\n"
            "Item 7A. Quantitative and Qualitative Disclosures ........ Page 40\n"
            "Item 8. Financial Statements ............................. Page 45\n\n"
            + ("Some introductory filler text about filing regulations.\n" * 50)
            + "\nITEM 1. Business\n"
            "The Company designs, manufactures and markets smartphones, personal computers, tablets, "
            "wearables and accessories, and sells a variety of related services.\n"
            "Our flagship product is the iPhone which drives major recurring revenues globally.\n\n"
            + ("More descriptive business operations details.\n" * 20)
            + "\nITEM 1A. Risk Factors\n"
            "The Company's business and financial condition could be adversely affected by supply chain disruptions "
            "in Asia and international trade disputes involving semiconductor tariffs.\n"
            "Antitrust regulatory investigations in the US and Europe may restrict App Store policies.\n\n"
            + ("Detailed risk factors narrative.\n" * 20)
            + "\nITEM 1B. Unresolved Staff Comments\n"
            "None.\n\n"
            + "\nITEM 7. Management's Discussion and Analysis of Financial Condition and Results of Operations\n"
            "Total net sales were $394.3 billion in 2024, driven by record Services revenue and iPhone growth.\n"
            "Gross margin expanded to 46.2% due to favorable product mix and operational efficiencies.\n\n"
            + ("Detailed MD&A commentary.\n" * 20)
            + "\nITEM 7A. Quantitative and Qualitative Disclosures About Market Risk\n"
            "Interest rate risk is managed through derivative financial instruments.\n"
        )

        sections = TenKSectionExtractor.extract_sections(sample_10k_text)

        self.assertIn("item_1", sections)
        self.assertIn("item_1a", sections)
        self.assertIn("item_7", sections)

        self.assertIn("flagship product is the iPhone", sections["item_1"])
        self.assertNotIn("TABLE OF CONTENTS", sections["item_1"])

        self.assertIn("supply chain disruptions in Asia", sections["item_1a"])
        self.assertIn("Antitrust regulatory investigations", sections["item_1a"])
        self.assertNotIn("Total net sales were $394.3 billion", sections["item_1a"])

        self.assertIn("Total net sales were $394.3 billion in 2024", sections["item_7"])
        self.assertIn("Gross margin expanded to 46.2%", sections["item_7"])
        self.assertNotIn("flagship product is the iPhone", sections["item_7"])

    def test_chunking_and_metadata_enrichment(self):
        chunker = FilingChunker(chunk_size=300, chunk_overlap=50)
        text = (
            "Global trade tensions and tariffs on electronic components may negatively impact operating margins. "
            "Furthermore, single-source component suppliers create vulnerability in our supply chain continuity. "
            "Exchange rate volatility between the US Dollar and Euro could adversely impact foreign sales. "
            "Cybersecurity threats and potential data breaches remain significant operational concerns."
        )

        chunks = chunker.chunk_section(
            text=text,
            ticker="AAPL",
            form="10-K",
            fy=2024,
            section="item_1a",
            accn="0000320193-24-000123",
            url="https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
        )

        self.assertGreaterEqual(len(chunks), 1)
        c0 = chunks[0]

        self.assertEqual(c0.ticker, "AAPL")
        self.assertEqual(c0.form, "10-K")
        self.assertEqual(c0.fy, 2024)
        self.assertEqual(c0.section, "item_1a")
        self.assertEqual(c0.accn, "0000320193-24-000123")
        self.assertIn("https://www.sec.gov", c0.url)
        self.assertIn("AAPL_2024_10-K_item_1a_", c0.chunk_id)

    def test_hybrid_search_bm25_and_vector(self):
        index = FilingHybridIndex(rrf_k=60)
        chunker = FilingChunker(chunk_size=400, chunk_overlap=50)

        chunks_risk = chunker.chunk_section(
            text="Geopolitical risks in Taiwan could disrupt advanced semiconductor foundry wafer production.",
            ticker="AAPL",
            form="10-K",
            fy=2024,
            section="item_1a",
            accn="accn1",
            url="url1",
        )
        chunks_mda = chunker.chunk_section(
            text="Services revenue grew 14% year over year reaching a new all-time revenue record of $96 billion.",
            ticker="AAPL",
            form="10-K",
            fy=2024,
            section="item_7",
            accn="accn1",
            url="url1",
        )

        index.add_chunks(chunks_risk + chunks_mda)

        results = index.search(query="semiconductor foundry wafer production risk", top_k=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].chunk.section, "item_1a")
        self.assertIn("semiconductor", results[0].chunk.text)

        results_mda = index.search(query="Services revenue growth all-time record", top_k=1)
        self.assertEqual(len(results_mda), 1)
        self.assertEqual(results_mda[0].chunk.section, "item_7")
        self.assertIn("Services revenue", results_mda[0].chunk.text)

    def test_anti_hallucination_temporal_and_section_filters(self):
        rag = EdgarFilingRAG()

        text_2023 = (
            "ITEM 1A. Risk Factors\n"
            "In fiscal 2023, COVID-19 related factory lockdowns in Zhengzhou materially affected iPhone 14 Pro shipments.\n"
            "ITEM 1B. Unresolved Staff Comments\n"
        )
        rag.index_filing(
            html_or_text=text_2023,
            ticker="AAPL",
            form="10-K",
            fy=2023,
            is_already_clean_text=True,
        )

        text_2024 = (
            "ITEM 1A. Risk Factors\n"
            "In fiscal 2024, regulatory scrutiny under the European Digital Markets Act (DMA) required alternative app store support.\n"
            "ITEM 1B. Unresolved Staff Comments\n"
        )
        rag.index_filing(
            html_or_text=text_2024,
            ticker="AAPL",
            form="10-K",
            fy=2024,
            is_already_clean_text=True,
        )

        res_2024 = rag.search_filings(
            query="factory lockdowns and regulatory scrutiny",
            ticker="AAPL",
            fy=2024,
            section="item_1a",
        )
        self.assertTrue(len(res_2024) > 0)
        self.assertEqual(res_2024[0].chunk.fy, 2024)
        self.assertIn("Digital Markets Act", res_2024[0].chunk.text)
        self.assertNotIn("Zhengzhou", res_2024[0].chunk.text)

        res_2023 = rag.search_filings(
            query="factory lockdowns in Zhengzhou",
            ticker="AAPL",
            fy=2023,
            section="item_1a",
        )
        self.assertTrue(len(res_2023) > 0)
        self.assertEqual(res_2023[0].chunk.fy, 2023)
        self.assertIn("Zhengzhou", res_2023[0].chunk.text)
        self.assertNotIn("Digital Markets Act", res_2023[0].chunk.text)

        res_leak_check = rag.search_filings(
            query="European Digital Markets Act",
            ticker="AAPL",
            fy=2023,
            section="item_1a",
        )
        for r in res_leak_check:
            self.assertEqual(r.chunk.fy, 2023)

        full_sec = rag.get_filing_section(ticker="AAPL", fy=2024, section="item_1a")
        self.assertIsNotNone(full_sec)
        self.assertIn("Digital Markets Act", full_sec)


if __name__ == "__main__":
    unittest.main()
