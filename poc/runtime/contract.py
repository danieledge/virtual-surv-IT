"""The provider-neutral runtime contract (POC, 2026-08-20).

WHY THIS SHAPE. The question the POC exists to answer is not "which framework?" but
"can virt-surv own the workflow, tools, safety model, state and evidence, leaving the
model provider an interchangeable implementation detail?" That forces one specific
inversion, and it is the whole design:

    THE AGENT LOOP BELONGS TO VIRT-SURV, NOT TO THE PROVIDER.

An adapter answers exactly one question - "given this conversation and these tool
declarations, what does the model say or want to call next?" - and then returns. It never
executes a tool, never decides whether a tool is allowed, never writes engagement state,
never loops. virt-surv reads the reply, asks its own policy whether the requested call is
permitted, executes it if so, appends the result and asks again. That keeps every
safety-critical decision on our side of the boundary even when a provider SDK would
happily take it (CLAUDE.md §7: the model REQUESTS an operation, virt-surv DECIDES).

Everything here is stdlib-only dataclasses on purpose: the contract must not drag a
framework in through the back door, or the POC would be answering a different question.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol


class RuntimeUnavailable(RuntimeError):
    """The provider could not be reached or refused: timeout, transport error, auth,
    rate limit, malformed response. Deliberately ONE exception type - callers must treat
    every provider failure identically (leave state untouched, surface it, carry on),
    and a taxonomy would invite per-provider handling to leak upward."""


@dataclass(frozen=True)
class ToolSpec:
    """A tool offered to the model. `handler` stays on OUR side: the adapter is told the
    name/description/schema so the provider can request it, and never receives anything
    callable."""

    name: str
    description: str
    schema: dict
    handler: Any = None


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict
    call_id: str = ""


@dataclass(frozen=True)
class Message:
    role: str  # "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str = ""


@dataclass(frozen=True)
class Usage:
    """What a run cost, as far as the provider is willing to say.

    Every field is Optional because provider honesty varies and a POC that invents
    numbers is worse than one that admits gaps (the repo has been burned by confident
    fabricated figures twice this month). `cached_input_tokens` is separated from
    `input_tokens` because cache-hit ratio, not raw volume, is what the token work on
    dev actually optimises."""

    model: str = ""
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    model_calls: int = 0
    tool_calls: int = 0
    latency_s: float | None = None
    cost_usd: float | None = None

    def merged(self, other: "Usage") -> "Usage":
        def _add(a, b):
            if a is None and b is None:
                return None
            return (a or 0) + (b or 0)

        return Usage(
            model=other.model or self.model,
            input_tokens=_add(self.input_tokens, other.input_tokens),
            cached_input_tokens=_add(self.cached_input_tokens, other.cached_input_tokens),
            output_tokens=_add(self.output_tokens, other.output_tokens),
            model_calls=self.model_calls + other.model_calls,
            tool_calls=self.tool_calls + other.tool_calls,
            latency_s=_add(self.latency_s, other.latency_s),
            cost_usd=_add(self.cost_usd, other.cost_usd),
        )


@dataclass(frozen=True)
class Reply:
    """One model turn: prose, or tool calls, or both. `raw` keeps whatever the provider
    actually sent so a failure can be diagnosed without re-running it."""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = field(default_factory=Usage)
    raw: Any = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class ModelRuntime(Protocol):
    """What EVERY adapter must provide, and nothing more.

    Note what is absent: no `run_agent`, no `execute_tools`, no session object, no
    state. An adapter that grew those would be quietly taking ownership of the loop,
    which is the thing this contract exists to prevent."""

    name: str

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str = "",
        timeout_s: float = 120.0,
    ) -> Reply:
        """One turn. Raises RuntimeUnavailable on ANY provider-side failure."""
        ...


def now() -> float:
    return time.monotonic()
