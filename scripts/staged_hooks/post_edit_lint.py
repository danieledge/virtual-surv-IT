#!/usr/bin/env python3
"""PostToolUse lint feedback - a defect surfaces one edit after it is written, not at the gate.

Finishes the pattern `docs/internal/research-virtual-team.md` refinement #4 names
("verification as hooks, not prompts" - lint on the write path): the Stop-gate half shipped
in 0.17.0; this is the PostToolUse half (0.33.1 capability adoption). When a builder agent
Write/Edits a Python file DURING A LIVE ENGAGEMENT, the file is checked immediately:

  * `py_compile` (stdlib - always available, no install assumption): syntax errors;
  * `ruff check` when it happens to be on PATH (never required): lint findings.

Findings feed back to the model via the PostToolUse feedback channel (exit 2 + stderr - the
write has already happened, nothing is blocked; the model just hears about the problem
while the file is still in hand). Clean files and dormant sessions are silent.

Advisory by design: NOT a safety guard, separate from the three ADR-002 guards, fails open
on every error path, and never fires outside a live engagement (dormancy invariant).

Wire via scripts/apply-post-edit-lint.sh (HUMAN-run - hook/config edits are human-only,
ADR-002 rec 5) into `.claude/settings.json` + `hooks/hooks.json` -> hooks.PostToolUse,
matcher "Write|Edit|MultiEdit".
"""

from __future__ import annotations

import json
import os
import py_compile
import shutil
import subprocess  # nosec B404 - fixed-argv lint invocations only (ruff only - py_compile is in-process)
import sys
import tempfile
from pathlib import Path

_LIVE = ("in_progress", "blocked", "closing")


def _pack_live(pack: Path) -> bool:
    state_file = pack / "engagement-state.json"
    if state_file.is_file():
        try:
            status = json.loads(state_file.read_text(encoding="utf-8")).get("status")
            if status in _LIVE:
                return True
            if status == "closed":
                return False
        except Exception:  # nosec B110 - unreadable state falls through to the index sniff
            pass
    try:
        text = (pack / "START-HERE.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(e in text for e in ("⏳", "⛔", "🔒"))


def _engagement_live(project_root: Path) -> bool:
    artifacts = project_root / "artifacts"
    if not artifacts.is_dir():
        return False
    if _pack_live(artifacts):
        return True
    try:
        return any(p.is_dir() and _pack_live(p) for p in artifacts.iterdir())
    except OSError:
        return False


def _lint(path: Path) -> list[str]:
    problems: list[str] = []
    # In-process, not a subprocess (2026-08-03 perf audit): py_compile.compile() does the
    # identical syntax-only check `python -m py_compile` runs - compiling to bytecode,
    # never executing the module - with zero process-spawn cost. str(PyCompileError) is
    # byte-for-byte the same "File ... / caret / SyntaxError: ..." text the subprocess's
    # stderr produced, so the tail-3-lines formatting below is unchanged.
    #
    # nit (2026-08-14 perf audit): the default cfile target is a __pycache__/*.pyc
    # dropped right next to the user's just-edited file, on every single Write/Edit
    # during a live engagement - pure litter in their working tree for what is only
    # ever a syntax check here, nothing downstream ever reads it. cfile=os.devnull
    # looks like the obvious fix but py_compile itself refuses it (FileExistsError:
    # "/dev/null is a non-regular file..." - a stdlib safety check against exactly
    # this shortcut). A real, throwaway temp file gets the same effect instead:
    # written outside the user's tree, then unconditionally removed in the finally
    # below regardless of which branch fires.
    tmp_cfile = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pyc", delete=False) as tmp:
            tmp_cfile = tmp.name
        py_compile.compile(str(path), cfile=tmp_cfile, doraise=True)
    except py_compile.PyCompileError as exc:
        tail = str(exc).strip().splitlines()[-3:]
        problems.append("syntax (py_compile): " + " | ".join(tail))
    except Exception:  # nosec B110 - a broken linter never becomes a broken edit
        pass
    finally:
        if tmp_cfile:
            try:
                os.unlink(tmp_cfile)
            except OSError:
                pass
    ruff = shutil.which("ruff")
    if ruff:
        try:
            result = subprocess.run(  # nosec B603 - resolved binary, fixed argv
                [ruff, "check", "--quiet", str(path)],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0 and result.stdout.strip():
                lines = result.stdout.strip().splitlines()
                problems.append(
                    f"ruff ({len(lines)} finding(s)): "
                    + " | ".join(lines[:5])
                    + (" …" if len(lines) > 5 else "")
                )
        except Exception:  # nosec B110
            pass
    return problems


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    try:
        tool_input = data.get("tool_input") or {}
        path = Path(str(tool_input.get("file_path") or ""))
        if path.suffix.lower() != ".py" or not path.is_file():
            return 0
        root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or Path.cwd())
        if not _engagement_live(root):
            return 0  # dormant session: standard Claude Code behaviour
        problems = _lint(path)
        if not problems:
            return 0
        sys.stderr.write(
            f"post-edit lint ({path.name}) - advisory, the write went through; fix while "
            "the file is in hand rather than at the review gate:\n- " + "\n- ".join(problems) + "\n"
        )
        return 2  # PostToolUse feedback channel: stderr reaches the model, nothing blocked
    except Exception:
        return 0  # advisory aid: always fail open


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
