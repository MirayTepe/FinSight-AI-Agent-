
from __future__ import annotations

import html
import logging
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from bs4 import BeautifulSoup, Comment
from rank_bm25 import BM25Okapi

logger = logging.getLogger("filing_rag")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


@dataclass
class FilingChunk:
    chunk_id: str
    ticker: str
    form: str
    fy: int
    section: str                                         
    section_name: str                                                                     
    text: str
    accn: str
    url: str
    chunk_index: int
    total_chunks: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SearchResult:
    chunk: FilingChunk
    score: float
    bm25_rank: Optional[int] = None
    dense_rank: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.chunk.text,
            "ticker": self.chunk.ticker,
            "form": self.chunk.form,
            "fy": self.chunk.fy,
            "section": self.chunk.section,
            "accn": self.chunk.accn,
            "url": self.chunk.url,
            "score": round(self.score, 4),
            "chunk": self.chunk.to_dict(),
            "bm25_rank": self.bm25_rank,
            "dense_rank": self.dense_rank,
        }


class TenKHtmlParser:

    TAGS_TO_REMOVE = {"script", "style", "noscript", "meta", "link", "head"}

    @classmethod
    def clean_html(cls, html_content: str) -> str:
        if not html_content:
            return ""

        soup = BeautifulSoup(html_content, "html.parser")

        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        for tag in soup.find_all(cls.TAGS_TO_REMOVE):
            tag.decompose()

        for hidden_tag in soup.find_all(name=["ix:hidden", "ix:header"]):
            hidden_tag.decompose()

        for tag in soup.find_all(attrs={"style": True}):
            style = tag.get("style", "").replace(" ", "").lower()
            if "display:none" in style or "visibility:hidden" in style:
                tag.decompose()

        for ix_tag in soup.find_all(name=re.compile(r"^ix:")):
            ix_tag.unwrap()

        for table in soup.find_all("table"):
            table_text = table.get_text()
            digits = sum(c.isdigit() for c in table_text)
            total_chars = max(len(table_text.strip()), 1)
            if digits / total_chars > 0.30:
                table.decompose()
            else:
                table.unwrap()

        for block in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "li", "tr"]):
            block.append("\n")

        text = soup.get_text()
        text = html.unescape(text)

        paragraphs = []
        for p in text.split("\n"):
            p_clean = " ".join(p.split())
            if p_clean:
                paragraphs.append(p_clean)

        return "\n".join(paragraphs)


class TenKSectionExtractor:

    SECTIONS_META = {
        "item_1": "Item 1 (Business)",
        "item_1a": "Item 1A (Risk Factors)",
        "item_7": "Item 7 (MD&A - Management's Discussion and Analysis)",
    }

    ITEM_PATTERNS = {
        "item_1": re.compile(
            r"(?:^|\n)\s*(?:ITEM|Item)\s+1[\.\:\s\—\-]+Business(?!\s+Overview|\s*\.{3,}|\s*\d+\s*$)",
            re.IGNORECASE,
        ),
        "item_1a": re.compile(
            r"(?:^|\n)\s*(?:ITEM|Item)\s+1A[\.\:\s\—\-]+Risk\s+Factors(?!\s*\.{3,}|\s*\d+\s*$)",
            re.IGNORECASE,
        ),
        "item_1b": re.compile(
            r"(?:^|\n)\s*(?:ITEM|Item)\s+1B[\.\:\s\—\-]+Unresolved\s+Staff\s+Comments",
            re.IGNORECASE,
        ),
        "item_2": re.compile(
            r"(?:^|\n)\s*(?:ITEM|Item)\s+2[\.\:\s\—\-]+Properties",
            re.IGNORECASE,
        ),
        "item_7": re.compile(
            r"(?:^|\n)\s*(?:ITEM|Item)\s+7[\.\:\s\—\-]+Management(?:\’|\')?s\s+Discussion\s+and\s+Analysis",
            re.IGNORECASE,
        ),
        "item_7a": re.compile(
            r"(?:^|\n)\s*(?:ITEM|Item)\s+7A[\.\:\s\—\-]+Quantitative\s+and\s+Qualitative\s+Disclosures",
            re.IGNORECASE,
        ),
        "item_8": re.compile(
            r"(?:^|\n)\s*(?:ITEM|Item)\s+8[\.\:\s\—\-]+Financial\s+Statements",
            re.IGNORECASE,
        ),
    }

    @classmethod
    def _find_body_heading(cls, text: str, pattern: re.Pattern, min_offset: int = 1500) -> Optional[int]:
        matches = list(pattern.finditer(text))
        if not matches:
            return None

        if len(matches) == 1:
            return matches[0].start()

        for m in reversed(matches):
            if m.start() >= min_offset:
                return m.start()

        return matches[-1].start()

    @classmethod
    def extract_sections(cls, text: str) -> Dict[str, str]:
        sections: Dict[str, str] = {}

        pos_1 = cls._find_body_heading(text, cls.ITEM_PATTERNS["item_1"], min_offset=2000)
        pos_1a = cls._find_body_heading(text, cls.ITEM_PATTERNS["item_1a"], min_offset=3000)
        pos_1b = cls._find_body_heading(text, cls.ITEM_PATTERNS["item_1b"], min_offset=4000)
        pos_2 = cls._find_body_heading(text, cls.ITEM_PATTERNS["item_2"], min_offset=4000)
        pos_7 = cls._find_body_heading(text, cls.ITEM_PATTERNS["item_7"], min_offset=5000)
        pos_7a = cls._find_body_heading(text, cls.ITEM_PATTERNS["item_7a"], min_offset=6000)
        pos_8 = cls._find_body_heading(text, cls.ITEM_PATTERNS["item_8"], min_offset=7000)

        if pos_1 is not None and pos_1a is not None and pos_1a > pos_1:
            sections["item_1"] = text[pos_1:pos_1a].strip()
        elif pos_1 is not None:
            sections["item_1"] = text[pos_1 : pos_1 + 50000].strip()

        end_1a = pos_1b or pos_2
        if pos_1a is not None and end_1a is not None and end_1a > pos_1a:
            sections["item_1a"] = text[pos_1a:end_1a].strip()
        elif pos_1a is not None:
            sections["item_1a"] = text[pos_1a : pos_1a + 100000].strip()

        end_7 = pos_7a or pos_8
        if pos_7 is not None and end_7 is not None and end_7 > pos_7:
            sections["item_7"] = text[pos_7:end_7].strip()
        elif pos_7 is not None:
            sections["item_7"] = text[pos_7 : pos_7 + 100000].strip()

        return sections


class FilingChunker:

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 150):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_section(
        self,
        text: str,
        ticker: str,
        form: str,
        fy: int,
        section: str,
        accn: str,
        url: str,
    ) -> List[FilingChunk]:
        if not text:
            return []

        chunks: List[FilingChunk] = []
        start = 0
        text_len = len(text)
        idx = 0

        section_name = TenKSectionExtractor.SECTIONS_META.get(section, section.upper())

        while start < text_len:
            end = min(start + self.chunk_size, text_len)

            if end < text_len:
                last_newline = text.rfind("\n", start + self.chunk_size // 2, end)
                last_period = text.rfind(". ", start + self.chunk_size // 2, end)
                cut_point = max(last_newline, last_period)
                if cut_point > start:
                    end = cut_point + 1

            chunk_text = text[start:end].strip()
            if len(chunk_text) >= 50:                                    
                chunk_id = f"{ticker.upper()}_{fy}_{form}_{section}_{idx:04d}"
                chunks.append(
                    FilingChunk(
                        chunk_id=chunk_id,
                        ticker=ticker.upper(),
                        form=form,
                        fy=fy,
                        section=section,
                        section_name=section_name,
                        text=chunk_text,
                        accn=accn,
                        url=url,
                        chunk_index=idx,
                    )
                )
                idx += 1

            start += self.chunk_size - self.chunk_overlap
            if start >= end:
                start = end

        for c in chunks:
            c.total_chunks = len(chunks)

        return chunks


class SimpleDenseVectorEngine:

    def __init__(self):
        self.vocabulary: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self.doc_vectors: List[Dict[int, float]] = []
        self.doc_norms: List[float] = []

    @staticmethod
    def tokenize(text: str) -> List[str]:
        return [w.lower() for w in re.findall(r"\b\w{2,}\b", text)]

    def fit_transform(self, corpus: List[str]) -> None:
        num_docs = len(corpus)
        if num_docs == 0:
            return

        tokenized_corpus = [self.tokenize(doc) for doc in corpus]
        df_counter: Counter[str] = Counter()

        for tokens in tokenized_corpus:
            unique_tokens = set(tokens)
            df_counter.update(unique_tokens)

        self.vocabulary = {term: idx for idx, (term, df) in enumerate(df_counter.items()) if df >= 1}
        self.idf = {
            term: math.log((num_docs + 1) / (df + 1)) + 1.0
            for term, df in df_counter.items()
        }

        self.doc_vectors = []
        self.doc_norms = []

        for tokens in tokenized_corpus:
            tf = Counter(tokens)
            vec: Dict[int, float] = {}
            norm_sq = 0.0
            for term, count in tf.items():
                if term in self.vocabulary:
                    dim = self.vocabulary[term]
                    weight = (1.0 + math.log(count)) * self.idf[term]
                    vec[dim] = weight
                    norm_sq += weight * weight
            self.doc_vectors.append(vec)
            self.doc_norms.append(math.sqrt(norm_sq) if norm_sq > 0 else 1.0)

    def query_similarity(self, query: str) -> List[float]:
        query_tokens = self.tokenize(query)
        q_tf = Counter(query_tokens)
        q_vec: Dict[int, float] = {}
        q_norm_sq = 0.0

        for term, count in q_tf.items():
            if term in self.vocabulary:
                dim = self.vocabulary[term]
                weight = (1.0 + math.log(count)) * self.idf[term]
                q_vec[dim] = weight
                q_norm_sq += weight * weight

        q_norm = math.sqrt(q_norm_sq) if q_norm_sq > 0 else 1.0
        scores: List[float] = []

        for doc_vec, doc_norm in zip(self.doc_vectors, self.doc_norms):
            dot_product = sum(weight * doc_vec.get(dim, 0.0) for dim, weight in q_vec.items())
            sim = dot_product / (q_norm * doc_norm) if (q_norm * doc_norm) > 0 else 0.0
            scores.append(sim)

        return scores


class FilingHybridIndex:

    def __init__(self, rrf_k: int = 60):
        self.rrf_k = rrf_k
        self.chunks: List[FilingChunk] = []
        self.bm25: Optional[BM25Okapi] = None
        self.vector_engine = SimpleDenseVectorEngine()
        self.tokenized_corpus: List[List[str]] = []

    def add_chunks(self, new_chunks: List[FilingChunk]) -> None:
        if not new_chunks:
            return

        self.chunks.extend(new_chunks)
        raw_texts = [c.text for c in self.chunks]

        self.tokenized_corpus = [SimpleDenseVectorEngine.tokenize(t) for t in raw_texts]
        self.bm25 = BM25Okapi(self.tokenized_corpus)

        self.vector_engine.fit_transform(raw_texts)
        logger.info("Hibrit RAG İndeksi güncellendi: Toplam %d chunk.", len(self.chunks))

    def search(
        self,
        query: str,
        ticker: Optional[str] = None,
        fy: Optional[int] = None,
        section: Optional[str] = None,
        top_k: int = 5,
    ) -> List[SearchResult]:
        if not self.chunks or not self.bm25:
            return []

        candidate_indices: List[int] = []
        for idx, chunk in enumerate(self.chunks):
            if ticker and chunk.ticker.upper() != ticker.upper():
                continue
            if fy is not None and chunk.fy != fy:
                continue
            if section and chunk.section.lower() != section.lower():
                continue
            candidate_indices.append(idx)

        if not candidate_indices:
            logger.info("Filtrelere uygun chunk bulunamadı (ticker=%s, fy=%s, section=%s)", ticker, fy, section)
            return []

        q_tokens = SimpleDenseVectorEngine.tokenize(query)
        bm25_scores = self.bm25.get_scores(q_tokens)

        dense_scores = self.vector_engine.query_similarity(query)

        matched_candidates = [
            i for i in candidate_indices
            if (bm25_scores[i] > 0.0 or dense_scores[i] > 0.0)
        ]

        active_indices = matched_candidates if matched_candidates else candidate_indices

        bm25_ranked = sorted(active_indices, key=lambda i: bm25_scores[i], reverse=True)
        bm25_rank_map = {idx: rank + 1 for rank, idx in enumerate(bm25_ranked)}

        dense_ranked = sorted(active_indices, key=lambda i: dense_scores[i], reverse=True)
        dense_rank_map = {idx: rank + 1 for rank, idx in enumerate(dense_ranked)}

        rrf_results: List[Tuple[int, float]] = []
        for idx in active_indices:
            b_score = bm25_scores[idx]
            d_score = dense_scores[idx]
            
            r_bm25 = bm25_rank_map[idx]
            r_dense = dense_rank_map[idx]
            rrf_base = (1.0 / (self.rrf_k + r_bm25)) + (1.0 / (self.rrf_k + r_dense))
            
            if b_score == 0 and d_score == 0:
                final_score = 0.0
            else:
                final_score = rrf_base + float(d_score * 0.1)

            rrf_results.append((idx, final_score))

        rrf_results.sort(key=lambda x: x[1], reverse=True)
        top_candidates = [r for r in rrf_results if r[1] > 0][:top_k]

        results: List[SearchResult] = []
        for idx, score in top_candidates:
            results.append(
                SearchResult(
                    chunk=self.chunks[idx],
                    score=score,
                    bm25_rank=bm25_rank_map.get(idx),
                    dense_rank=dense_rank_map.get(idx),
                )
            )

        return results


class EdgarFilingRAG:

    def __init__(self, raw_data_dir: Optional[Union[str, Path]] = None):
        if raw_data_dir is None:
            root = Path(__file__).resolve().parent.parent.parent
            raw_data_dir = root / "data" / "raw"
        self.raw_data_dir = Path(raw_data_dir)
        self.parser = TenKHtmlParser()
        self.extractor = TenKSectionExtractor()
        self.chunker = FilingChunker()
        self.index = FilingHybridIndex()

        self.sections_store: Dict[Tuple[str, int, str], str] = {}

    def index_filing(
        self,
        html_or_text: str,
        ticker: str,
        form: str = "10-K",
        fy: int = 2024,
        accn: str = "",
        url: str = "",
        is_already_clean_text: bool = False,
    ) -> Dict[str, int]:
        if is_already_clean_text:
            cleaned_text = html_or_text
        else:
            cleaned_text = self.parser.clean_html(html_or_text)

        sections = self.extractor.extract_sections(cleaned_text)
        stats: Dict[str, int] = {}
        all_new_chunks: List[FilingChunk] = []

        for sec_key, sec_text in sections.items():
            self.sections_store[(ticker.upper(), fy, sec_key)] = sec_text

            chunks = self.chunker.chunk_section(
                text=sec_text,
                ticker=ticker,
                form=form,
                fy=fy,
                section=sec_key,
                accn=accn,
                url=url,
            )
            all_new_chunks.extend(chunks)
            stats[sec_key] = len(chunks)

        self.index.add_chunks(all_new_chunks)
        return stats

    def search_filings(
        self,
        query: str,
        ticker: Optional[str] = None,
        fy: Optional[int] = None,
        section: Optional[str] = None,
        top_k: int = 5,
    ) -> List[SearchResult]:
        return self.index.search(
            query=query,
            ticker=ticker,
            fy=fy,
            section=section,
            top_k=top_k,
        )

    def get_filing_section(
        self,
        ticker: str,
        fy: int,
        section: str,
    ) -> Optional[str]:
        key = (ticker.upper(), fy, section.lower())
        return self.sections_store.get(key)

    def index_text(
        self,
        text: str,
        ticker: str,
        form: str = "10-K",
        fy: int = 2024,
        section: str = "general",
        section_name: Optional[str] = None,
        accn: str = "",
        url: str = "",
    ) -> None:
        cid = f"{ticker.upper()}_{fy}_{section}_{len(self.index.chunks)}"
        sec_name = section_name or section
        chunk = FilingChunk(
            chunk_id=cid,
            ticker=ticker.upper(),
            form=form.upper(),
            fy=fy,
            section=section.lower(),
            section_name=sec_name,
            text=text,
            accn=accn,
            url=url,
            chunk_index=0,
            total_chunks=1,
        )
        self.index.add_chunks([chunk])


FilingRAGRetriever = EdgarFilingRAG

