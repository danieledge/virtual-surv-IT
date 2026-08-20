"""One representative workflow, provider-agnostic (POC, 2026-08-20).

A miniature review: read the changed files, look at one of them, produce a verdict. It is
the smallest thing that still exercises the full shape the brief asks to prove -

    launch -> context -> model invocation -> tool call -> tool result -> continuation ->
    final result/evidence

- and, crucially, it is written ONCE and runs against ANY adapter. Nothing below names
Claude, the CLI, a provider or an SDK. That is the claim being tested: swapping the model
runtime is a one-line change at the call site, not a rewrite of the workflow.

Tools are supplied by virt-surv with their handlers attached on our side; the model only
ever learns their names and schemas. Evidence (usage, refusals, turns) is returned rather
than written, so the caller owns persistence and a failed run touches no state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .runtime import Policy, RunResult, ToolSpec, run

SYSTEM = (
    "You are a code reviewer working inside a controlled engagement runtime. "
    "Use the supplied tools to inspect the code before judging it. "
    "Never guess at file contents you have not read."
)


@dataclass
class ReviewContext:
    """Everything the workflow needs, resolved BEFORE the model is involved.

    The environment (workspace, file list) is discovered by deterministic code, exactly as
    the launcher/probe does on dev - a model runtime should never have to work out where
    it is running, least of all on a locked-down corporate box."""

    workspace: Path
    files: tuple[str, ...]

    @classmethod
    def discover(cls, workspace: Path, patterns: tuple[str, ...] = ("*.py",)) -> "ReviewContext":
        found: list[str] = []
        for pattern in patterns:
            found += [
                str(p.relative_to(workspace))
                for p in sorted(workspace.rglob(pattern))
                if p.is_file()
            ]
        return cls(workspace=workspace, files=tuple(found))


def build_tools(ctx: ReviewContext) -> list[ToolSpec]:
    """The tool set, with handlers bound on OUR side of the boundary."""

    def list_files() -> str:
        return json.dumps(list(ctx.files))

    def read_file(path: str) -> str:
        # Policy has already decided this call is permitted; this still resolves inside
        # the workspace, because defence in depth is cheaper than an incident.
        target = (ctx.workspace / path).resolve()
        if ctx.workspace.resolve() not in target.parents:
            return "ERROR: outside the workspace"
        try:
            return target.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError as exc:
            return f"ERROR: {exc}"

    return [
        ToolSpec(
            name="list_files",
            description="List the files in scope for this review.",
            schema={"type": "object", "properties": {}},
            handler=list_files,
        ),
        ToolSpec(
            name="read_file",
            description="Read one in-scope file.",
            schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=read_file,
        ),
    ]


def review(runtime, ctx: ReviewContext, *, max_turns: int = 6) -> RunResult:
    """Run the workflow against ANY ModelRuntime. Raises RuntimeUnavailable on provider
    failure, having written nothing - the caller decides what to persist."""
    tools = build_tools(ctx)
    policy = Policy({t.name for t in tools}, workspace=ctx.workspace)
    prompt = (
        f"Review this change. Files in scope: {len(ctx.files)}. "
        "Inspect what you need, then give a one-paragraph verdict."
    )
    return run(
        runtime,
        prompt=prompt,
        tools=tools,
        policy=policy,
        system=SYSTEM,
        max_turns=max_turns,
    )
