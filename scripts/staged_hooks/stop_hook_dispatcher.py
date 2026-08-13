#!/usr/bin/env python3
"""One Stop-event process for what used to be two (2026-08-03 perf audit).

`dod_stop_gate.py` and `todo_panel_nudge.py` were two independent `hooks.Stop` entries,
each its own `sh run-guard.sh <script>` process spawn on every single Stop event while any
engagement pack is gated (open/blocked/closing) - the same "N processes for one event"
shape `bash_hook_dispatcher.py` already fixed for PreToolUse (its own docstring: "FIVE
process-creation events per single Bash call... 51s for the step-0 probe alone"). Here it
was only two, not five, but each independently `importlib`-execs the ~90KB
`check_artifacts.py` via its own `_load_checker()`, and both independently discover the
gated packs via `ca.engagement_packs()` / `ca.pack_status()`. This dispatcher runs the SAME
two checks - unmodified, imported by file path, not reimplemented - in ONE process instead
of two.

Design constraints, mirroring bash_hook_dispatcher.py's own (see that file for the fuller
rationale on why each point matters):
  - Each hook's own main() is called directly, never re-executed via its own
    `if __name__ == "__main__":` block - that block is what wires crash policy to the CLI,
    so this dispatcher replicates the NET effect (see below) rather than the block itself.
  - stdin is read ONCE and re-injected as a fresh in-memory stream before each hook's
    main() call, since both independently read it.
  - Both hooks fail OPEN on any internal error already (dod_stop_gate.py's own
    `if __name__` wraps main() in try/except: sys.exit(0); todo_panel_nudge.py's main()
    wraps its own body internally) - unlike the PreToolUse safety guards, NEITHER of these
    is a safety control, so there is no fail-closed policy to preserve here. This
    dispatcher wraps each call the same way: an exception from either hook is swallowed
    and treated as "no nudge from this one", never as a crash of the whole dispatcher.
  - UNLIKE bash_hook_dispatcher.py's exit-code short-circuit (PreToolUse has one binary
    outcome - block or allow - so "first block wins" is correct), a Stop hook's signal is a
    JSON `{"decision": "block", "reason": ...}` printed to stdout, and the ACTUAL
    Claude Code composition behavior when multiple hooks on the same event each try to
    print their own JSON decision is not documented (confirmed against the hooks
    reference - hooks "run in parallel", but result composition across distinct hooks
    is unspecified). Rather than depend on undocumented behavior, this dispatcher captures
    each hook's stdout, and if BOTH want to nudge in the same turn, COMBINES both reasons
    into ONE deterministic `decision:block` output - the model sees exactly the same total
    information either hook would have surfaced alone, never less, and never twice.

Protocol: read the Stop-hook JSON payload on stdin once; print at most ONE
`{"decision": "block", "reason": ...}` JSON if either (or both, combined) hook wants to
nudge; print nothing and exit 0 otherwise. Never raises.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType

_HOOKS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "hooks"
_SCRIPTS_DIR = Path(__file__).resolve().parent

# name -> path to that hook's (unmodified) source, tried by file path so the dispatcher
# never re-implements either hook's own logic.
_CHECKS = (
    ("dod_stop_gate", _SCRIPTS_DIR / "dod_stop_gate.py"),
    ("todo_panel_nudge", _SCRIPTS_DIR / "todo_panel_nudge.py"),
)


def _load(name: str, path: Path) -> ModuleType | None:
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def _run_hook(module: ModuleType, payload_text: str) -> dict | None:
    """Runs module.main() with stdin replaced by payload_text and stdout captured, and
    returns the parsed {"decision": ..., "reason": ...} dict if it printed one, else None.
    Never raises - either hook failing is "no nudge from this one", matching both hooks'
    own documented fail-open posture exactly."""
    old_stdin, old_stdout = sys.stdin, sys.stdout
    sys.stdin = io.StringIO(payload_text)
    captured = io.StringIO()
    sys.stdout = captured
    try:
        module.main()
    except SystemExit:
        pass
    except Exception:  # nosec B110 - deliberate fail-open, see docstring above
        pass
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout
    printed = captured.getvalue().strip()
    if not printed:
        return None
    try:
        decision = json.loads(printed)
    except Exception:
        return None
    if not isinstance(decision, dict) or decision.get("decision") != "block":
        return None
    return decision


def main() -> int:
    try:
        payload_text = sys.stdin.read()
    except Exception:
        return 0

    decisions: list[dict] = []
    for name, path in _CHECKS:
        try:
            if not path.is_file():
                continue  # missing hook file - skip that check only
        except OSError:
            continue
        module = _load(name, path)
        if module is None:
            continue  # both hooks fail open on their own load errors too
        decision = _run_hook(module, payload_text)
        if decision is not None:
            decisions.append(decision)

    if not decisions:
        return 0
    if len(decisions) == 1:
        print(json.dumps(decisions[0]))
        return 0

    # Both wanted to nudge in the same turn - combine deterministically rather than rely
    # on undocumented multi-hook composition.
    combined_reason = "\n\n".join(d.get("reason", "") for d in decisions)
    print(json.dumps({"decision": "block", "reason": combined_reason}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
