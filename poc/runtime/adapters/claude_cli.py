"""The Claude CLI adapter (POC, 2026-08-20) - the compatibility/reference implementation.

This wraps what the project uses TODAY, so the POC can show both paths driving the same
workflow. It deliberately uses the CLI's headless one-shot mode (`-p`) rather than its
agentic mode, because the whole point of the boundary is that the LOOP is ours: we want
the CLI to answer one turn and return, not to run an agent of its own.

HONEST LIMITATION, stated rather than papered over: `claude -p` is a text-in/text-out
interface. It has no native tool-call protocol we can consume here, so this adapter asks
for a strict JSON envelope and parses it. That is serviceable for a POC and is genuinely
how a text-only provider would have to be driven - but it is weaker than a real
tool-calling API, and a production adapter should target the SDK's structured tool
protocol instead. The fake adapter, not this one, carries the test suite; nothing here
runs in CI, because a test that shells out to a real model is neither hermetic nor free.

Environment discovery is NOT done here. The interpreter/CLI path is expected to arrive
already resolved (the launcher/probe work on dev exists precisely so a model runtime
never has to discover its own environment on a locked-down corporate box).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from ..contract import Message, Reply, RuntimeUnavailable, ToolCall, ToolSpec, Usage, now

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

_ENVELOPE_RULES = (
    "Reply with ONE JSON object and nothing else.\n"
    'To answer: {"text": "<your answer>"}\n'
    'To call a tool: {"tool_calls": [{"name": "<tool>", "arguments": {...}}]}\n'
    "Never wrap it in prose or a code fence."
)


class ClaudeCliRuntime:
    """Reference adapter: one CLI invocation per turn."""

    name = "claude-cli"

    def __init__(
        self,
        *,
        executable: str | None = None,
        model: str = "",
        prefer_subscription: bool = True,
    ) -> None:
        # prefer_subscription (2026-08-20, found live): an ANTHROPIC_API_KEY in the
        # environment TAKES PRECEDENCE over a claude.ai login, so a key with no credit
        # shadows a perfectly good subscription and every call dies with "Credit balance
        # is too low". We unset it for the CHILD process only - the parent environment is
        # never touched - so headless runs use the subscription the human is already
        # signed in with. Set False to force whatever the environment says.
        self._prefer_subscription = prefer_subscription
        # Resolved once, by us, from an already-known environment - never probed per call.
        # None means "find it"; an explicit "" means "there is none" and must NOT fall
        # back to a PATH lookup (caught by a test on a box where claude IS installed -
        # the caller's explicit answer has to win over discovery).
        self._exe = shutil.which("claude") or "" if executable is None else executable
        self._model = model

    @property
    def available(self) -> bool:
        return bool(self._exe)

    def _render(self, messages: list[Message], tools: list[ToolSpec] | None, system: str) -> str:
        parts = []
        if system:
            parts.append(f"SYSTEM:\n{system}")
        if tools:
            declared = [
                {"name": t.name, "description": t.description, "schema": t.schema} for t in tools
            ]
            parts.append("TOOLS AVAILABLE:\n" + json.dumps(declared, indent=2))
            parts.append(_ENVELOPE_RULES)
        for m in messages:
            if m.role == "tool":
                parts.append(f"TOOL RESULT ({m.tool_call_id}):\n{m.content}")
            elif m.role == "assistant" and m.tool_calls:
                names = ", ".join(c.name for c in m.tool_calls)
                parts.append(f"ASSISTANT (requested: {names})")
            elif m.content:
                parts.append(f"{m.role.upper()}:\n{m.content}")
        return "\n\n".join(parts)

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str = "",
        timeout_s: float = 120.0,
    ) -> Reply:
        if not self._exe:
            raise RuntimeUnavailable("claude CLI not found on PATH")
        argv = [self._exe, "-p", self._render(messages, tools, system)]
        if self._model:
            argv += ["--model", self._model]
        started = now()
        child_env = os.environ.copy()
        if self._prefer_subscription:
            child_env.pop("ANTHROPIC_API_KEY", None)
        try:
            proc = subprocess.run(  # fixed argv, shell=False  # nosec B603
                argv,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env=child_env,
                # stdin CLOSED, not inherited: `claude -p` waits ~3s for piped input and
                # then warns, and an inherited terminal stdin can hang the call outright.
                # Found by running the POC demo, not by reading the docs.
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeUnavailable(f"claude CLI timed out after {timeout_s}s") from exc
        except OSError as exc:
            raise RuntimeUnavailable(f"claude CLI could not be run: {exc}") from exc
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()[-3:]
            raise RuntimeUnavailable(f"claude CLI exited {proc.returncode}: {' / '.join(tail)}")
        out = (proc.stdout or "").strip()
        latency = now() - started
        if not tools:
            return Reply(
                text=out,
                usage=Usage(model=self._model or "claude-cli", model_calls=1, latency_s=latency),
                raw=out,
            )
        match = _JSON_BLOCK.search(out)
        if not match:
            # Not a crash: the model answered in prose when an envelope was requested.
            # Treat it as the answer rather than failing the run - but say so in raw.
            return Reply(
                text=out,
                usage=Usage(model=self._model or "claude-cli", model_calls=1, latency_s=latency),
                raw={"unparsed": out},
            )
        try:
            payload = json.loads(match.group(0))
        except ValueError as exc:
            raise RuntimeUnavailable(f"claude CLI returned unparseable JSON: {exc}") from exc
        calls = tuple(
            ToolCall(
                name=c.get("name", ""), arguments=c.get("arguments") or {}, call_id=c.get("id", "")
            )
            for c in (payload.get("tool_calls") or [])
            if c.get("name")
        )
        return Reply(
            text=payload.get("text", ""),
            tool_calls=calls,
            usage=Usage(model=self._model or "claude-cli", model_calls=1, latency_s=latency),
            raw=payload,
        )
