#!/usr/bin/env python3
"""
PreToolUse guard: keep agents structurally downstream of masking.

Blocks Read / Grep / Glob / Bash tool calls that target raw, un-masked data (anything
that resolves under a `data/raw/` directory).  Agents must consume masked output
(data/masked/, via scripts/ingest.py) or synthetic data - never raw records, which
would egress to the model provider as prompt context (CLAUDE.md §5).

Protocol: read the PreToolUse JSON on stdin; exit 2 to block (stderr is fed back to
the model); exit 0 to allow.  The script errs on the side of blocking on ambiguous
input (fail-closed for path resolution errors).

FAIL-OPEN RESIDUAL RISK (Bash):
  String-matching shell commands is advisory only - arbitrary shell can bypass any
  lexical check (indirection, subshells, heredocs, `cd` etc.).  The real boundary for
  Bash is:
    1. The permissions.deny list in .claude/settings.json (file-level OS enforcement).
    2. data/raw/ being in .gitignore (prevents accidental commit of raw data).
    3. Masking-at-source: data never leaves the raw/ directory except via scripts/ingest.py.
  String-matching is belt-and-braces only; do NOT rely on it as the sole control.
  See docs/house-rules.md for the authoritative note on this.

See CLAUDE.md §5 and scripts/ingest.py for the full data-safety contract.
"""

from __future__ import annotations

# ^ Makes the PEP 585 annotations below (list[str]) lazy strings, so the module still
# *imports* on older interpreters instead of crashing at def-time - a crash would exit 1,
# which Claude Code treats as NON-blocking (the read would proceed). Note the runtime still
# needs Python >= 3.9 for Path.is_relative_to; run-guard.sh probes for that.

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Substring markers - belt-and-braces catch (fast path, tool-agnostic).
# Kept in addition to the normalised path check so that encoded or relative
# paths that can't be resolved still get a best-effort intercept.
# Only the specific `data/raw/` is matched: a bare `/raw/` is too broad (it
# false-positives on unrelated paths like /var/raw/ or foo/raw/bar and on benign
# commands that merely mention the string). The normalised realpath check in
# _is_under_raw() remains the primary, precise control for Read/Grep/Glob.
# ---------------------------------------------------------------------------
RAW_MARKERS = ("data/raw/",)

# ---------------------------------------------------------------------------
# Canonical raw-data directory - the directory we protect.
#
# This must be the USER'S PROJECT data/raw (where their real data lives), NOT
# the plugin's own directory. Claude Code passes `CLAUDE_PROJECT_DIR` to hook
# subprocesses (the project being worked on), so we resolve against that.
#   - repo-as-project:   CLAUDE_PROJECT_DIR == this repo        -> repo/data/raw
#   - plugin install:    CLAUDE_PROJECT_DIR == the user project -> <project>/data/raw
# We deliberately do NOT use CLAUDE_PLUGIN_ROOT here - that points at the plugin's
# own files, which is the wrong tree to protect. Fall back to the process cwd
# (the project dir for a hook subprocess) if the env var is absent.
# ---------------------------------------------------------------------------
_project_root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
_RAW_DIR = (Path(_project_root) / "data" / "raw").resolve()


def _is_under_raw(candidate: str) -> bool:
    """
    Return True if *candidate* resolves to a path inside the raw data directory.

    Strategy:
      1. Try os.path.realpath to canonicalise symlinks / relative components.
      2. Compare with _RAW_DIR using Path.is_relative_to (Python 3.9+).
      3. On any resolution error, fail CLOSED (return True = block).
    """
    if not candidate:
        return False
    try:
        resolved = Path(os.path.realpath(candidate)).resolve()
        return resolved == _RAW_DIR or resolved.is_relative_to(_RAW_DIR)
    except Exception:
        # Cannot resolve - err on the side of caution: block.
        return True


def _extract_path_candidates(tool: str, tool_input: dict) -> list[str]:
    """
    Return the list of string path tokens to check for a given tool.

    Read     -> file_path
    Grep     -> path, include (directory/glob the search is rooted in)
    Glob     -> pattern (the glob itself), path (directory root)
    Bash     -> command (full shell string - advisory only, see module docstring)
    """
    if tool == "Read":
        return [tool_input.get("file_path") or ""]

    if tool == "Grep":
        # Grep exposes 'path' (directory to search) and a glob filter. The current tool names the
        # glob 'glob'; older configs used 'include' - check both so neither is a dead check. Any
        # resolving under raw/ is enough to block. (A path-LESS Grep searches cwd and is not caught
        # here - that residual needs the OS/filesystem boundary; see ADR-002 Tier-3.)
        return [
            tool_input.get("path") or "",
            tool_input.get("glob") or "",
            tool_input.get("include") or "",
        ]

    if tool == "Glob":
        # Glob exposes 'pattern' (glob expression) and optionally 'path' (base dir).
        return [
            tool_input.get("pattern") or "",
            tool_input.get("path") or "",
        ]

    if tool == "Bash":
        # Belt-and-braces substring scan of the raw command string.
        # This is ADVISORY - see module-level docstring for the residual risk note.
        return [tool_input.get("command") or ""]

    return []


def _block(reason: str) -> None:
    sys.stderr.write(
        f"Blocked ({reason}): this targets raw, un-masked data (data/raw/). "
        "Agents must not read raw records into context (CLAUDE.md §5) - they "
        "would be sent to the model provider. "
        "Run `python -m scripts.ingest` to produce masked data under data/masked/, "
        "then use that (or synthetic data from scripts/gen_synthetic.py) instead.\n"
    )
    sys.exit(2)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        # Malformed hook payload - fail open so we never brick a session.
        # The deny list in settings.json remains active as the hard boundary.
        sys.exit(0)

    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    candidates = _extract_path_candidates(tool, tool_input)
    if not candidates:
        # Tool not in scope - allow.
        sys.exit(0)

    for candidate in candidates:
        if not candidate:
            continue
        # 1. Normalised path check (primary for Read / Grep / Glob).
        if _is_under_raw(candidate):
            _block(f"resolved path under data/raw/ - tool={tool}")
        # 2. Substring fallback (catches relative refs and Bash commands).
        if any(marker in candidate for marker in RAW_MARKERS):
            _block(f"raw-data marker in input - tool={tool}")

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Any unexpected crash (e.g. a payload shape main() doesn't handle) would exit 1,
        # which Claude Code treats as a NON-blocking error - the read would PROCEED. Fail
        # CLOSED instead: the deny-list backstop covers Read/Grep/Glob, but blocking here is
        # still the right default for a data guard. The deliberate exit-0 for malformed JSON
        # in main() is unaffected (sys.exit raises SystemExit, not an Exception).
        sys.stderr.write(
            "guard-raw-data crashed unexpectedly; failing closed (blocked). "
            "See docs/adr/ADR-002-safety-hook-threat-model.md.\n"
        )
        sys.exit(2)
