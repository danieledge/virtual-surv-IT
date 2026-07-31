#!/usr/bin/env python3
"""One PreToolUse process for what used to be five (P4, 2026-07-31 corp report).

Five separate hooks all matched Bash (guard-raw-data, guard-code-execution,
guard-consent-writes, document_input_redirect, module_form_redirect), each wired as
its own hooks.json entry -> its own `sh run-guard.sh <script>` process. P1/P2 already
made run-guard.sh's OWN interpreter resolution fast and cached, but that left the
underlying cost untouched: FIVE process-creation events per single Bash tool call,
before its command even runs. On a corporate Windows box where every new process gets
scanned by endpoint security, that's five scans instead of one, on every Bash call, all
session long - confirmed live (2026-07-31): 51s for the step-0 probe alone, 1m31s for
the very next Bash call, ~2 minutes total for just the open sequence, even with every
individual hang already fixed. This dispatcher runs the SAME five checks - unmodified,
imported by file path, not reimplemented - in ONE process instead of five.

Design constraints, all deliberate:
  - Each guard's own main() is called directly, never re-executed via its own
    `if __name__ == "__main__":` block (that block is what wires each guard's exit
    code / crash policy to the CLI - the dispatcher must replicate it, see below).
  - stdin can only be consumed once, but all five guards independently read it - so
    it's read ONCE here and re-injected as a fresh in-memory stream before each
    guard's main() call.
  - Every guard's own documented crash-fail-policy is preserved exactly, NOT
    unified: guard-raw-data / guard-code-execution / guard-consent-writes are safety
    guards that fail CLOSED (block) on an unexpected exception (their own
    if __name__ blocks say so explicitly, ADR-002); document_input_redirect and
    module_form_redirect are convenience redirects that fail OPEN (their own
    docstrings say so explicitly - "never block work it cannot improve"). Getting
    this backwards for even one guard would be a silent safety regression.
  - Matcher scope (which tool_names each guard used to fire on, per its hooks.json
    entry) is preserved exactly as a lookup table below - a tool call only runs the
    checks that would have actually matched it before, not all five unconditionally.
  - First block wins: checks run in the same order the old hooks.json entries did,
    and the loop returns as soon as one blocks - equivalent to "would at least one
    of the five have blocked", the only thing that determines the tool call's fate.

Protocol: read the PreToolUse JSON on stdin once; exit 2 if any applicable guard would
have blocked; exit 0 otherwise. Never raises - a dispatcher-level bug must not brick
every Bash/Read/Write call it's wired to guard.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType

# name -> (relative-to-hooks-dir-or-scripts-dir, applicable tool_names, fail-closed-on-crash)
_HOOKS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "hooks"
_SCRIPTS_DIR = Path(__file__).resolve().parent

_CHECKS = (
    ("guard_raw_data", _HOOKS_DIR / "guard-raw-data.py", {"Read", "Grep", "Glob", "Bash"}, True),
    ("guard_code_execution", _HOOKS_DIR / "guard-code-execution.py", {"Bash"}, True),
    (
        "guard_consent_writes",
        _HOOKS_DIR / "guard-consent-writes.py",
        {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"},
        True,
    ),
    (
        "document_input_redirect",
        _SCRIPTS_DIR / "document_input_redirect.py",
        {"Read", "Bash"},
        False,
    ),
    ("module_form_redirect", _SCRIPTS_DIR / "module_form_redirect.py", {"Bash"}, False),
)


def _load(name: str, path: Path) -> ModuleType | None:
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def _run_guard(module: ModuleType, name: str, payload_text: str, fail_closed: bool) -> int:
    """Runs module.main() with stdin replaced by payload_text, capturing its intended
    exit code without letting SystemExit (or any other exception) tear down the
    dispatcher - the whole point is that ONE guard's outcome must never stop the
    remaining ones from running."""
    old_stdin = sys.stdin
    sys.stdin = io.StringIO(payload_text)
    try:
        result = module.main()
        return result if isinstance(result, int) else 0
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    except Exception:
        # Preserve each guard's OWN documented crash policy exactly - bypassing its
        # if __name__ block means the dispatcher must reproduce what that block did.
        if fail_closed:
            sys.stderr.write(f"{name} crashed unexpectedly; failing closed (blocked).\n")
            return 2
        return 0
    finally:
        sys.stdin = old_stdin


def main() -> int:
    try:
        payload_text = sys.stdin.read()
    except Exception:
        return 0
    try:
        payload = json.loads(payload_text or "{}")
    except Exception:
        return 0  # malformed payload - fail open, matches every individual guard
    tool = payload.get("tool_name", "")

    for name, path, tools, fail_closed in _CHECKS:
        if tool not in tools:
            continue
        try:
            if not path.is_file():
                continue  # missing guard file - fail open for THAT check only
        except OSError:
            continue
        module = _load(name, path)
        if module is None:
            if fail_closed:
                sys.stderr.write(f"{name} failed to load; failing closed (blocked).\n")
                return 2
            continue
        code = _run_guard(module, name, payload_text, fail_closed)
        if code == 2:
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
