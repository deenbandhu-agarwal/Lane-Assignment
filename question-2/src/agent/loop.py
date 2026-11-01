"""The agent loop: ask the model, run the tools it asks for, repeat, within limits.

Stops on: a final answer, step limit, cost cap, per-step timeout, a repeated
identical tool call (loop), too many malformed tool calls in a row, or a model error.
Every run writes a full trace, whatever the reason it stopped.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypeVar

from agent.budget import Budget, Limits
from agent.models.base import ModelClient
from agent.models.pricing import Price
from agent.safety import detect_injection, wrap_data
from agent.tools.registry import ToolRegistry, ToolResult
from agent.trace import Tracer
from agent.types import Message, ToolCall

T = TypeVar("T")


class StopReason(StrEnum):
    FINAL = "final"
    MAX_STEPS = "max_steps"
    MAX_COST = "max_cost"
    TIMEOUT = "timeout"
    LOOP = "loop_detected"
    MALFORMED = "malformed_tool_calls"
    MODEL_ERROR = "model_error"


STOP_TEXT = {
    StopReason.MAX_STEPS: "I stopped because I reached the step limit before finishing.",
    StopReason.MAX_COST: "I stopped because this run reached its cost limit.",
    StopReason.TIMEOUT: "I stopped because the model took too long to respond.",
    StopReason.LOOP: "I stopped because I was repeating the same action without progress.",
    StopReason.MALFORMED: "I stopped because I kept producing invalid tool calls.",
    StopReason.MODEL_ERROR: "I stopped because the model provider returned an error.",
}


@dataclass(frozen=True)
class RunResult:
    answer: str
    stop_reason: StopReason
    steps: int
    cost_usd: float
    messages: list[Message]
    trace_path: Path


def run_with_timeout(fn: Callable[[], T], timeout_s: float) -> T:
    """Run fn in a worker thread; raise TimeoutError if it takes longer than timeout_s.

    Python cannot kill a thread, so a timed-out call keeps running in the background
    and its result is discarded. Adapters should also set their own HTTP timeouts.
    """
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        return ex.submit(fn).result(timeout=timeout_s)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def canonical_args(raw_args: str) -> str:
    try:
        return json.dumps(json.loads(raw_args), sort_keys=True, separators=(",", ":"))
    except json.JSONDecodeError:
        return raw_args


class Agent:
    def __init__(
        self,
        model: ModelClient,
        tools: ToolRegistry,
        *,
        price: Price,
        trace_dir: Path,
        system_prompt: str = "",
        limits: Limits = Limits(),
    ) -> None:
        self.model = model
        self.tools = tools
        self.price = price
        self.trace_dir = Path(trace_dir)
        self.system_prompt = system_prompt
        self.limits = limits

    def execute_tool(self, call: ToolCall, tracer: Tracer) -> ToolResult:
        # Write tools go through the registry's approval gate; gate decisions land in the trace.
        return self.tools.execute(call, audit=tracer.event)

    # -- the loop ------------------------------------------------------------------

    def run(self, user_input: str, history: Sequence[Message] = ()) -> RunResult:
        tracer = Tracer.new(self.trace_dir)
        tracer.event(
            "run_start",
            model=self.model.model_name,
            limits=self.limits,
            user_input=user_input,
            history_len=len(history),
        )
        messages: list[Message] = []
        if self.system_prompt:
            messages.append(Message("system", self.system_prompt))
        messages += [*history, Message("user", user_input)]
        budget = Budget(self.limits, self.price)
        specs = self.tools.specs()
        write_tools = self.tools.write_tool_names()
        seen: Counter[tuple[str, str]] = Counter()
        malformed_streak = 0
        step = 0

        def finish(reason: StopReason, answer: str = "") -> RunResult:
            text = answer if reason is StopReason.FINAL else STOP_TEXT[reason]
            tracer.event(
                "run_end",
                stop_reason=reason,
                steps=step,
                cost_usd=budget.spent_usd,
                answer=text,
            )
            return RunResult(text, reason, step, budget.spent_usd, messages, tracer.path)

        try:
            while step < self.limits.max_steps:
                if not budget.can_afford_next_call():
                    return finish(StopReason.MAX_COST)
                step += 1

                t0 = time.perf_counter()
                try:
                    reply = run_with_timeout(
                        lambda: self.model.complete(list(messages), specs),
                        self.limits.step_timeout_s,
                    )
                except TimeoutError:
                    tracer.event("model_timeout", step=step, timeout_s=self.limits.step_timeout_s)
                    return finish(StopReason.TIMEOUT)
                except Exception as e:
                    tracer.event("model_error", step=step, error=f"{type(e).__name__}: {e}")
                    return finish(StopReason.MODEL_ERROR)
                latency_ms = (time.perf_counter() - t0) * 1000
                cost = budget.charge(reply.usage)
                tracer.event(
                    "model_call",
                    step=step,
                    prompt=messages,
                    reply=reply,
                    latency_ms=round(latency_ms, 1),
                    input_tokens=reply.usage.input_tokens,
                    output_tokens=reply.usage.output_tokens,
                    cost_usd=cost,
                    total_cost_usd=budget.spent_usd,
                )
                messages.append(reply.to_message())

                if not reply.tool_calls:
                    return finish(StopReason.FINAL, reply.text)

                all_malformed = True
                for call in reply.tool_calls:
                    key = (call.name, canonical_args(call.raw_args))
                    seen[key] += 1
                    if seen[key] >= self.limits.max_repeat_calls:
                        tracer.event("loop_detected", step=step, tool=call.name, count=seen[key])
                        return finish(StopReason.LOOP)

                    t1 = time.perf_counter()
                    try:
                        result = run_with_timeout(
                            lambda c=call: self.execute_tool(c, tracer), self.limits.step_timeout_s
                        )
                    except TimeoutError:
                        result = ToolResult.failure(
                            "timeout", f"tool did not finish within {self.limits.step_timeout_s}s"
                        )
                    tracer.event(
                        "tool_call",
                        step=step,
                        tool=call.name,
                        call_id=call.id,
                        args=call.raw_args,
                        ok=result.ok,
                        error_type=result.error_type,
                        result=result.content,
                        latency_ms=round((time.perf_counter() - t1) * 1000, 1),
                    )
                    all_malformed &= result.malformed
                    flags = detect_injection(result.content, write_tools)
                    if flags:
                        tracer.event("injection_flag", step=step, tool=call.name, flags=flags)
                    messages.append(
                        Message(
                            "tool",
                            wrap_data(call.name, result.content, flags),
                            tool_call_id=call.id,
                            tool_name=call.name,
                        )
                    )

                malformed_streak = malformed_streak + 1 if all_malformed else 0
                if malformed_streak >= self.limits.max_malformed_steps:
                    return finish(StopReason.MALFORMED)

            return finish(StopReason.MAX_STEPS)
        except BaseException as e:  # unexpected bug: still leave a complete trace
            tracer.event("run_end", stop_reason="crash", steps=step, error=f"{type(e).__name__}: {e}")
            raise
        finally:
            tracer.close()
