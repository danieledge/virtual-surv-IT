#!/usr/bin/env python3
"""PreToolUse(Bash) redirect: module-form team-script calls in plugin mode.

`<python> -m scripts.<name>` only works with the team repo as the working directory -
anywhere else Python exits 1 with ModuleNotFoundError before the script loads. In an
installed-plugin session that error costs a recovery turn and alarms the user watching
the console (seen live on a plugin-mode engagement, 2026-07-30). This hook catches the
call BEFORE it runs and hands the model the exact path-form command instead.

Deliberately narrow and fail-open:
- fires only when the Bash command contains `-m scripts.<name>`;
- allows silently when the working directory has scripts/<name>.py (repo-as-project,
  where the module form is correct);
- redirects (exit 2, stderr feedback) only when the bundled copy exists under
  CLAUDE_PLUGIN_ROOT, quoting the corrected command verbatim;
- any doubt - no plugin root, unreadable stdin, weird input - allows (exit 0). This is
  a convenience redirect, not a safety gate: never block work it cannot improve.
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
    fixes = []
    for name in dict.fromkeys(hits):
        bundled = Path(root) / "scripts" / f"{name}.py"
        try:
            if bundled.is_file():
                fixes.append(f'"{bundled}"')
        except OSError:
            continue
    if not fixes:
        return 0
    print(
        "plugin mode: `-m scripts.<name>` exits 1 outside the team repo (no `scripts` "
        "package on the module path). Run the bundled copy by path instead - replace "
        "the `-m scripts.<name>` part with: " + " / ".join(fixes) + " (keep the same "
        "interpreter and arguments).",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
