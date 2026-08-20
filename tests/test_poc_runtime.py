"""POC runtime boundary tests (2026-08-20) - no credentials, no network, no CLI.

These test the CLAIM, not the plumbing: that virt-surv owns the loop, the tool decisions,
the turn limit and the accounting, and that the provider is interchangeable. If these pass
against a purely local fake, the workflow genuinely does not depend on Claude or its CLI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from poc.runtime import Message, Policy, Reply, RuntimeUnavailable, ToolCall, ToolSpec, Usage, run
from poc.runtime.adapters.fake import FakeRuntime
from poc.workflow_review import ReviewContext, build_tools, review


def _tool(name="read_file", handler=None, required=("path",)):
    return ToolSpec(
        name=name,
        description="test tool",
        schema={"type": "object", "properties": {"path": {"type": "string"}}},
        handler=handler or (lambda **kw: f"read:{kw.get('path', '')}"),
    )


def _call(name="read_file", **args):
    return ToolCall(name=name, arguments=args, call_id="c1")


# --- the loop is ours ----------------------------------------------------------------


def test_tool_call_then_continuation_produces_a_final_answer():
    """The full shape: model asks for a tool, virt-surv runs it, feeds the result back,
    model answers. The provider never executed anything itself."""
    rt = FakeRuntime(
        [
            Reply(tool_calls=(_call(path="a.py"),)),
            Reply(text="verdict: fine"),
        ]
    )
    result = run(rt, prompt="review", tools=[_tool()])
    assert result.text == "verdict: fine"
    assert result.turns == 2
    assert any(m.role == "tool" and m.content == "read:a.py" for m in result.messages)


def test_tool_result_is_fed_back_to_the_model():
    rt = FakeRuntime([Reply(tool_calls=(_call(path="x.py"),)), Reply(text="done")])
    run(rt, prompt="go", tools=[_tool()])
    second_turn = rt.calls[1]
    assert any(m.role == "tool" for m in second_turn), "the model never saw the tool result"


def test_max_turns_is_a_hard_stop():
    """A model that keeps asking for tools must not run forever - the pathological-cost
    failure mode a framework's 'just let it run' default would hide."""
    rt = FakeRuntime([Reply(tool_calls=(_call(path="a.py"),)) for _ in range(20)])
    result = run(rt, prompt="go", tools=[_tool()], max_turns=3)
    assert result.stopped_at_limit and result.turns == 3


# --- virt-surv decides, the model requests -------------------------------------------


def test_undeclared_tool_is_refused_and_never_executed():
    executed = []
    rt = FakeRuntime([Reply(tool_calls=(_call(name="rm_rf"),)), Reply(text="ok")])
    result = run(rt, prompt="go", tools=[_tool(handler=lambda **kw: executed.append(kw))])
    assert executed == [], "a tool outside the declared set was executed"
    assert any("not declared" in reason for _name, reason in result.refusals)


def test_raw_data_argument_is_refused():
    """CLAUDE.md §5: data/raw/ never reaches a model, and the decision is ours - no
    provider or framework is consulted."""
    executed = []
    rt = FakeRuntime(
        [
            Reply(tool_calls=(_call(path="data/raw/trades.csv"),)),
            Reply(text="ok"),
        ]
    )
    result = run(rt, prompt="go", tools=[_tool(handler=lambda **kw: executed.append(kw))])
    assert executed == []
    assert any("data/raw" in reason for _n, reason in result.refusals)


def test_refusal_is_fed_back_not_raised():
    """The model must be able to adapt to a refusal, exactly as it does with the guard
    hooks today - a refusal is a tool result, not an exception."""
    rt = FakeRuntime([Reply(tool_calls=(_call(name="nope"),)), Reply(text="fine, moving on")])
    result = run(rt, prompt="go", tools=[_tool()])
    assert result.text == "fine, moving on"
    assert any("REFUSED" in m.content for m in result.messages if m.role == "tool")


def test_policy_blocks_workspace_escape(tmp_path):
    policy = Policy({"read_file"}, workspace=tmp_path)
    assert policy.check(_call(path="inside.py")).allowed
    assert not policy.check(_call(path="../../etc/passwd")).allowed


# --- provider failures ---------------------------------------------------------------


def test_provider_timeout_surfaces_and_writes_nothing(tmp_path):
    """A failed provider call must be a non-event on disk: the loop owns no state, so
    there is nothing half-written to clean up."""
    before = sorted(p.name for p in tmp_path.iterdir())
    rt = FakeRuntime([RuntimeUnavailable("timed out")])
    with pytest.raises(RuntimeUnavailable):
        run(rt, prompt="go", tools=[_tool()])
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_malformed_provider_response_is_a_runtime_failure():
    rt = FakeRuntime([{"not": "a reply"}])
    with pytest.raises(RuntimeUnavailable):
        run(rt, prompt="go", tools=[_tool()])


def test_tool_error_does_not_end_the_run():
    """A throwing tool is a normal event: the model is told and picks another route."""

    def _boom(**kwargs):
        raise ValueError("disk on fire")

    rt = FakeRuntime([Reply(tool_calls=(_call(path="a.py"),)), Reply(text="recovered")])
    result = run(rt, prompt="go", tools=[_tool(handler=_boom)])
    assert result.text == "recovered"
    assert any("ValueError" in m.content for m in result.messages if m.role == "tool")


# --- usage accounting -----------------------------------------------------------------


def test_usage_accumulates_across_turns_and_counts_tools():
    rt = FakeRuntime(
        [
            Reply(
                tool_calls=(_call(path="a.py"),), usage=Usage(input_tokens=100, output_tokens=10)
            ),
            Reply(
                text="done", usage=Usage(input_tokens=150, cached_input_tokens=90, output_tokens=20)
            ),
        ]
    )
    result = run(rt, prompt="go", tools=[_tool()])
    assert result.usage.input_tokens == 250
    assert result.usage.cached_input_tokens == 90
    assert result.usage.output_tokens == 30
    assert result.usage.model_calls == 2
    assert result.usage.tool_calls == 1
    assert result.usage.model == "fake-model-1"


def test_usage_keeps_none_when_a_provider_reports_nothing():
    """Providers differ in what they disclose; the POC must not invent numbers."""
    rt = FakeRuntime([Reply(text="hi", usage=Usage(model_calls=1))])
    result = run(rt, prompt="go")
    assert result.usage.input_tokens is None and result.usage.cost_usd is None


# --- adapter interchangeability (the actual claim) ------------------------------------


def test_the_same_workflow_runs_against_a_non_cli_runtime(tmp_path):
    """The headline: a real workflow, unchanged, driven end to end by a runtime that is
    not Claude and not a CLI."""
    (tmp_path / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    ctx = ReviewContext.discover(tmp_path)
    rt = FakeRuntime(
        [
            Reply(tool_calls=(ToolCall(name="list_files", arguments={}, call_id="1"),)),
            Reply(
                tool_calls=(ToolCall(name="read_file", arguments={"path": "mod.py"}, call_id="2"),)
            ),
            Reply(text="verdict: small and fine"),
        ]
    )
    result = review(rt, ctx)
    assert result.text == "verdict: small and fine"
    assert result.usage.tool_calls == 2
    contents = [m.content for m in result.messages if m.role == "tool"]
    assert any("mod.py" in c for c in contents)
    assert any("def f()" in c for c in contents)


def test_workflow_imports_no_provider():
    """Provider-specific code must stay behind the adapter: if the workflow module ever
    imports one, the boundary has leaked.

    Checks IMPORTS via ast rather than grepping the text - the first version grepped for
    vendor names and failed on this module's own docstring, which names them precisely to
    explain that the code does not."""
    import ast

    tree = ast.parse(Path("poc/workflow_review.py").read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    banned = ("anthropic", "openai", "claude", "adapters", "subprocess", "httpx", "requests")
    for name in imported:
        assert not any(b in name.lower() for b in banned), f"workflow imports {name!r}"


def test_cli_adapter_satisfies_the_contract_without_being_run():
    """The CLI adapter is the reference implementation - importable and shaped like every
    other adapter. It is NOT exercised here: a test that shells out to a real model is
    neither hermetic nor free."""
    from poc.runtime.adapters.claude_cli import ClaudeCliRuntime

    rt = ClaudeCliRuntime(executable="")
    assert rt.name == "claude-cli" and hasattr(rt, "complete")
    assert not rt.available
    with pytest.raises(RuntimeUnavailable):
        rt.complete([Message(role="user", content="hi")])


def test_context_discovery_happens_before_any_model_call(tmp_path):
    """Deterministic environment discovery stays outside the LLM (the launcher/probe
    principle): the file list exists before a runtime is even constructed."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    ctx = ReviewContext.discover(tmp_path)
    assert set(ctx.files) == {"a.py", "b.py"}
    handlers = {t.name: t.handler for t in build_tools(ctx)}
    assert json.loads(handlers["list_files"]()) == sorted(ctx.files)
