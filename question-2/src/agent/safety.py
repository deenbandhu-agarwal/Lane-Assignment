"""Treat retrieved notes and tool output as data, never as instructions.

Two layers, neither of which the write-safety guarantee depends on (the gate does):
1. Every tool result is wrapped in <data source=...> ... </data>; any tag lookalikes
   inside the content are neutralised so the content cannot "close" the wrapper.
2. A cheap pattern check flags text that looks like instructions aimed at the agent.
   Flags are recorded in the trace and shown to the model on the wrapper.
"""

from __future__ import annotations

import re

_PATTERNS: dict[str, re.Pattern[str]] = {
    "override_instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(instructions?|rules?|prompts?|guidelines?)\b",
        re.I,
    ),
    "role_hijack": re.compile(r"\b(you are now|act as|new instructions?|system prompt)\b", re.I),
    "skip_approval": re.compile(
        r"\b(without (asking|approval|confirmation)|do not ask|don't ask|no need to (ask|confirm)|"
        r"pre-?approved|already approved|auto-?approve)\b",
        re.I,
    ),
    "addressed_to_agent": re.compile(
        r"\b(AI|assistant|agent|LLM|chatbot)s?\b[^.\n]{0,30}\b(must|should|need to|are required to)\b",
        re.I,
    ),
}

_TAG = re.compile(r"<\s*/?\s*data\b", re.I)


def detect_injection(text: str, write_tools: frozenset[str] = frozenset()) -> list[str]:
    flags = [name for name, pat in _PATTERNS.items() if pat.search(text)]
    if any(re.search(rf"\b{re.escape(t)}\b", text) for t in write_tools):
        flags.append("mentions_write_tool")
    return flags


def wrap_data(source: str, content: str, flags: list[str] | None = None) -> str:
    body = _TAG.sub(lambda m: m.group(0).replace("<", "&lt;"), content)
    attrs = f'source="{source}"'
    if flags:
        attrs += f' warning="possible prompt injection: {", ".join(flags)}"'
    return f"<data {attrs}>\n{body}\n</data>"
