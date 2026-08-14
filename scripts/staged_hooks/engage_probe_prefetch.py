#!/usr/bin/env python3
"""UserPromptSubmit hook - pre-run the /engage step-0 probe before the model's turn.

The step-0 probe (`engage-open.md`) currently costs a full model round-trip on every
`/engage`/`/engage-light`/`/map-codebase` open: the model has to issue a Bash tool call
(the heredoc), wait for it, then read the result - a real turn, not free, even though the
probe's own substance is already cheap (tool inventory is 7-day TTL cached, map-drift is
mtime-shortcut cached). This hook removes that round-trip for the steady-state case: it
runs the SAME probe (calling `find_plugin_root.find_plugin_root` and
`engage_probe.build_report` directly - no logic duplicated, no new drift surface) from a
`UserPromptSubmit` hook, which Claude Code fires BEFORE the model's turn and whose plain
stdout (exit 0) is added straight to context - the identical mechanism
`persona_anchor.py`/`session_resume_brief.py` already rely on. When the result lands in
context already wrapped as `<engage-probe-result>`, `engage-open.md`'s step 0 uses it
directly and skips the Bash heredoc for that open.

Dormancy-exact, two gates, in order:
1. `user_input` must actually look like one of the three commands that read
   `engage-open.md` (`/engage`, `/engage-light`, `/map-codebase` - checked by grepping
   every skill file for the reference, not guessed) - a single regex check, so every
   other prompt in every other session costs nothing, same contract as
   `persona_anchor.py`'s own dormancy gate.
2. The project's `.guard-interpreter` cache must already be warm. A cold cache means
   this is a genuinely first-ever run in this project - the exact case the live Bash
   heredoc's own three-way interpreter trial (`python3`/`python`/`py`, Windows-aware)
   exists to handle, and reimplementing that here would be new, untested surface for a
   case that only happens once per project. This hook declines instead: no injected
   block, the model's own live probe runs exactly as it does today. The steady-state
   majority (every session after the first, in a project that has run the plugin
   before) is what this hook actually targets.

Fails open on any error past those two gates too (missing plugin-root, a build_report
exception, an unreadable cache file) - an optimisation must never cost a broken open;
worst case is simply no injected block, same as a cold cache.

Wire via scripts/apply-engage-probe-prefetch.sh (HUMAN-run - hook/config edits are
human-only, ADR-002 rec 5).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# \b alone is too loose here: a hyphen counts as a word boundary, so "/engage-lighter"
# would match via the bare "engage" branch (live test caught this). Command arguments
# always follow a space, never a bare hyphen, so require whitespace-or-end explicitly.
_ENGAGE_RE = re.compile(r"^/(?:engage(?:-light)?|map-codebase)(?:\s|$)")


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _read_cache(project_dir: Path) -> str:
    try:
        return (project_dir / ".claude" / ".guard-interpreter").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _scripts_dir() -> Path:
    """Sibling find_plugin_root.py/engage_probe.py live in scripts/ - resolve that
    directory whether THIS file is running from its staged copy
    (scripts/staged_hooks/engage_probe_prefetch.py, what this file's own tests load
    directly) or its live, applied copy (scripts/engage_probe_prefetch.py, what actually
    runs once a human applies it) - __file__.parent differs between the two."""
    here = Path(__file__).resolve().parent
    for candidate in (here, here.parent):
        if (candidate / "find_plugin_root.py").is_file():
            return candidate
    return here  # neither has it - let the import below fail naturally (fail-open)


def _build_block(interp: str, project_dir: Path) -> str | None:
    """Returns the full injected block, or None on any failure (fail-open)."""
    try:
        scripts_dir = _scripts_dir()
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from find_plugin_root import find_plugin_root  # local import: see sys.path above
        import engage_probe

        plugin_root = find_plugin_root(Path.home(), project_dir)
        report = engage_probe.build_report(plugin_root, project_dir)
    except Exception:
        return None
    if not report:
        return None
    lines = [
        "<engage-probe-result>",
        "Pre-computed by the engage_probe_prefetch hook, same probe engage-open.md's step 0",
        "documents - use these values directly, do NOT run the Bash bootstrap heredoc for",
        "this open. Still read docs/team-operating-guide.md yourself using PLUGIN_ROOT below;",
        "the probe never prints it.",
        f"INTERPRETER={interp}",
        report,
        "</engage-probe-result>",
    ]
    return "\n".join(lines)


def main() -> int:
    _force_utf8_output()
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    prompt = (data.get("user_input") or "").lstrip()
    if not _ENGAGE_RE.match(prompt):
        return 0  # not an engage-open.md consumer - zero cost, dormancy preserved

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or Path.cwd())
    interp = _read_cache(project_dir)
    if not interp:
        return 0  # cold cache: first-ever run in this project, let the live probe handle it

    try:
        block = _build_block(interp, project_dir)
        if block:
            print(block)
    except Exception:
        pass  # belt-and-braces: _build_block already fails open internally, but a hook's
        # own main() must never propagate ANY exception past itself (matches
        # persona_anchor.py/session_resume_brief.py's own outer try/except) - an
        # optimisation must never cost a broken open.
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
