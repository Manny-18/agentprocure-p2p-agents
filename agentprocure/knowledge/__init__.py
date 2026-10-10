"""Policy & regulation knowledge base (RAG).

Built with LangChain components:
  * MarkdownHeaderTextSplitter cuts the policy manual and regulatory notes into one Document per clause
    (metadata: clause id such as POL-4.2, title, section, source file).
  * BM25ClauseRetriever, a LangChain BaseRetriever over rank_bm25, gives keyword retrieval that works offline.
  * Optionally (RAG_EMBEDDINGS=gemini), an InMemoryVectorStore with Gemini embeddings adds semantic retrieval;
    the two rankings are merged by reciprocal-rank fusion.

Used by: the Policy Advisor agent (question answering with clause citations), the Procurement Analyst
(policy reminders for urgent or sole-source requests) and every agent's findings (each finding code carries
the clause that justifies it).
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_text_splitters import MarkdownHeaderTextSplitter
from rank_bm25 import BM25Okapi

KNOWLEDGE_DIR = Path(__file__).parent
SOURCES = {"procurement_policy.md": "Meridian Procurement Policy v3.2", "regulations.md": "Regulatory notes (as of 10 Oct 2026)"}
CLAUSE_RE = re.compile(r"^((?:POL|REG)-[A-Z]*-?\d+(?:\.\d+)?)\s+(.*)$")

# Which clause justifies each control the agents raise (finding code -> clause id).
CODE_TO_CLAUSE = {
    "QUOTES_INSUFFICIENT": "POL-4.1", "RFQ_REQUIRED": "POL-4.1", "SPLIT_PURCHASE_SUSPECTED": "POL-4.2",
    "SINGLE_SOURCE": "POL-4.3", "SINGLE_SOURCE_WEAK_JUSTIFICATION": "POL-4.3", "SOLE_SOURCE_CLAIMED": "POL-4.3",
    "BUDGET_EXCEEDED": "POL-3.2", "BUDGET_AT_RISK": "POL-3.2", "COST_CENTER_UNKNOWN": "POL-3.2",
    "URGENCY_LANGUAGE": "POL-3.3", "QTY_MISMATCH": "POL-3.1", "CATEGORY_MISMATCH": "POL-3.1",
    "GSTIN_CHECKSUM_INVALID": "REG-GST-3", "GSTIN_FORMAT_INVALID": "REG-GST-3", "GSTIN_STATE_INVALID": "REG-GST-3",
    "GSTIN_MISSING": "POL-5.1", "PAN_MISMATCH": "POL-5.1", "GST_REGISTRATION_INACTIVE": "POL-5.1",
    "VENDOR_NOT_APPROVED": "POL-5.1", "GSTIN_NOT_ON_MASTER": "POL-5.1",
    "BANK_CHANGE_UNVERIFIED": "POL-5.2", "BANK_ON_INVOICE_DIFFERS": "POL-5.2", "PAN_NOT_ON_MASTER": "POL-5.3",
    "PRICE_VARIANCE": "POL-7.1", "QTY_EXCEEDS_ACCEPTED": "POL-7.1", "QTY_EXCEEDS_PO": "POL-7.1",
    "FREIGHT_NOT_AGREED": "POL-7.1", "MISSING_GRN": "POL-7.1", "INVOICE_VENDOR_NOT_PO_VENDOR": "POL-7.1",
    "DUPLICATE_INVOICE": "POL-7.3", "PROBABLE_DUPLICATE": "POL-7.3",
    "WRONG_TAX_TYPE": "REG-GST-2", "TAX_AMOUNT_MISMATCH": "REG-GST-2", "TOTAL_MISMATCH": "REG-GST-2",
    "HSN_UNKNOWN": "REG-GST-1", "IRN_MISSING": "REG-GST-4", "IRN_LATE": "REG-GST-4", "BUYER_GSTIN_WRONG": "REG-GST-5",
    "TDS_HIGHER_RATE_NO_PAN": "REG-IT-2", "MSME_OVERDUE": "REG-MSMED-2",
}

_STOP = set("a an the of to in on for and or is are be by with at as it its this that from can we our i my me do does "
            "what when which who how if any all into than then there their them they you your will should must not no "
            "may only per under over up within about".split())


def tokenize(text: str) -> list[str]:
    """Lower-case words with light stemming, so 'splitting', 'split' and 'splits' meet."""
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in _STOP:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if len(w) > 4 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "aeiou0123456789":
            w = w[:-1]
        out.append(w)
    return out


def load_clauses() -> list[Document]:
    """One Document per ### clause, with clause id, title, section and source in metadata."""
    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=[("#", "document"), ("##", "section"), ("###", "heading")],
                                          strip_headers=True)
    docs: list[Document] = []
    for fname, source in SOURCES.items():
        for d in splitter.split_text((KNOWLEDGE_DIR / fname).read_text(encoding="utf-8")):
            m = CLAUSE_RE.match(d.metadata.get("heading", ""))
            if not m:
                continue                       # document intro or section line without a clause
            d.metadata.update(clause=m.group(1), title=m.group(2), source=source, file=fname)
            docs.append(d)
    return docs


class BM25ClauseRetriever(BaseRetriever):
    """Keyword (BM25) retriever over policy clauses: deterministic, needs no API key."""

    docs: list[Document]
    k: int = 4
    _bm25: BM25Okapi | None = None

    def model_post_init(self, __context) -> None:
        corpus = [tokenize(f"{d.metadata['title']} {d.metadata['title']} {d.metadata['section']} {d.page_content}")
                  for d in self.docs]
        self._bm25 = BM25Okapi(corpus)

    def scored(self, query: str) -> list[tuple[Document, float]]:
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(zip(self.docs, scores), key=lambda x: -x[1])
        return [(d, float(s)) for d, s in ranked if s > 0]

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        return [d for d, _ in self.scored(query)[: self.k]]


class KnowledgeBase:
    def __init__(self, embeddings: str | None = None):
        self.docs = load_clauses()
        self.by_id = {d.metadata["clause"]: d for d in self.docs}
        self.bm25 = BM25ClauseRetriever(docs=self.docs, k=8)
        self.mode = "bm25"
        self.vector = None
        if embeddings == "gemini":
            try:
                from langchain_core.vectorstores import InMemoryVectorStore
                from langchain_google_genai import GoogleGenerativeAIEmbeddings
                model = os.getenv("RAG_EMBED_MODEL", "gemini-embedding-001")
                self.vector = InMemoryVectorStore.from_documents(self.docs, GoogleGenerativeAIEmbeddings(model=model))
                self.mode = f"hybrid (bm25 + {model})"
            except Exception as exc:           # no key, quota or package: keyword search still works
                self.mode = f"bm25 (embeddings unavailable: {type(exc).__name__})"

    def retrieve(self, query: str, k: int = 4) -> list[dict]:
        """Top-k clauses for a query: [{clause, title, source, text, score}], best first."""
        bm = self.bm25.scored(query)
        if self.vector is None:
            ranked = [(d, s) for d, s in bm[:k]]
        else:                                   # reciprocal-rank fusion of keyword and semantic rankings
            try:
                sem = self.vector.similarity_search(query, k=8)
            except Exception:
                sem = []
            fused: dict[str, float] = {}
            for rank, (d, _) in enumerate(bm[:8]):
                fused[d.metadata["clause"]] = fused.get(d.metadata["clause"], 0) + 1 / (60 + rank)
            for rank, d in enumerate(sem):
                fused[d.metadata["clause"]] = fused.get(d.metadata["clause"], 0) + 1 / (60 + rank)
            ranked = [(self.by_id[c], s) for c, s in sorted(fused.items(), key=lambda x: -x[1])[:k]]
        return [{"clause": d.metadata["clause"], "title": d.metadata["title"], "source": d.metadata["source"],
                 "text": d.page_content, "score": round(s, 4)} for d, s in ranked]

    def get(self, clause_id: str) -> dict | None:
        d = self.by_id.get(clause_id)
        if not d:
            return None
        return {"clause": clause_id, "title": d.metadata["title"], "source": d.metadata["source"], "text": d.page_content}


def excerpt(text: str, max_chars: int = 220) -> str:
    first = re.split(r"(?<=[.!?])\s+", text.strip())
    out = ""
    for s in first:
        if len(out) + len(s) > max_chars and out:
            break
        out = f"{out} {s}".strip()
    return out


@lru_cache
def kb() -> KnowledgeBase:
    return KnowledgeBase(embeddings=os.getenv("RAG_EMBEDDINGS", "").strip().lower() or None)


def basis_for(code: str) -> dict | None:
    """The clause that justifies a finding code, with a short excerpt to show the reader."""
    cid = CODE_TO_CLAUSE.get(code)
    clause = kb().get(cid) if cid else None
    if not clause:
        return None
    return {"clause": cid, "title": clause["title"], "excerpt": excerpt(clause["text"])}
