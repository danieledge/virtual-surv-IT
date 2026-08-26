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

(2026-08-03: `guard_findings_pack_write` joined the registry below as a sixth check, added
after this consolidation rather than migrated into it - the "five" above is the historical
count from the original migration, not a ceiling. New checks register the same way: an entry
in `_CHECKS` below - but unlike the 2026-08-03 addition, a check that needs a tool_name NOT
already in the top-level PreToolUse matcher (hooks.json / settings.json) also needs that
matcher widened, or its process never starts. That happened once already: the 2026-08-01
raw-data-guard coverage fix (ADR-002 rec 22) taught guard-raw-data.py to handle WebFetch and
NotebookRead, but neither the matcher nor this file's own tool set were updated to match, so
the new code path was dead until the 2026-08-05 review caught it and this comment plus the
_CHECKS entry below were corrected. Check both places when a guard's tool coverage changes.
It happened AGAIN, on a security boundary this time: guard-findings-pack-write.py was
extended (2026-08-06) to scope Edit as well as Write for the four advisory review agents
(CLAUDE.md §6's "mechanically enforced ... neither grant can widen in practice" claim) -
the guard's own main() checks `tool_name not in ("Write", "Edit")`, but this file's _CHECKS
entry was never widened past {"Write"}, so an Edit call from a scoped agent never reached
this guard at all in the live dispatched path. The guard's OWN test suite invoked it as a
direct subprocess, bypassing this file entirely, so it stayed green while the real
enforcement was dead code. Found by a 2026-08-14 Fable-model audit, fixed the same day -
see tests/test_bash_hook_dispatcher.py's dispatcher-level Edit test, which the guard-direct
test suite could never have caught on its own.)

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
    (
        "guard_raw_data",
        _HOOKS_DIR / "guard-raw-data.py",
        {"Read", "Grep", "Glob", "Bash", "WebFetch", "NotebookRead"},
        True,
    ),
    ("guard_code_execution", _HOOKS_DIR / "guard-code-execution.py", {"Bash"}, True),
    (
        "guard_consent_writes",
        _HOOKS_DIR / "guard-consent-writes.py",
        {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"},
        True,
    ),
    (
        "guard_findings_pack_write",
        _HOOKS_DIR / "guard-findings-pack-write.py",
        {"Write", "Edit"},
        True,
    ),
    (
        "document_input_redirect",
        _SCRIPTS_DIR / "document_input_redirect.py",
        {"Read", "Bash"},
        False,
    ),
    ("module_form_redirect", _SCRIPTS_DIR / "module_form_redirect.py", {"Bash"}, False),
    # Map-first enforcement (2026-08-17): denies bare full-tree enumeration in
    # ENGAGED sessions only, naming the sanctioned inventory sources. Advisory
    # infra polarity (fail_open on a missing/broken file) - it is a cost rule,
    # not a safety wall; the module itself returns 2 to deny when armed.
    ("enumeration_redirect", _SCRIPTS_DIR / "enumeration_redirect.py", {"Bash"}, False),
    # Exploration redirect (2026-08-26): the sibling of enumeration_redirect for the two
    # habits that actually cost the tokens - a whole-file Read of a large file, and an
    # unbounded content-mode Grep. Same advisory infra polarity (fail_open), same
    # engaged-sessions-only arming, and it redirects each target ONCE so a deliberate full
    # read still succeeds on the repeat. Prose said this already; prose did not do it.
    ("exploration_redirect", _SCRIPTS_DIR / "exploration_redirect.py", {"Read", "Grep"}, False),
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
            missing = not path.is_file()
        except OSError:
            missing = True
        if missing:
            # 2026-08-07 (found by a framework-wide audit): this used to unconditionally
            # `continue` here regardless of fail_closed - a missing safety-guard FILE
            # (accidental deletion, a broken install, tampering that bypasses the
            # Bash-lexical mutation check) failed OPEN, asymmetric with the "failed to
            # LOAD" branch three lines below, which already correctly fails closed for
            # the same class of guard. There is no legitimate reason for a shipped guard
            # file to be missing from a working install, so this now follows the exact
            # same fail_closed policy as a load failure - both are "this guard cannot
            # run", and a guard that cannot run must not silently pass.
            if fail_closed:
                sys.stderr.write(f"{name} guard file not found; failing closed (blocked).\n")
                return 2
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
