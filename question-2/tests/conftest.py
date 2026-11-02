from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from agent.budget import Limits
from agent.loop import Agent
from agent.models.fake import FakeModelClient
from agent.models.pricing import price_for
from agent.tools.registry import Tool, ToolRegistry


class EchoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    times: int = 1


def echo_tool() -> Tool:
    return Tool(
        name="echo",
        description="Echo text back.",
        args=EchoArgs,
        fn=lambda a: {"echo": a.text * a.times},
    )


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry([echo_tool()])


@pytest.fixture
def make_agent(tmp_path: Path, registry: ToolRegistry):
    def _make(script, *, limits: Limits = Limits(), delay_s: float = 0.0, tools=None) -> Agent:
        return Agent(
            FakeModelClient(script, delay_s=delay_s),
            tools or registry,
            price=price_for("fake"),
            trace_dir=tmp_path / "traces",
            limits=limits,
        )

    return _make
