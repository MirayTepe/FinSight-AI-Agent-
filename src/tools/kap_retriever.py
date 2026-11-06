
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .filing_rag import (
    EdgarFilingRAG,
    FilingChunk,
    FilingHybridIndex,
    SearchResult,
    TenKHtmlParser,
    TenKSectionExtractor,
)

_default_rag_instance: Optional[EdgarFilingRAG] = None


def get_rag_instance() -> EdgarFilingRAG:
    global _default_rag_instance
    if _default_rag_instance is None:
        _default_rag_instance = EdgarFilingRAG()
    return _default_rag_instance


def search_filings(
    query: str,
    ticker: Optional[str] = None,
    fy: Optional[int] = None,
    section: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    rag = get_rag_instance()
    results = rag.search_filings(
        query=query,
        ticker=ticker,
        fy=fy,
        section=section,
        top_k=top_k,
    )
    return [r.to_dict() for r in results]


def get_filing_section(
    ticker: str,
    fy: int,
    section: str,
) -> Optional[str]:
    rag = get_rag_instance()
    return rag.get_filing_section(ticker=ticker, fy=fy, section=section)


__all__ = [
    "EdgarFilingRAG",
    "FilingChunk",
    "FilingHybridIndex",
    "SearchResult",
    "TenKHtmlParser",
    "TenKSectionExtractor",
    "get_rag_instance",
    "search_filings",
    "get_filing_section",
]
