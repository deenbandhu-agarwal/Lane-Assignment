"""Provider-neutral message types. The agent loop only ever sees these.

Each model adapter translates them to and from its own SDK format, so a
provider can be swapped without touching the loop, tools or gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    raw_args: str  # JSON text exactly as the model produced it; validated later by the registry


@dataclass(frozen=True)
class Message:
    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None  # set on role="tool": which call this answers
    tool_name: str | None = None  # set on role="tool"
    provider_data: Any = None  # opaque adapter data that must be echoed back (e.g. Gemini thought signatures)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ModelReply:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = Usage()
    provider_data: Any = None

    def to_message(self) -> Message:
        return Message(
            role="assistant",
            content=self.text,
            tool_calls=self.tool_calls,
            provider_data=self.provider_data,
        )
