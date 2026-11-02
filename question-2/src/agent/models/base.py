"""The model port. Every provider adapter (Gemini, fake, later Anthropic/Ollama) implements it."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from agent.types import Message, ModelReply, ToolSpec


class ModelError(Exception):
    """The provider failed in a way the adapter could not recover from (after its own retries)."""


class ModelClient(Protocol):
    model_name: str

    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> ModelReply:
        """One model call. Returns either final text or one or more tool calls."""
        ...
