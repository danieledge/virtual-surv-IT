#!/usr/bin/env python3
"""Build and read a headless Claude Code run (`claude -p --output-format stream-json`).

WHY THIS EXISTS. An unattended engagement has nobody to ask and nobody watching, so the two
things it needs are a hard spend limit and a live account of what it is doing. Both are
published by the CLI in print mode and neither was available to the transcript reader this
replaces: `--max-budget-usd` is an enforced ceiling rather than advisory pacing, and the
event stream reports the session id, the model, per-model cost and the final outcome as
facts rather than inferences.

SCOPE OF THIS MODULE. Argv construction and stream decoding only - it owns no process. That
belongs in the supervisor built on top of it, and keeping them apart means the decoding can
be tested against captured output with no process anywhere near it.

BUILT AGAINST REAL OUTPUT, captured 2026-08-25 from claude 2.1.243, both a success and a
billing failure. Three things came from that capture rather than from the documentation:

  * `subtype` is "success" even when `is_error` is true - a run that failed on a 400 still
    reports subtype success. **`is_error` is the truth**; anything keying on subtype is
    reading the wrong field.
  * `modelUsage` is keyed by the FULL model id (`claude-opus-5[1m]`) and carries `costUSD`
    per model plus `canonicalModel` - so per-model cost AND the suffix normalisation are
    both published. Nothing here needs a rate table.
  * `rate_limit_event` exists as its own top-level type, alongside the documented ones.

Stdlib only, deliberately: the Agent SDK is better ergonomics and is a pip install into an
estate built on vendored dependencies, and it shells out to this same CLI underneath.
"""

from __future__ import annotations

import json
from pathlib import Path

# Never, ever add --bare. It is the documented recommendation for scripted calls and it skips
# hooks, skills, plugins and CLAUDE.md - which disables this entire team, silently, leaving a
# run that looks normal and has none of the guardrails the pre-flight just authorised.
_FORBIDDEN_FLAGS = ("--bare",)


def build_argv(
    prompt: str,
    *,
    claude: str = "claude",
    session_id: str = "",
    budget_usd: float | None = None,
    max_turns: int | None = None,
    permission_mode: str = "dontAsk",
    allowed_tools: tuple[str, ...] = (),
    extra: tuple[str, ...] = (),
) -> list[str]:
    """The command line for one headless run.

    `session_id` is passed in rather than discovered. That is the whole point: the caller
    generates the UUID and records it on the engagement, so the run and the engagement are
    the same thing by construction - no matching a session to a pack afterwards by date or
    by whichever file was modified last.

    `permission_mode` defaults to `dontAsk`, which denies anything outside the allow rules
    and denies AskUserQuestion outright. That is correct here and nowhere else: an
    unattended run's questions were all answered at the pre-flight, so a question it could
    ask now would be one nobody is there to hear."""
    argv = [claude, "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if session_id:
        argv += ["--session-id", session_id]
    if budget_usd is not None:
        # A HARD stop, and subagent spend counts toward it. This is the only layer that can
        # enforce a ceiling; everything above it is a run agreeing to behave.
        argv += ["--max-budget-usd", f"{budget_usd}"]
    if max_turns is not None:
        argv += ["--max-turns", str(max_turns)]
    if permission_mode:
        argv += ["--permission-mode", permission_mode]
    for tool in allowed_tools:
        argv += ["--allowedTools", tool]
    argv += list(extra)
    bad = [f for f in argv if f in _FORBIDDEN_FLAGS]
    if bad:
        raise ValueError(
            f"{bad[0]} disables hooks, skills, plugins and CLAUDE.md - it would run this "
            "engagement without the team, and without the guardrails the pre-flight authorised"
        )
    return argv


def new_state() -> dict:
    """A run that has not started. Every field the monitor reads exists from the outset, so
    a screen never has to distinguish "missing" from "not yet"."""
    return {
        "session_id": "",
        "model": "",
        "version": "",
        "started": False,
        "finished": False,
        "ok": None,          # None while running; True/False once the result arrives
        "outcome": "",       # terminal_reason, or the error category
        "message": "",       # the final text, or the failure
        "cost_usd": 0.0,
        "by_model": {},      # canonical model -> {"cost_usd", "input", "output", "cache_read"}
        "turns": 0,
        "duration_ms": 0,
        "stages": [],        # subagent calls, in order
        "tool_calls": 0,
        "retries": [],
        "rate_limited": False,
        "rate_limit_use": {},   # window -> utilisation, 0..1
        "events": 0,
        "undecodable": 0,
    }


def apply_event(state: dict, event: dict) -> dict:
    """Fold one stream event into the run state. Never raises on content."""
    if not isinstance(event, dict):
        state["undecodable"] += 1
        return state
    state["events"] += 1
    kind, subtype = event.get("type"), event.get("subtype")

    if kind == "system" and subtype == "init":
        state["started"] = True
        state["session_id"] = str(event.get("session_id") or "")
        state["model"] = str(event.get("model") or "")
        state["version"] = str(event.get("claude_code_version") or "")
        return state

    if kind == "system" and subtype == "api_retry":
        # Visible retries are the difference between "slow" and "stuck", which is the
        # question a watcher of an unattended run is actually asking.
        state["retries"].append(
            {
                "attempt": event.get("attempt"),
                "error": str(event.get("error") or ""),
                "status": event.get("error_status"),
                "delay_ms": event.get("retry_delay_ms"),
            }
        )
        return state

    if kind == "rate_limit_event":
        # A STATUS REPORT, not a block. The real payload carries status "allowed" with
        # utilisation figures for the rolling windows, and it arrives on healthy runs -
        # captured live 2026-08-25 on a run that succeeded. Treating its presence as "rate
        # limited" flagged every good run, which is a false alarm that teaches you to ignore
        # the field. Utilisation is worth keeping though: an unattended run drifting toward
        # a window reset is exactly what someone watching it wants told.
        info = event.get("rate_limit_info") or {}
        if isinstance(info, dict):
            state["rate_limited"] = str(info.get("status") or "allowed") != "allowed"
            windows = info.get("unifiedWindows")
            if isinstance(windows, dict):
                state["rate_limit_use"] = {
                    name: row.get("utilization")
                    for name, row in windows.items()
                    if isinstance(row, dict)
                }
        return state

    if kind == "assistant":
        message = event.get("message") or {}
        if event.get("error"):
            # A synthetic assistant message carrying an API failure - model "<synthetic>",
            # seen live on a billing error. Not a turn, and not something to price.
            state["outcome"] = state["outcome"] or str(event.get("error"))
            return state
        _count_tools(state, message, event.get("parent_tool_use_id"))
        return state

    if kind == "result":
        return _apply_result(state, event)
    return state


def _count_tools(state: dict, message: dict, parent: str | None) -> None:
    """Tool calls, and the subagent stages among them.

    `parent_tool_use_id` is what makes the stage tree exact: a message with one belongs to
    the subagent spawned by that call, at any nesting depth. The transcript reader could
    only ever see totals."""
    for block in message.get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        state["tool_calls"] += 1
        name = str(block.get("name") or "")
        if name in ("Agent", "Task"):
            agent_type = ""
            if isinstance(block.get("input"), dict):
                agent_type = str(block["input"].get("subagent_type") or "")
            state["stages"].append(
                {
                    "agent": agent_type or "agent",
                    "tool_use_id": str(block.get("id") or ""),
                    "parent": parent or "",
                    "status": "running",
                }
            )


def _apply_result(state: dict, event: dict) -> dict:
    state["finished"] = True
    # is_error, NOT subtype. A run that failed on a 400 still reports subtype "success"
    # (captured live, 2026-08-25) - keying on subtype would call a failed run a good one.
    state["ok"] = not bool(event.get("is_error"))
    state["outcome"] = str(event.get("terminal_reason") or event.get("stop_reason") or "")
    state["message"] = str(event.get("result") or "")
    state["turns"] = int(event.get("num_turns") or 0)
    state["duration_ms"] = int(event.get("duration_ms") or 0)
    state["session_id"] = state["session_id"] or str(event.get("session_id") or "")
    try:
        state["cost_usd"] = float(event.get("total_cost_usd") or 0.0)
    except (TypeError, ValueError):
        state["cost_usd"] = 0.0
    state["by_model"] = _by_model(event.get("modelUsage"))
    if not state["ok"] and not state["message"]:
        state["message"] = f"failed (HTTP {event.get('api_error_status')})"
    return state


def _by_model(usage) -> dict:
    """Per-model cost and tokens, keyed by CANONICAL model.

    The stream keys this by the full id (`claude-opus-5[1m]`) and hands us `canonicalModel`
    alongside - so the suffix normalisation this repo wrote by hand is published, and the
    published one is the authority."""
    out: dict = {}
    if not isinstance(usage, dict):
        return out
    for model_id, row in usage.items():
        if not isinstance(row, dict):
            continue
        key = str(row.get("canonicalModel") or model_id)
        entry = out.setdefault(
            key, {"cost_usd": 0.0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        )
        try:
            entry["cost_usd"] = round(entry["cost_usd"] + float(row.get("costUSD") or 0.0), 6)
            entry["input"] += int(row.get("inputTokens") or 0)
            entry["output"] += int(row.get("outputTokens") or 0)
            entry["cache_read"] += int(row.get("cacheReadInputTokens") or 0)
            entry["cache_write"] += int(row.get("cacheCreationInputTokens") or 0)
        except (TypeError, ValueError):
            continue
    return out


def read_stream(lines, state: dict | None = None) -> dict:
    """Fold an iterable of stream-json lines into run state.

    Takes an iterable rather than a file or a process so the caller decides where the lines
    come from - a live pipe, a capture, a test. A line that will not decode is counted and
    skipped: the stream is written by another process and a partial write must not end the
    watching."""
    state = new_state() if state is None else state
    for line in lines:
        text = (line or "").strip()
        if not text:
            continue
        try:
            event = json.loads(text)
        except ValueError:
            state["undecodable"] += 1
            continue
        apply_event(state, event)
    return state


def read_file(path: Path, state: dict | None = None) -> dict:
    try:
        with Path(path).open(encoding="utf-8", errors="replace") as handle:
            return read_stream(handle, state)
    except OSError:
        return state if state is not None else new_state()


def summary(state: dict) -> str:
    """One line a human can read, for the launcher and for a log."""
    if not state.get("started"):
        return "not started"
    if not state.get("finished"):
        stages = len(state.get("stages") or [])
        return (
            f"running - {state['tool_calls']} tool call(s), {stages} stage(s), "
            f"{len(state.get('retries') or [])} retry(ies)"
        )
    verdict = "completed" if state.get("ok") else "FAILED"
    return (
        f"{verdict} - {state.get('outcome') or 'no reason given'}, "
        f"{state['turns']} turn(s), ${state['cost_usd']:.4f}"
    )
