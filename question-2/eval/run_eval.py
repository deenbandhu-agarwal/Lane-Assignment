"""Run the golden set through the real agent and score it.

    uv run python eval/run_eval.py                        # real Gemini + real sandbox repo
    uv run python eval/run_eval.py --offline-github       # real Gemini, in-memory repo
    uv run python eval/run_eval.py --only s1,m3           # subset
    uv run python eval/run_eval.py --resume eval/results/agent-....jsonl   # continue a run

Writes one JSONL row per question plus a markdown summary to eval/results/.
Approved writes (w1) are deleted again after scoring, so runs do not pile up comments.
Seeded: temperature 0 + SEED from .env.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from agent.config import Settings
from agent.evaluation import load_golden, score, summarize
from agent.factory import build_agent, build_embedder, build_github, build_model, build_retriever
from agent.gate import ScriptedApprover
from agent.trace import read_trace

HERE = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default=str(HERE / "golden.yaml"))
    ap.add_argument("--mode", choices=["bm25", "vector", "hybrid"])
    ap.add_argument("--offline-github", action="store_true")
    ap.add_argument("--only", help="comma-separated question ids")
    ap.add_argument("--resume", help="append to this results file, skipping ids already in it")
    args = ap.parse_args()

    s = Settings.from_env()
    mode = args.mode or s.retrieval_mode
    golden = load_golden(Path(args.golden))
    if args.only:
        wanted = set(args.only.split(","))
        golden = [g for g in golden if g["id"] in wanted]

    out = Path(args.resume) if args.resume else (
        HERE / "results" / f"agent-{s.model_name.replace('/', '_')}-{mode}-{time.strftime('%Y%m%dT%H%M%S')}.jsonl"
    )
    done = set()
    if out.exists():
        done = {json.loads(line)["id"] for line in out.read_text().splitlines() if line.strip()}
    out.parent.mkdir(parents=True, exist_ok=True)

    model = build_model(s)
    github = build_github(s, offline=args.offline_github)
    retriever = build_retriever(s, build_embedder(s), mode)
    print(f"{len(golden)} questions | {s.model_name} | retrieval={mode} | seed={s.seed} -> {out.name}")

    with out.open("a", encoding="utf-8") as f:
        for g in golden:
            if g["id"] in done:
                continue
            approver = ScriptedApprover([bool(g.get("approve", False))] * 5)
            agent = build_agent(
                s, approver=approver, model=model, github=github, retriever=retriever,
                offline_github=args.offline_github,
            )
            t0 = time.perf_counter()
            r = agent.run(g["question"])
            events = read_trace(r.trace_path)
            sc = score(g, r.answer, str(r.stop_reason), events)
            cleaned = cleanup_writes(github, events)
            row = {
                "id": g["id"],
                "category": g["category"],
                "question": g["question"],
                "answer": r.answer,
                "stop_reason": str(r.stop_reason),
                "steps": r.steps,
                "cost_usd": round(r.cost_usd, 6),
                "seconds": round(time.perf_counter() - t0, 1),
                "approvals_asked": len(approver.asked),
                "comments_cleaned_up": cleaned,
                "trace": str(Path(r.trace_path).relative_to(s.trace_dir.parent)),
                **sc,
            }
            f.write(json.dumps(row) + "\n")
            f.flush()
            mark = "PASS" if sc["success"] else "FAIL " + ",".join(k for k, v in sc["checks"].items() if not v)
            print(f"  {g['id']:4s} {mark:40s} steps={r.steps} {row['seconds']}s")

    rows = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    summary = summarize(rows)
    md = out.with_suffix(".md")
    md.write_text(render(summary, rows, s.model_name, mode, s.seed), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"summary -> {md}")
    return 0


def cleanup_writes(github, events) -> int:
    """Delete comments the eval itself posted (reversible write, keeps the sandbox stable)."""
    n = 0
    for e in events:
        if e["event"] == "tool_call" and e["tool"] == "post_issue_comment" and e["ok"]:
            cid = json.loads(e["result"])["data"]["comment_id"]
            if hasattr(github, "delete_issue_comment"):
                github.delete_issue_comment(cid)
                n += 1
    return n


def render(summary, rows, model, mode, seed) -> str:
    lines = [
        f"# Agent eval: {model}, retrieval={mode}, seed={seed}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Task success | {summary['task_success']} ({sum(r['success'] for r in rows)}/{len(rows)}) |",
        f"| Tool-call accuracy | {summary['tool_call_accuracy']} |",
        f"| recall@5 (in agent) | {summary['recall_at_5_in_agent']} |",
        f"| Writes executed | {summary['writes_executed']} |",
        f"| Non-final stops | {summary['non_final_stops']} |",
        f"| Est. cost (paid-tier price) | ${summary['total_cost_usd_est']} |",
        f"| Model steps | {summary['total_steps']} |",
        "",
        "| Category | Passed |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in summary["by_category"].items()],
        "",
        "| id | result | failed checks | steps |",
        "|---|---|---|---|",
    ]
    for r in rows:
        failed = ", ".join(k for k, v in r["checks"].items() if not v) or ""
        lines.append(f"| {r['id']} | {'pass' if r['success'] else 'FAIL'} | {failed} | {r['steps']} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
