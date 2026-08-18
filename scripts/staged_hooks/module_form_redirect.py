#!/usr/bin/env python3
"""PreToolUse(Bash) redirect: module-form team-script calls in plugin mode.

`<python> -m scripts.<name>` only works with the team repo as the working directory -
anywhere else Python exits 1 with ModuleNotFoundError before the script loads. In an
installed-plugin session that error costs a recovery turn and alarms the user watching
the console (seen live on a plugin-mode engagement, 2026-07-30). This hook catches the
call BEFORE it runs.

Deliberately narrow and fail-open:
- fires only when the Bash command contains `-m scripts.<name>`;
- allows silently when the working directory has scripts/<name>.py (repo-as-project,
  where the module form is correct);
- when EVERY matched name resolves to a bundled copy under CLAUDE_PLUGIN_ROOT, rewrites
  the command transparently (`hookSpecificOutput.updatedInput`, `permissionDecision:
  "allow"`) and lets it run - no block, no red/blocked styling, nothing for the user or
  model to react to (2026-08-04: the earlier exit-2-and-ask-the-model-to-retry design
  looked like a failure to users watching the console even though nothing was wrong);
- when only SOME matched names resolve (a multi-call command mixing a real bundled
  script with one that doesn't exist), a silent partial rewrite would leave part of the
  command broken - falls back to the old behavior: block (exit 2) with a corrective
  stderr message for the ones it can fix;
- any doubt - no plugin root, unreadable stdin, weird input, nothing resolves - allows
  (exit 0). This is a convenience redirect, not a safety gate: never block work it
  cannot improve.

This transparent-rewrite technique is deliberately NOT used by the actual safety guards
(guard-raw-data.py, guard-code-execution.py, guard-consent-writes.py,
guard-findings-pack-write.py) - those exist to stop things, and silently rewriting a
command under a safety guard would defeat the point of a guard. It only belongs on a
convenience hook like this one, where the "fix" is unambiguous and the alternative to
rewriting is simply letting a doomed command fail with a worse error.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_MODULE_FORM = re.compile(r"-m\s+scripts\.([A-Za-z_][A-Za-z0-9_]*)")


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    command = str((data.get("tool_input") or {}).get("command") or "")
    hits = _MODULE_FORM.findall(command)
    if not hits:
        return 0
    cwd = Path(data.get("cwd") or ".")
    try:
        if all((cwd / "scripts" / f"{name}.py").is_file() for name in hits):
            return 0  # repo-as-project: the module form is the right one
    except OSError:
        return 0
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or ""
    if not root:
        return 0
    unique_names = list(dict.fromkeys(hits))
    bundled_by_name: dict[str, Path] = {}
    for name in unique_names:
        bundled = Path(root) / "scripts" / f"{name}.py"
        try:
            if bundled.is_file():
                bundled_by_name[name] = bundled
        except OSError:
            continue
    if not bundled_by_name:
        return 0

    if set(unique_names) <= set(bundled_by_name):
        # every occurrence resolves - rewrite transparently, no block, no red text
        def _sub(m: "re.Match[str]") -> str:
            return f'"{bundled_by_name[m.group(1)]}"'

        updated_command = _MODULE_FORM.sub(_sub, command)
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "permissionDecisionReason": (
                            "plugin mode: rewrote `-m scripts.<name>` to the bundled "
                            "copy's direct path (module form only works inside the "
                            "team repo)."
                        ),
                        "updatedInput": {"command": updated_command},
                    }
                }
            )
        )
        return 0

    # partial resolution - a silent rewrite would leave part of the command broken,
    # so fall back to a blocking corrective message for the names that do resolve
    fixes = [f'"{bundled_by_name[name]}"' for name in unique_names if name in bundled_by_name]
    print(
        "Not an error, no action needed from you: `-m scripts.<name>` only works with the "
        "team repo as the working directory, which a plugin install doesn't have, so this "
        "call was blocked before it ran. Retry the same tool call with the `-m scripts.<name>` "
        "part swapped for: " + " / ".join(fixes) + " (keep the same interpreter and arguments).",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
