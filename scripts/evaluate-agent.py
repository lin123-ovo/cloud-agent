#!/usr/bin/env python3
"""Reproducible smoke evaluation; model modes explicitly call paid remote APIs."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "agent"), str(ROOT / "app"), str(ROOT)]
from core.retrieval import lexical_search, Passage, fuse, rerank


def retrieval(live=False):
    rows = json.loads((ROOT / "evaluation/retrieval.json").read_text())
    for row in rows:
        start = time.monotonic()
        local = lexical_search(row["query"])
        dense = []
        if live:
            from tools.vector_tool import _get_milvus_store

            results = _get_milvus_store().similarity_search_with_score(
                row["query"], k=12, timeout=10
            )
            dense = [
                Passage(
                    doc.page_content.strip(),
                    Path(doc.metadata.get("source", "Unknown")).name,
                )
                for doc, _ in results
            ]
            row["baseline_dense_hit"] = any(
                p.source == row["source"] and row["evidence"] in p.content
                for p in dense[:3]
            )
        selected = rerank(row["query"], fuse([local, dense])) if live else local[:3]
        row["evidence_hit"] = any(
            p.source == row["source"] and row["evidence"] in p.content for p in selected
        )
        row["sources"] = [p.source for p in selected]
        row["elapsed_ms"] = round((time.monotonic() - start) * 1000)
    return rows


async def routes(limit):
    from agents.orchestrator import OrchestratorAgent

    router = OrchestratorAgent()
    rows = json.loads((ROOT / "evaluation/routing.json").read_text())[:limit]
    for row in rows:
        start = time.monotonic()
        result = await router.route(
            {
                "messages": [tuple(m) for m in row["history"]]
                + [("user", row["query"])],
                "metadata": {},
            }
        )
        decision = result["metadata"]["routing"]
        row["actual"] = decision
        row["correct"] = decision["agent"] == row["agent"] and decision[
            "needs_clarification"
        ] == row.get("needs_clarification", False)
        row["elapsed_ms"] = round((time.monotonic() - start) * 1000)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Call Qwen and dense retrieval (paid)"
    )
    parser.add_argument(
        "--rerank", action="store_true", help="Also call gte-rerank-v2 (paid)"
    )
    parser.add_argument("--route-limit", type=int, default=44)
    parser.add_argument("--output", default="evaluation/latest.json")
    args = parser.parse_args()
    if args.rerank and not args.live:
        parser.error("--rerank requires --live")
    from dotenv import load_dotenv

    load_dotenv(ROOT / "agent/.env")
    if args.rerank:
        os.environ["RERANK_MODEL"] = "gte-rerank-v2"
    report = {
        "scope": "assistant-authored smoke cases, not held-out validation or production accuracy",
        "mode": "live" if args.live else "offline_lexical",
        "retrieval": retrieval(args.live),
    }
    if args.live:
        report["routing"] = asyncio.run(routes(args.route_limit))
    report["summary"] = {
        "retrieval_evidence_hit_at_3": sum(
            r["evidence_hit"] for r in report["retrieval"]
        )
        / len(report["retrieval"])
    }
    if args.live:
        report["summary"]["baseline_dense_evidence_hit_at_3"] = sum(
            r["baseline_dense_hit"] for r in report["retrieval"]
        ) / len(report["retrieval"])
        report["summary"]["routing_contract_accuracy"] = sum(
            r["correct"] for r in report["routing"]
        ) / len(report["routing"])
    if args.live:
        report["summary"]["agent_accuracy"] = sum(
            r["actual"]["agent"] == r["agent"] for r in report["routing"]
        ) / len(report["routing"])
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(output)


if __name__ == "__main__":
    main()
