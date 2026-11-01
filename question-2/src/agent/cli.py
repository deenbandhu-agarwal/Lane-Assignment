"""Chat with the agent.

    uv run python -m agent.cli                         # interactive, real Gemini + real GitHub
    uv run python -m agent.cli --ask "question"        # one question, then exit
    uv run python -m agent.cli --offline-github        # real Gemini, in-memory sandbox repo
    uv run python -m agent.cli --mode bm25             # retrieval mode override

Writes always stop for y/N on this terminal.
"""

from __future__ import annotations

import argparse
import sys

from agent.config import Settings
from agent.factory import build_agent
from agent.gate import TerminalApprover
from agent.memory import Memory


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agent")
    p.add_argument("--ask", help="ask one question and exit")
    p.add_argument("--offline-github", action="store_true", help="use the in-memory sandbox repo")
    p.add_argument("--mode", choices=["bm25", "vector", "hybrid"], help="retrieval mode")
    args = p.parse_args(argv)

    settings = Settings.from_env()
    if args.mode:
        settings = Settings(**{**settings.__dict__, "retrieval_mode": args.mode})
    agent = build_agent(settings, approver=TerminalApprover(), offline_github=args.offline_github)
    memory = Memory()

    def ask(question: str) -> None:
        r = agent.run(question, history=memory.history())
        memory.add_turn(r.turn_messages)
        print(f"\n{r.answer}\n")
        print(f"  [{r.stop_reason} | steps {r.steps} | est. ${r.cost_usd:.4f} | trace {r.trace_path}]")

    if args.ask:
        ask(args.ask)
        return 0

    print(f"Ledgerly agent ({settings.model_name}, retrieval={settings.retrieval_mode}). Ctrl-D to quit.")
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if q:
            ask(q)


if __name__ == "__main__":
    sys.exit(main())
