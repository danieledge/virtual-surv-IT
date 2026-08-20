"""The agent loop - owned by virt-surv, not by any provider (POC, 2026-08-20).

This is the file that makes the boundary real. Read it as the answer to "what did the
Claude CLI used to do for us that we now do ourselves?": drive turns, decide whether a
requested tool may run, execute it, feed the result back, stop at a limit, and account
for what it cost.

Three properties are deliberate and tested:

1. **Every tool call passes Policy.check() BEFORE its handler is touched.** A refusal is
   fed back to the model as a tool result, not raised - the model gets to react (and the
   refusal is recorded as evidence), exactly as the guard hooks behave today.
2. **A provider failure leaves engagement state untouched.** The loop owns no state; it
   returns a result and lets the caller persist. `RuntimeUnavailable` propagates cleanly,
   with whatever usage was accrued still readable, so a failed run is a non-event on disk
   rather than a half-written engagement.
3. **max_turns is a hard stop.** Without it the loop is a pathological-cost generator -
   the one failure mode that a framework's "just let it run" default would hide.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .contract import Message, ModelRuntime, Reply, ToolCall, ToolSpec, Usage, now
from .policy import Policy


@dataclass
class RunResult:
    text: str = ""
    messages: list[Message] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    turns: int = 0
    stopped_at_limit: bool = False
    refusals: list[tuple[str, str]] = field(default_factory=list)


def _result_message(call: ToolCall, payload: str) -> Message:
    return Message(role="tool", content=payload, tool_call_id=call.call_id or call.name)


def run(
    runtime: ModelRuntime,
    *,
    prompt: str,
    tools: list[ToolSpec] | None = None,
    policy: Policy | None = None,
    system: str = "",
    max_turns: int = 8,
    timeout_s: float = 120.0,
) -> RunResult:
    """Drive one workflow to completion (or to its turn limit)."""
    tools = list(tools or [])
    by_name = {t.name: t for t in tools}
    policy = policy or Policy(set(by_name))
    messages: list[Message] = [Message(role="user", content=prompt)]
    usage = Usage()
    started = now()

    for turn in range(1, max_turns + 1):
        reply: Reply = runtime.complete(messages, tools, system=system, timeout_s=timeout_s)
        usage = usage.merged(reply.usage)
        messages.append(Message(role="assistant", content=reply.text, tool_calls=reply.tool_calls))
        if not reply.wants_tools:
            usage = usage.merged(Usage(latency_s=now() - started))
            return RunResult(
                text=reply.text,
                messages=messages,
                usage=usage,
                turns=turn,
                refusals=list(policy.refusals),
            )

        for call in reply.tool_calls:
            decision = policy.check(call)
            if not decision.allowed:
                # Refusal is FED BACK, not raised: the model must be able to adapt, and
                # the refusal is evidence. This mirrors how the guard hooks answer today.
                messages.append(
                    _result_message(call, f"REFUSED by virt-surv policy: {decision.reason}")
                )
                continue
            spec = by_name.get(call.name)
            handler = getattr(spec, "handler", None)
            if handler is None:
                messages.append(_result_message(call, "ERROR: tool has no handler"))
                continue
            try:
                output = handler(**(call.arguments or {}))
                payload = output if isinstance(output, str) else json.dumps(output, default=str)
            except Exception as exc:
                # A tool that throws is a normal event, not a run-ending one: the model
                # is told and can choose another route.
                payload = f"ERROR: {type(exc).__name__}: {exc}"
            usage = usage.merged(Usage(tool_calls=1))
            messages.append(_result_message(call, payload))

    usage = usage.merged(Usage(latency_s=now() - started))
    return RunResult(
        text=messages[-1].content if messages else "",
        messages=messages,
        usage=usage,
        turns=max_turns,
        stopped_at_limit=True,
        refusals=list(policy.refusals),
    )
