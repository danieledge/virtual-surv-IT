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


# --- supervision --------------------------------------------------------------------------
#
# The child writes its stream to a FILE rather than to a pipe we hold. That single choice is
# what makes an unattended run survivable: nobody owns the process, so the launcher can be
# closed, crash, or be on the wrong side of an accidental Esc, and the run continues and
# stays readable. A pipe would have made the launcher a single point of failure for work it
# is only supposed to be watching.

import os          # noqa: E402 - grouped with the supervision half, not the decoding half
import subprocess  # noqa: E402
import time        # noqa: E402
import uuid        # noqa: E402

_RUN_DIR = ".headless"
# A run whose stream file has not been touched in this long, with no result event, is not
# running any more - it was killed, the machine slept, or the process died without a word.
# Generous, because a long tool call writes nothing while it works, and a corporate machine
# is slow (the same reason the monitor waits five minutes before suggesting a fault).
_STALE_AFTER = 600.0


def run_dir(project_dir: Path) -> Path:
    return Path(project_dir) / ".claude" / _RUN_DIR


def new_session_id() -> str:
    """A UUID we choose, so the run and the engagement are the same thing by construction."""
    return str(uuid.uuid4())


def start(
    project_dir: Path,
    prompt: str,
    *,
    session_id: str = "",
    budget_usd: float | None = None,
    max_turns: int | None = None,
    permission_mode: str = "dontAsk",
    allowed_tools: tuple[str, ...] = (),
    claude: str = "claude",
    slug: str = "",
) -> dict:
    """Start a headless run detached, streaming to a file. Returns its record.

    Raises OSError if the process cannot be started - the caller must fall back to an
    attended launch rather than report an unattended run that never began. That failure has
    already happened once here, in the windowed launcher, and it is the worst one available:
    a human authorised work that then silently did not happen."""
    project_dir = Path(project_dir)
    session_id = session_id or new_session_id()
    folder = run_dir(project_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stream_path = folder / f"{session_id}.jsonl"
    error_path = folder / f"{session_id}.err"
    argv = build_argv(
        prompt,
        claude=claude,
        session_id=session_id,
        budget_usd=budget_usd,
        max_turns=max_turns,
        permission_mode=permission_mode,
        allowed_tools=allowed_tools,
    )
    kwargs: dict = {"cwd": str(project_dir), "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        # DETACHED_PROCESS is right HERE, unlike the windowed launcher where it was the bug:
        # a headless run wants no console at all, and its output is going to a file anyway.
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True
    with stream_path.open("w", encoding="utf-8") as out, error_path.open(
        "w", encoding="utf-8"
    ) as err:
        proc = subprocess.Popen(argv, stdout=out, stderr=err, **kwargs)  # noqa: S603
    record = {
        "session_id": session_id,
        "slug": slug,
        "pid": proc.pid,
        "started_at": time.time(),
        "stream": str(stream_path),
        "errors": str(error_path),
        # The prompt is NOT recorded here. It is the human's request, it can carry anything,
        # and this file sits in the project - the engagement pack is where the request lives.
        "argv_summary": [a for a in argv if a != prompt],
        "cwd": str(project_dir),
    }
    (folder / f"{session_id}.run.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    return record


def records(project_dir: Path) -> list[dict]:
    """Every headless run recorded for this project, newest first."""
    folder = run_dir(project_dir)
    found = []
    try:
        paths = sorted(folder.glob("*.run.json"))
    except OSError:
        return []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("session_id"):
            found.append(data)
    return sorted(found, key=lambda r: r.get("started_at") or 0, reverse=True)


def latest(project_dir: Path, slug: str = "") -> dict | None:
    """The newest run, optionally for one engagement. None if there is none."""
    for record in records(project_dir):
        if not slug or record.get("slug") == slug:
            return record
    return None


def status(record: dict) -> dict:
    """Run state plus whether it is still going.

    Liveness is judged from the STREAM, not from the operating system. A pid check is
    unreliable across platforms and lies after reuse; the stream cannot: a result event means
    finished, and a file nobody has written to for a long time with no result means the
    process is gone. That also means a run started by a launcher that has since closed is
    still readable, which is the entire point of writing to a file."""
    state = read_file(Path(record.get("stream", "")))
    state["session_id"] = state["session_id"] or str(record.get("session_id") or "")
    state["slug"] = record.get("slug", "")
    state["pid"] = record.get("pid")
    if state["finished"]:
        state["live"] = False
        return state
    try:
        idle = time.time() - Path(record["stream"]).stat().st_mtime
    except (OSError, KeyError, TypeError):
        idle = 0.0
    state["idle_seconds"] = round(idle, 1)
    state["live"] = idle < _STALE_AFTER
    if not state["live"]:
        state["outcome"] = state["outcome"] or "no output for a long time - the run is gone"
    return state


def stop(record: dict, *, hard: bool = False) -> bool:
    """Ask a run to stop. True if a signal was delivered.

    SIGINT by default, because the documented difference matters: SIGINT ENDS THE TURN, while
    SIGTERM leaves it unfinished and records no result for it. An unattended run that is
    stopped should still close its books where it can."""
    pid = record.get("pid")
    if not isinstance(pid, int):
        return False
    import signal

    if os.name == "nt":
        sig = signal.SIGTERM if hard else getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM)
    else:
        sig = signal.SIGTERM if hard else signal.SIGINT
    try:
        os.kill(pid, sig)
        return True
    except (OSError, ValueError, AttributeError):
        return False


def is_alive(pid) -> bool:
    """Best-effort liveness for a pid we do not own. Unknown counts as alive.

    Only used to decide whether to ESCALATE a stop - never to decide whether a run finished,
    which is read from the stream. A pid check lies after reuse and behaves differently on
    every platform; the stream does not."""
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except (OSError, ValueError, AttributeError):
        return True  # cannot tell (Windows, permissions) - assume it is still there


def stop_and_wait(record: dict, timeout: float = 45.0, poll: float = 1.0) -> bool:
    """Stop a run and make sure it is actually gone. True if it exited.

    SIGINT first, then SIGTERM if it outstays the timeout. The wait is not optional and the
    default is generous, because measured live (2026-08-25) the CLI ends the turn and writes
    its result promptly but takes appreciably longer to exit - about a minute in one case.
    Checking at six seconds said "still alive" and would have led someone to escalate, or
    worse, to conclude that stopping does not work."""
    if not stop(record):
        return not is_alive(record.get("pid"))
    deadline = time.time() + max(0.0, timeout)
    while time.time() < deadline:
        if not is_alive(record.get("pid")):
            return True
        time.sleep(poll)
    stop(record, hard=True)
    deadline = time.time() + 10.0
    while time.time() < deadline:
        if not is_alive(record.get("pid")):
            return True
        time.sleep(poll)
    return False
