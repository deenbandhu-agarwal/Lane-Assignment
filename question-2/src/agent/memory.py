"""Conversation memory across turns: truncation, not summarization.

- Keep only the last `max_turns` turns (a turn = the user message and everything the
  run added after it).
- In all but the newest `full_turns` turns, tool results are cut to a short preview.
  Tool output is the bulk of the tokens and is the least likely to be needed again;
  the model's own answers (with their citations) are kept in full.
- A turn that stopped mid-way (loop, limit) can end with tool calls that never got a
  result; providers reject that, so a "not executed" result is filled in.

What is lost: details of old tool output (e.g. the full text of a note from 4 turns
ago) and everything older than max_turns. Asking again re-runs the tool, which is
cheap here. Summarization was rejected: it costs a model call per turn and can
silently change facts.
"""

from __future__ import annotations

import json

from agent.types import Message


def repair(turn: list[Message]) -> list[Message]:
    out: list[Message] = []
    for i, m in enumerate(turn):
        out.append(m)
        if m.role == "assistant" and m.tool_calls:
            answered = {
                t.tool_call_id for t in turn[i + 1 :] if t.role == "tool"
            }
            for c in m.tool_calls:
                if c.id not in answered:
                    out.append(
                        Message(
                            "tool",
                            json.dumps({"ok": False, "error": {"type": "not_executed"}}),
                            tool_call_id=c.id,
                            tool_name=c.name,
                        )
                    )
    return out


class Memory:
    def __init__(self, max_turns: int = 6, full_turns: int = 2, preview_chars: int = 300) -> None:
        self.max_turns, self.full_turns, self.preview_chars = max_turns, full_turns, preview_chars
        self._turns: list[list[Message]] = []

    def add_turn(self, messages: list[Message]) -> None:
        self._turns.append(repair(list(messages)))
        self._turns = self._turns[-self.max_turns :]

    def history(self) -> list[Message]:
        out: list[Message] = []
        n = len(self._turns)
        for idx, turn in enumerate(self._turns):
            old = idx < n - self.full_turns
            for m in turn:
                if old and m.role == "tool" and len(m.content) > self.preview_chars:
                    m = Message(
                        "tool",
                        m.content[: self.preview_chars] + " …[older tool output truncated; call the tool again if needed]",
                        tool_call_id=m.tool_call_id,
                        tool_name=m.tool_name,
                    )
                out.append(m)
        return out

    def __len__(self) -> int:
        return len(self._turns)
