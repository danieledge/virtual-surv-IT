#!/usr/bin/env python3
"""What the team actually did: stages, models, cost and loops, from a session transcript.

WHY THIS EXISTS. An engagement's shape - which specialist ran, on which model, what it cost,
and how many times the work looped back - was visible nowhere. The orchestrator could
describe it afterwards from memory, which is exactly the kind of claim this repo does not
accept anywhere else. Every figure here is read from the transcript Claude Code already
writes, so the account is evidenced rather than recalled.

WHAT IS MEASURED AND WHAT IS NOT. Token counts, models, durations, tool stats and outcomes
are 📊 OBSERVED - read from the file. Money is 🧠 INFERRED: tokens priced through
scripts/dashboard.py's rate table - the SAME one `budget-status` measures an unattended run
against, deliberately, so the workflow view and the spend ceiling can never report different
costs for the same run. The distinction is carried through every field name and every
renderer, because a number that looks like a bill invites being treated as one.

FOR THE SESSION TOTAL, `/cost` IN CLAUDE CODE IS THE AUTHORITY and is not restated here.
Claude Code records cost nowhere on disk (verified 2026-08-25), so per-stage figures cannot
borrow it - and a session total is not the question anyway: `/cost` cannot say what the
second review pass cost, and raw tokens cannot either, since an opus output token is several
times a haiku one. Apportioning across stages is the only reason prices appear here.

THE LIMIT THAT SHAPED THE DESIGN. A subagent's internal turns are NOT in the parent
transcript - verified 2026-08-25 across all 465 transcripts on the author's machine, zero
sidechain records. Only the totals return, on the tool result. So a stage is the atom here:
exact totals, no drill-down into its turns, and no pretence of one.

STABILITY. The transcript is Claude Code's internal file, not a public API, and its shape can
change without notice. Every field access is defensive, every failure resolves to a
displayable state, and tests run against captured real lines so a format change fails a test
rather than someone's screen. That risk is contained here, in one module, on purpose.

Usage:
    python -m scripts.workflow_trace [--dir PROJECT] [--session FILE] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
# Run as `python -m scripts.workflow_trace`, the repo ROOT is on sys.path and scripts/ is
# not - so a bare `import dashboard` fails and pricing silently returns None for everything
# (found 2026-08-25: the CLI reported every stage unpriced while a direct import priced them
# fine, because the test had put scripts/ on the path by hand). Make the sibling importable
# here rather than leaving it to whoever imports this module.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

# Anything below this many tokens between two agent calls is not worth a row of its own: the
# orchestrator reading one file is noise, not a stage. Chosen to be visible in the trace
# rather than tuned - it is a display threshold, not a measurement.
_ORCHESTRATION_FLOOR = 20_000


def transcript_dir_for(project_dir: Path) -> Path:
    """Where Claude Code keeps this project's transcripts.

    The directory name is the absolute path with separators replaced by dashes - verified
    against a live tree, 2026-08-25. Derived rather than searched so the lookup stays O(1)
    and cannot wander into another project's sessions."""
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    slug = str(Path(project_dir).resolve()).replace(os.sep, "-").replace("/", "-")
    return root / "projects" / slug


def newest_transcript(project_dir: Path, after: float = 0.0) -> Path | None:
    """The most recently modified transcript for this project, optionally one that started
    after `after` (a POSIX timestamp - the moment the launcher opened the session).

    `after` is what stops another session's cost being attributed to this engagement. With no
    candidate the answer is None, never a best guess."""
    folder = transcript_dir_for(project_dir)
    try:
        candidates = [p for p in folder.glob("*.jsonl") if p.is_file()]
    except OSError:
        return None
    if after:
        candidates = [p for p in candidates if _safe_mtime(p) >= after]
    if not candidates:
        return None
    return max(candidates, key=_safe_mtime)


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def load_rates(path: Path | None = None) -> dict:
    """Rate metadata, for anything that wants to state how stale the prices are.

    There is no table here to load. Pricing lives in scripts/dashboard.py and this module
    prices THROUGH it - see `cost_of`. The signature is kept because callers pass rates
    around; the content is provenance, not prices."""
    try:
        import dashboard

        return {"rates_as_of": getattr(dashboard, "PRICING_AS_OF", ""), "currency": "USD"}
    except Exception:
        return {"rates_as_of": "", "currency": "USD"}


def cost_of(usage: dict, model: str, rates: dict | None = None) -> float | None:
    """Estimated cost of one usage block, or None when the model has no price.

    Prices through scripts/dashboard.py's table, which is the SAME one `budget-status` uses
    to measure an unattended run against its ceiling. That matters more than convenience:
    this view shipped on 2026-08-25 with a second, hand-written table that disagreed with it
    (opus at 15/75 against 5/25), which would have had the workflow view and the spend
    ceiling reporting different costs for the same run. One table, or the numbers argue.

    None is a first-class answer, not a failure: an unpriced model shows its tokens and says
    so. Pricing it from a neighbouring model's rate would look authoritative and be wrong."""
    if not isinstance(usage, dict):
        return None
    try:
        import dashboard
    except ImportError:
        # Not "this model has no rate" - "pricing is unavailable at all". Different fault,
        # and a caller showing "unpriced" for both would be hiding a broken install.
        return None
    try:
        priced = dashboard.price_usage(model or "", usage)
    except Exception:
        return None
    return None if priced is None else round(priced, 4)


# Cache reads are billed on EVERY request, so they belong in the cost - but they are the same
# context being re-read, not new work, and summing them across a long session produces a
# number that is arithmetically correct and completely misleading. Caught on first contact
# with a real 31MB transcript (2026-08-25): the naive total read 1.8 BILLION tokens for one
# session. So "tokens" means new tokens, and cache reads are carried and shown separately.
_NEW_TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens")


def total_tokens(usage: dict) -> int:
    """New tokens: input, output and cache writes. Deliberately NOT cache reads."""
    if not isinstance(usage, dict):
        return 0
    return sum(int(usage.get(field, 0) or 0) for field in _NEW_TOKEN_FIELDS)


def cache_reads(usage: dict) -> int:
    """Context re-read from cache. Billed, but not work done - shown on its own line."""
    if not isinstance(usage, dict):
        return 0
    try:
        return int(usage.get("cache_read_input_tokens", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _blank_usage() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def _add_usage(into: dict, more: dict) -> None:
    if not isinstance(more, dict):
        return
    for field in into:
        try:
            into[field] += int(more.get(field, 0) or 0)
        except (TypeError, ValueError):
            continue


def parse(path: Path, rates: dict | None = None) -> dict:
    """Stream a transcript into an ordered trace. Never raises on content.

    Streams rather than reads: one session here was 31MB and 3,546 messages, and holding that
    in memory to count tokens would be its own performance bug."""
    rates = load_rates() if rates is None else rates
    stages: list[dict] = []
    pending = _blank_usage()
    pending_models: dict[str, dict] = {}
    started = ""
    ended = ""
    lines_read = 0
    unreadable = 0

    def _flush_orchestration() -> None:
        """Turn accumulated orchestrator usage into its own row.

        It gets rows of its own rather than being spread over the neighbouring stages: the PM
        thinking between delegations is real cost that belongs to no stage, and quietly
        inflating the stages either side would misattribute it."""
        nonlocal pending, pending_models
        if total_tokens(pending) >= _ORCHESTRATION_FLOOR:
            model = max(
                pending_models,
                key=lambda m: total_tokens(pending_models[m]),
                default="",
            )
            stages.append(
                {
                    "kind": "orchestration",
                    "agent": "orchestrator",
                    "model": model,
                    "usage": dict(pending),
                    "tokens": total_tokens(pending),
                    "cache_reads": cache_reads(pending),
                    "cost": _blended_cost(pending_models, rates),
                    "duration_ms": None,
                    "status": "",
                    "tool_stats": {},
                    "loop_index": 1,
                }
            )
        pending = _blank_usage()
        pending_models = {}

    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                lines_read += 1
                try:
                    record = json.loads(line)
                except ValueError:
                    unreadable += 1
                    continue
                if not isinstance(record, dict):
                    unreadable += 1
                    continue
                stamp = record.get("timestamp") or ""
                if stamp:
                    started = started or stamp
                    ended = stamp
                result = record.get("toolUseResult")
                if isinstance(result, dict) and result.get("agentType"):
                    _flush_orchestration()
                    stages.append(_stage_from_result(result, rates))
                    continue
                if record.get("type") == "assistant":
                    message = record.get("message") or {}
                    usage = message.get("usage") or {}
                    model = message.get("model") or ""
                    _add_usage(pending, usage)
                    bucket = pending_models.setdefault(model, _blank_usage())
                    _add_usage(bucket, usage)
    except OSError as exc:
        return {
            "ok": False,
            "error": f"cannot read the transcript ({exc.__class__.__name__})",
            "stages": [],
            "path": str(path),
        }
    _flush_orchestration()
    _mark_loops(stages)
    return {
        "ok": True,
        "error": "",
        "path": str(path),
        "stages": stages,
        "started": started,
        "ended": ended,
        "lines_read": lines_read,
        "unreadable_lines": unreadable,
        "rates_as_of": rates.get("rates_as_of", ""),
        "currency": rates.get("currency", "USD"),
        "totals": _totals(stages),
    }


def _blended_cost(per_model: dict, rates: dict) -> float | None:
    """Cost of usage split across several models. None if ANY part is unpriced - a partial
    total presented as a total is the same lie as a guessed rate."""
    if not per_model:
        return None
    running = 0.0
    for model, usage in per_model.items():
        one = cost_of(usage, model, rates)
        if one is None:
            return None
        running += one
    return round(running, 4)


def _stage_from_result(result: dict, rates: dict) -> dict:
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    model = result.get("resolvedModel") or ""
    tokens = result.get("totalTokens")
    return {
        "kind": "agent",
        "agent": str(result.get("agentType") or "agent"),
        "model": str(model),
        "usage": usage,
        # totalTokens counts cache reads too, so it is NOT interchangeable with our "tokens".
        # Keep it under its own name and derive ours consistently for every row.
        "tokens": total_tokens(usage),
        "cache_reads": cache_reads(usage),
        "reported_total": int(tokens) if isinstance(tokens, int) else None,
        "cost": cost_of(usage, model, rates),
        "duration_ms": result.get("totalDurationMs"),
        "status": str(result.get("status") or ""),
        "tool_stats": result.get("toolStats") if isinstance(result.get("toolStats"), dict) else {},
        "tool_calls": result.get("totalToolUseCount"),
        "loop_index": 1,
    }


def _mark_loops(stages: list[dict]) -> None:
    """Number repeat runs of the same agent, and bracket A -> B -> A fix cycles.

    Deterministic and sequence-based: no heuristics, no inference about intent. A repeat is
    the same agent running again; a cycle is a return to an agent that has already run with
    at least one different agent in between - which is what review, fix, re-review looks
    like from the outside."""
    seen: dict[str, int] = {}
    for position, stage in enumerate(stages):
        if stage["kind"] != "agent":
            continue
        agent = stage["agent"]
        seen[agent] = seen.get(agent, 0) + 1
        stage["loop_index"] = seen[agent]
        if seen[agent] > 1:
            previous = _last_index(stages, agent, position)
            between = [
                s for s in stages[previous + 1 : position]
                if s["kind"] == "agent" and s["agent"] != agent
            ]
            if between:
                stage["cycle_with"] = sorted({s["agent"] for s in between})
                stages[previous]["cycle_start"] = True


def _last_index(stages: list[dict], agent: str, before: int) -> int:
    for i in range(before - 1, -1, -1):
        if stages[i]["kind"] == "agent" and stages[i]["agent"] == agent:
            return i
    return 0


def _totals(stages: list[dict]) -> dict:
    tokens = sum(int(s.get("tokens") or 0) for s in stages)
    cached = sum(int(s.get("cache_reads") or 0) for s in stages)
    priced = [s["cost"] for s in stages if isinstance(s.get("cost"), (int, float))]
    unpriced = [s for s in stages if s.get("cost") is None]
    duration = sum(int(s.get("duration_ms") or 0) for s in stages)
    return {
        "tokens": tokens,
        "cache_reads": cached,
        "cost": round(sum(priced), 4) if priced else None,
        # Named, not hidden: a total with unpriced stages in it is incomplete, and the view
        # has to be able to say so rather than quietly under-reporting.
        "unpriced_stages": len(unpriced),
        "duration_ms": duration,
        "agent_stages": sum(1 for s in stages if s["kind"] == "agent"),
        "loops": sum(1 for s in stages if s.get("loop_index", 1) > 1),
    }


def trace_for(project_dir: Path, after: float = 0.0) -> dict:
    """The trace for a project's most recent session, or a displayable reason there is none."""
    path = newest_transcript(project_dir, after=after)
    if path is None:
        return {
            "ok": False,
            "error": "no session transcript found for this project yet",
            "stages": [],
            "path": "",
        }
    return parse(path)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(description="What an engagement ran, on what, and for how much.")
    ap.add_argument("--dir", default=".", help="project directory (default: .)")
    ap.add_argument("--session", default="", help="a specific transcript file")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    trace = parse(Path(args.session)) if args.session else trace_for(Path(args.dir))
    if args.json:
        print(json.dumps(trace, indent=2))
        return 0 if trace.get("ok") else 1
    if not trace.get("ok"):
        print(trace.get("error", "no trace"), file=sys.stderr)
        return 1
    print(render_text(trace))
    return 0


def render_text(trace: dict) -> str:
    """Plain-text trace - the same content the TUI shows, for a terminal or a file."""
    totals = trace.get("totals") or {}
    out = [
        f"# Workflow - {totals.get('agent_stages', 0)} stage(s), "
        f"{totals.get('tokens', 0):,} new tokens, {_money(totals.get('cost'))} est",
        f"  (+{totals.get('cache_reads', 0):,} tokens re-read from cache - billed, not new work)",
        "",
    ]
    width = max((len(s["agent"]) for s in trace.get("stages") or []), default=12)
    for stage in trace.get("stages") or []:
        loop = f" x{stage['loop_index']}" if stage.get("loop_index", 1) > 1 else ""
        out.append(
            f"  {stage['agent'].ljust(width)}{loop:<4} {_short_model(stage['model']):<10}"
            f"{stage['tokens']:>10,} tok  {_money(stage.get('cost')):>9}"
            f"  {_duration(stage.get('duration_ms'))}"
        )
        if stage.get("cycle_with"):
            out.append(f"  {' ' * width}     ^ fix cycle with {', '.join(stage['cycle_with'])}")
    if totals.get("unpriced_stages"):
        out.append("")
        out.append(f"  {totals['unpriced_stages']} stage(s) ran on a model with no rate - "
                   "their tokens are counted, their cost is not")
    out += [
        "",
        f"> Tokens are measured. Cost is INFERRED from rates of "
        f"{trace.get('rates_as_of') or 'unknown date'} and is an estimate, never a bill.",
    ]
    return "\n".join(out)


def _money(value) -> str:
    """Small costs keep their significant digits. A stage that cost half a cent rendering as
    $0.00 reads as free, which is a different claim from cheap."""
    if value is None:
        return "unknown"
    if 0 < value < 0.01:
        return f"${value:.4f}"
    return f"${value:,.2f}"


def _short_model(model: str) -> str:
    """`claude-haiku-4-5-20251001` -> `haiku`. The family is what a reader is scanning for."""
    for family in ("opus", "sonnet", "haiku", "fable"):
        if family in (model or ""):
            return family
    return (model or "-")[:10]


def _duration(ms) -> str:
    if not ms:
        return "-"
    seconds = int(ms) // 1000
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


if __name__ == "__main__":
    sys.exit(main())
