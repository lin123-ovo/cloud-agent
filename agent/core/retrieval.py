"""Local BM25 recall, reciprocal rank fusion and optional managed reranking.

Local corpus is the shipped mock_data only; no writes to existing vector collections.
"""

from dataclasses import dataclass
from collections import Counter
from pathlib import Path
from functools import lru_cache
import hashlib
import math
import os
import re
import httpx
from langchain_text_splitters import RecursiveCharacterTextSplitter
from core.runtime import event


@dataclass(frozen=True)
class Passage:
    content: str
    source: str
    title: str = ""

    @property
    def key(self) -> str:
        return hashlib.sha256((self.source + self.content.strip()).encode()).hexdigest()


def tokens(text: str) -> list[str]:
    """Keep model identifiers whole and use Chinese bigrams without extra dependencies."""
    result = re.findall(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", text.lower())
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        result.extend(run[i : i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            result.append(run)
    return result


@lru_cache(maxsize=1)
def corpus() -> tuple[Passage, ...]:
    root = Path(__file__).resolve().parents[2] / "mock_data"
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n## ", "\n### ", "\n\n", "\n", " ", ""],
    )
    passages = []
    for path in sorted(root.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ")
        passages.extend(
            Passage(chunk, path.name, title) for chunk in splitter.split_text(text)
        )
    return tuple(passages)


def lexical_search(query: str, passages=None, k: int = 12) -> list[Passage]:
    """BM25 recall; returns no results for zero lexical evidence."""
    docs = tuple(corpus() if passages is None else passages)
    if not docs or not query.strip():
        return []
    terms = set(tokens(query))
    counts = [Counter(tokens(p.content)) for p in docs]
    lengths = [sum(c.values()) for c in counts]
    avg_len = sum(lengths) / len(docs) or 1
    scores = [0.0] * len(docs)
    for term in terms:
        df = sum(term in c for c in counts)
        idf = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
        for i, c in enumerate(counts):
            tf = c[term]
            if tf:
                scores[i] += (
                    idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * lengths[i] / avg_len))
                )
    order = sorted(range(len(docs)), key=lambda i: (-scores[i], docs[i].key))
    return [docs[i] for i in order[:k] if scores[i] > 0]


def fuse(rankings: list[list[Passage]], k: int = 12) -> list[Passage]:
    """RRF combines rankings without assuming a vector distance metric."""
    scores, docs = {}, {}
    for ranking in rankings:
        seen = set()
        for rank, passage in enumerate(ranking, 1):
            if passage.key in seen:
                continue
            seen.add(passage.key)
            docs[passage.key] = passage
            scores[passage.key] = scores.get(passage.key, 0) + 1 / (60 + rank)
    return [
        docs[key] for key in sorted(scores, key=lambda key: (-scores[key], key))[:k]
    ]


def rerank(query: str, candidates: list[Passage], top_k: int = 3) -> list[Passage]:
    """Optional remote rerank. Failures retain fused order; no business writes are retried.

    Set RERANK_MODEL to enable. Score cutoff must be calibrated on a held-out set.
    """
    model = os.getenv("RERANK_MODEL", "").strip()
    if not model or not candidates:
        return candidates[:top_k]
    try:
        response = httpx.post(
            "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
            headers={"Authorization": "Bearer " + os.environ["DASHSCOPE_API_KEY"]},
            json={
                "model": model,
                "input": {"query": query, "documents": [p.content for p in candidates]},
                "parameters": {"top_n": top_k, "return_documents": False},
            },
            timeout=15,
        )
        response.raise_for_status()
        results = response.json()["output"]["results"]
        cutoff = float(os.getenv("RERANK_MIN_SCORE", "0"))
        ordered = []
        seen = set()
        for row in results:
            index = row["index"]
            score = float(row["relevance_score"])
            if (
                not isinstance(index, int)
                or not 0 <= index < len(candidates)
                or not math.isfinite(score)
            ):
                raise ValueError("Invalid rerank result")
            if score >= cutoff and index not in seen:
                ordered.append(candidates[index])
                seen.add(index)
        event("rerank", status="ok", candidates=len(candidates), returned=len(ordered))
        return ordered[:top_k]
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        event("rerank", status="fallback", error=type(exc).__name__)
        return candidates[:top_k]
