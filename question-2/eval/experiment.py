"""Controlled retrieval experiment: BM25-only vs vector-only vs hybrid. No LLM calls.

Same corpus, same chunks, same golden questions, same embedder; only the retrieval
mode changes. The question text itself is the query.

    uv run python eval/experiment.py                 # real bge-small
    uv run python eval/experiment.py --fake-embedder # offline smoke run

Reports recall@5 and MRR on questions with known relevant chunks, and the abstain
rate (no results returned) on unanswerable questions. Questions whose search terms
only exist after another tool call (e.g. "issue #3 mentions an error code") cannot be
answered by searching the question text; they are reported separately, not scored.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.config import Settings
from agent.evaluation import load_golden, recall
from agent.factory import build_embedder
from agent.retrieval.chunker import load_corpus
from agent.retrieval.embedders import FakeEmbedder
from agent.retrieval.index import Mode, Retriever

HERE = Path(__file__).resolve().parent


def mrr(expected: list[str], ranked: list[str]) -> float:
    for i, cid in enumerate(ranked, start=1):
        if cid in expected:
            return 1.0 / i
    return 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake-embedder", action="store_true")
    args = ap.parse_args()
    s = Settings.from_env()
    golden = load_golden(HERE / "golden.yaml")
    chunks = load_corpus(s.corpus_dir)
    embedder = FakeEmbedder() if args.fake_embedder else build_embedder(s)
    retrievers = {m: Retriever(chunks, embedder, mode=m, cache_dir=s.cache_dir / "index") for m in Mode}

    rows = []
    for g in golden:
        if not g.get("chunks") and not g.get("not_found"):
            continue
        needs_tool_first = any(t["name"] != "search_notes" for t in g.get("tools", []))
        row = {"id": g["id"], "category": g["category"], "question": g["question"],
               "expected": g.get("chunks", []), "needs_tool_first": needs_tool_first}
        for m, r in retrievers.items():
            top = [h.chunk.id for h in r.search(g["question"], 5)]
            row[m] = {
                "top5": top,
                "recall": recall(g.get("chunks", []), top),
                "mrr": mrr(g.get("chunks", []), top) if g.get("chunks") else None,
                "abstained": not top,
            }
        rows.append(row)

    tag = "fake" if args.fake_embedder else embedder.name.split("/")[-1]
    out = HERE / "results" / f"retrieval-experiment-{tag}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))

    answerable = [r for r in rows if r["expected"] and not r["needs_tool_first"]]
    excluded = [r["id"] for r in rows if r["needs_tool_first"]]
    unanswerable = [r for r in rows if not r["expected"]]
    lines = [
        f"# Retrieval experiment ({tag}, {len(chunks)} chunks, k=5)",
        "",
        f"{len(answerable)} answerable questions with labelled chunks, {len(unanswerable)} unanswerable. "
        f"Not scored (search terms come from a GitHub tool call first): {', '.join(excluded) or 'none'}.",
        "",
        "| Mode | recall@5 | MRR | full recall (all chunks in top 5) | abstained on unanswerable |",
        "|---|---|---|---|---|",
    ]
    for m in Mode:
        rec = sum(r[m]["recall"] for r in answerable) / len(answerable)
        mr = sum(r[m]["mrr"] for r in answerable) / len(answerable)
        full = sum(1 for r in answerable if r[m]["recall"] == 1.0)
        abst = sum(1 for r in unanswerable if r[m]["abstained"])
        lines.append(f"| {m} | {rec:.3f} | {mr:.3f} | {full}/{len(answerable)} | {abst}/{len(unanswerable)} |")
    lines += ["", "| id | expected | bm25 | vector | hybrid |", "|---|---|---|---|---|"]
    for r in answerable:
        cells = [f"{r[m]['recall']:.2f}" for m in Mode]
        lines.append(f"| {r['id']} | {', '.join(r['expected'])} | " + " | ".join(cells) + " |")
    md = out.with_suffix(".md")
    md.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))
    print(f"-> {md}")


if __name__ == "__main__":
    main()
