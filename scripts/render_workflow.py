#!/usr/bin/env python3
"""Export a workflow trace: Markdown, HTML, JSON and CSV.

WHY IT IS THE SAME OBJECT. This renders exactly the dict `workflow_trace.parse` returns -
the same one the launcher screen draws. Two renderers over one object cannot disagree; two
parsers over one file eventually always do, which is the drift this repo has already fixed
once between the launcher's own menu tiers.

WHAT AN EXPORT MAY CONTAIN. Stage names, models, token counts, durations, tool counts and
outcomes. **Never message content, prompts or file contents** - a trace sits on top of a
transcript full of both, and an export is a file that leaves the machine. That restriction is
what makes an exported workflow safe to attach to a client report, which is the only reason
to export one. Treat any change that widens it as a safety regression (CLAUDE.md §5).

Usage:
    python -m scripts.render_workflow [--dir PROJECT] [--session FILE] [--out DIR]
                                      [--format md|html|json|csv|all]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import workflow_trace  # noqa: E402

# The exact columns an export may carry. An allow-list rather than a deny-list on purpose:
# a new field appearing in the transcript must not silently start being exported.
_COLUMNS = (
    "position", "kind", "agent", "loop_index", "model",
    "tokens", "cache_reads", "cost", "duration_ms", "tool_calls", "status",
)


def rows(trace: dict) -> list[dict]:
    out = []
    for position, stage in enumerate(trace.get("stages") or [], 1):
        row = {"position": position}
        for column in _COLUMNS[1:]:
            row[column] = stage.get(column, "")
        out.append(row)
    return out


def to_markdown(trace: dict) -> str:
    totals = trace.get("totals") or {}
    lines = [
        "# Workflow trace",
        "",
        f"- **Stages:** {totals.get('agent_stages', 0)} "
        f"({totals.get('loops', 0)} repeat run(s))",
        f"- **New tokens:** {totals.get('tokens', 0):,} "
        f"📊 measured",
        f"- **Re-read from cache:** {totals.get('cache_reads', 0):,} - billed, not new work",
        f"- **Estimated cost:** {workflow_trace._money(totals.get('cost'))} 🧠 inferred "
        f"from rates of {trace.get('rates_as_of') or 'an unknown date'}",
        "",
        "| # | Stage | Model | New tokens | Cache reads | Est. cost | Duration | Status |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows(trace):
        loop = f" ×{row['loop_index']}" if (row.get("loop_index") or 1) > 1 else ""
        lines.append(
            f"| {row['position']} | {row['agent']}{loop} "
            f"| {workflow_trace._short_model(row['model'])} "
            f"| {int(row['tokens'] or 0):,} | {int(row['cache_reads'] or 0):,} "
            f"| {workflow_trace._money(row['cost'])} "
            f"| {workflow_trace._duration(row['duration_ms'])} | {row['status'] or '-'} |"
        )
    if totals.get("unpriced_stages"):
        lines += ["", f"> {totals['unpriced_stages']} stage(s) ran on a model with no rate in "
                      "`config/model-pricing.json`. Their tokens are counted; their cost is "
                      "not, because pricing them from a neighbouring model would produce a "
                      "figure that looks authoritative and is wrong."]
    lines += [
        "",
        "> **Tokens are 📊 observed** - read from the session transcript. **Cost is 🧠 "
        "inferred** by multiplying them by a rate table, and is an estimate, never a bill.",
        "> For the SESSION total, `/cost` in Claude Code is the authority and this is not - "
        "it computes from its own rates and is not restated here. These figures exist to "
        "apportion cost ACROSS STAGES, which `/cost` does not do and which token counts "
        "alone cannot: an opus output token and a haiku one differ by roughly 15x, so a "
        "stage comparison without rates would be meaningless.",
        "> This export carries stage names, models, counts, durations and outcomes only - "
        "never prompts, message content or file contents.",
    ]
    return "\n".join(lines) + "\n"


def to_csv(trace: dict, path: Path) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_COLUMNS))
        writer.writeheader()
        for row in rows(trace):
            writer.writerow(row)
    return path


def export(trace: dict, out_dir: Path, formats: tuple[str, ...]) -> list[Path]:
    """Write the trace out. A FAILED trace exports nothing.

    Writing an empty workflow-trace.md would produce a document that looks like a record of
    an engagement and is a record of a failed read - and unlike a missing file, it would be
    attached to things and believed. Nothing is the honest output here."""
    if not trace.get("ok"):
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    stem = "workflow-trace"
    if "json" in formats:
        path = out_dir / f"{stem}.json"
        path.write_text(json.dumps(trace, indent=2), encoding="utf-8")
        written.append(path)
    if "csv" in formats:
        written.append(to_csv(trace, out_dir / f"{stem}.csv"))
    if "md" in formats or "html" in formats:
        md_path = out_dir / f"{stem}.md"
        md_path.write_text(to_markdown(trace), encoding="utf-8")
        written.append(md_path)
        if "html" in formats:
            written.extend(_render_html(md_path))
    return written


def _render_html(md_path: Path) -> list[Path]:
    """Reuse the team's own renderer, so an exported trace looks like every other artifact."""
    try:
        import render_html

        # render_file, not main(): main() parses argv and takes no arguments. Caught by
        # exporting for real and noticing the .html simply was not there (2026-08-25) - the
        # broad except below had swallowed a TypeError into a silent skip, which is exactly
        # the shape of failure that makes a "convenience" quietly stop existing.
        out = render_html.render_file(md_path)
        return [out] if out and Path(out).is_file() else []
    except Exception as exc:
        print(f"note: HTML render skipped ({exc.__class__.__name__})", file=sys.stderr)
        return []  # the markdown is the deliverable; html is a convenience


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(description="Export a workflow trace.")
    ap.add_argument("--dir", default=".", help="project directory (default: .)")
    ap.add_argument("--session", default="", help="a specific transcript file")
    ap.add_argument("--out", default="", help="output directory (default: alongside the project)")
    ap.add_argument("--format", default="all", choices=["md", "html", "json", "csv", "all"])
    args = ap.parse_args(argv)

    project = Path(args.dir).resolve()
    trace = (
        workflow_trace.parse(Path(args.session))
        if args.session
        else workflow_trace.trace_for(project)
    )
    if not trace.get("ok"):
        print(trace.get("error", "no trace to export"), file=sys.stderr)
        return 1
    formats = ("md", "html", "json", "csv") if args.format == "all" else (args.format,)
    out_dir = Path(args.out).resolve() if args.out else project / "artifacts" / "workflow"
    for path in export(trace, out_dir, formats):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
