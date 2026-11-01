"""Scripted model for offline tests. No network, fully deterministic.

What it proves: the loop, limits, registry, gate and trace behave correctly for a
given sequence of model outputs (including hostile or broken ones).
What it does not prove: that a real model picks good tools or writes good answers.
"""

from __future__ import annotations

import itertools
import json
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from agent.types import Message, ModelReply, ToolCall, ToolSpec, Usage

Step = ModelReply | Callable[[Sequence[Message]], ModelReply]

DEFAULT_USAGE = Usage(input_tokens=100, output_tokens=20)
_ids = itertools.count(1)


def call(name: str, args: dict[str, Any] | str | None = None, *, id: str | None = None) -> ToolCall:
    """A tool call. Pass a str for args to simulate malformed JSON."""
    raw = args if isinstance(args, str) else json.dumps(args or {})
    return ToolCall(id=id or f"call_{next(_ids)}", name=name, raw_args=raw)


def tool_reply(*calls: ToolCall, usage: Usage = DEFAULT_USAGE) -> ModelReply:
    return ModelReply(tool_calls=tuple(calls), usage=usage)


def text_reply(text: str, usage: Usage = DEFAULT_USAGE) -> ModelReply:
    return ModelReply(text=text, usage=usage)


class FakeModelClient:
    model_name = "fake"

    def __init__(self, script: Iterable[Step], *, delay_s: float = 0.0) -> None:
        self._script = iter(script)
        self.delay_s = delay_s
        self.calls: list[list[Message]] = []  # every prompt it was sent, for assertions

    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> ModelReply:
        self.calls.append(list(messages))
        if self.delay_s:
            time.sleep(self.delay_s)
        try:
            step = next(self._script)
        except StopIteration:
            raise AssertionError("fake model script exhausted") from None
        return step(messages) if callable(step) else step
