#!/usr/bin/env python3
"""One UserPromptSubmit hook that runs both prompt hooks, instead of two of them.

WHY (F4, 2026-08-26 perf audit). `persona_anchor.py` and `engage_probe_prefetch.py` were
registered as two INDEPENDENT UserPromptSubmit entries. Claude Code runs each hook command
separately, so every user message paid two complete launcher chains: two `sh run-guard.sh`,
two Python interpreter cold starts, two daemon round trips. The work inside them is
nothing - measured over a raw socket on a dormant session, persona_anchor 0.88ms and
engage_probe_prefetch 0.66ms - so roughly 99% of the second invocation was pure overhead.

On Linux that is ~90ms wasted per prompt. On the corporate Windows box it is an entire
extra `sh` + `python.exe` spawn pair per prompt, on the host where spawns cost the most;
run-guard.sh's own field measurement there is ~211ms per daemon-served invocation.

This is exactly what `bash_hook_dispatcher.py` already does for the five hooks that match
Bash - the same established, reviewed pattern, applied to the other every-message event.

HOW IT DIFFERS FROM THE BASH DISPATCHER, and why that matters. The Bash guards are safety
checks: they communicate by EXIT CODE (2 blocks), and one blocking guard must short-circuit
the rest. These two are context injectors: they communicate by writing to STDOUT, which
Claude Code adds to the prompt, and both always return 0. So this dispatcher:

  - captures each hook's stdout rather than letting it write directly, and emits them
    concatenated in the SAME registration order the two separate entries had (persona_anchor
    first), because that order is what the user sees;
  - runs EVERY hook, always - there is no short-circuit, since neither can "block";
  - fails OPEN throughout. Neither hook is a safety guard (both already swallow their own
    exceptions and exit 0), so a crash here must cost the injected context, never the
    user's prompt. This is the opposite polarity to the Bash dispatcher's fail-closed
    guards, and it is deliberate.

A hook that produces no output contributes nothing - no blank lines, no separators - so a
dormant session emits exactly what it did before: nothing at all.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType

_SCRIPTS_DIR = Path(__file__).resolve().parent

# ORDER IS THE CONTRACT: this is the order the two separate hook entries ran in, and it is
# the order their output appeared in the prompt. Adding a hook here means appending, not
# inserting, unless the injected context genuinely needs to lead.
_PROMPT_HOOKS = (
    ("persona_anchor", _SCRIPTS_DIR / "persona_anchor.py"),
    ("engage_probe_prefetch", _SCRIPTS_DIR / "engage_probe_prefetch.py"),
)


def _load(name: str, path: Path) -> ModuleType | None:
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def _run_hook(module: ModuleType, payload_text: str) -> str:
    """Run module.main() with stdin replaced by the payload, returning what it printed.

    Both streams are swapped for the duration: stdin so the hook reads the payload it
    expects, stdout so its `print()` calls are captured rather than emitted mid-run. Every
    failure mode returns "" - a hook that crashes loses its context and nothing else.
    """
    old_stdin, old_stdout = sys.stdin, sys.stdout
    captured = io.StringIO()
    sys.stdin = io.StringIO(payload_text)
    sys.stdout = captured
    try:
        module.main()
    except SystemExit:
        # Both hooks call sys.exit(main()) in their own __main__ block; bypassing that
        # block means SystemExit can still arrive from inside main() itself. Whatever they
        # printed before exiting is still wanted.
        pass
    except Exception:
        return ""
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout
    return captured.getvalue()


def main() -> int:
    try:
        payload_text = sys.stdin.read()
    except Exception:
        return 0
    try:
        json.loads(payload_text or "{}")
    except Exception:
        # Malformed payload - fail open, matching what each hook does with the same input.
        return 0

    for name, path in _PROMPT_HOOKS:
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        module = _load(name, path)
        if module is None:
            continue
        output = _run_hook(module, payload_text)
        if output:
            sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
