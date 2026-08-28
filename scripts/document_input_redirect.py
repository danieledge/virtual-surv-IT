#!/usr/bin/env python3
"""PreToolUse redirect: document inputs go through the vendored converter, not hand-parsing.

Live failure (user report, 2026-07-29): handed a PDF mid-engagement, the team reached for
PowerShell, read the binary bytes and tried to extract text by hand - with no awareness
that `scripts/convert_file.py` (pypdf + openpyxl + docx support, deps VENDORED, zero pip,
built exactly for locked-down corporate environments) ships in the plugin. Prompt-surface
rules decay with context; this hook is the mechanical backstop ("verification as hooks,
not prompts").

What it does - ONLY while an engagement is live (dormancy: a session that never engaged
the team behaves as standard Claude Code, so this hook no-ops unless a pack under
`artifacts/` is in_progress/blocked/closing):

  * `Read` of a binary document (.pdf/.docx/.xlsx/.xlsm/.xls) -> BLOCKED with the exact
    convert_file command to run instead (the binary bytes are useless in context; the
    converter produces auditable text plus an evidence report).
  * `Bash` that reads a document's bytes by hand (Get-Content/ReadAllBytes/certutil/
    Format-Hex/strings/xxd/od/hexdump/cat/head on a .pdf/.docx/.xlsx) -> BLOCKED with the
    same redirect. Any command that already invokes `convert_file` passes untouched.

Not a safety guard: this is a quality redirect, deliberately separate from the three
ADR-002 guards, and it FAILS OPEN on any internal error. Blocking uses the standard hook
protocol (exit 2, reason on stderr). Text formats (csv/tsv/md/json) are never touched -
reading those directly is legitimate.

Wire via scripts/apply-document-redirect.sh (HUMAN-run - hook/config edits are human-only,
ADR-002 rec 5) into `.claude/settings.json` + `hooks/hooks.json`, matcher "Read|Bash".
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


def _vsit_paths():
    """The layout resolver (VSIT migration), imported lazily.

    Lazy because this file may run standalone from a bare clone where `scripts/` is not yet
    on sys.path. Searches its own directory AND a sibling `scripts/`, because several of
    these files also exist as staged copies under `scripts/staged_hooks/`."""
    import sys as _sys

    _here = Path(__file__).resolve().parent
    for _candidate in (_here, _here.parent, _here.parent / "scripts"):
        if (_candidate / "vsit_paths.py").is_file():
            if str(_candidate) not in _sys.path:
                _sys.path.insert(0, str(_candidate))
            break
    import vsit_paths

    return vsit_paths


_DOC_EXTS = (".pdf", ".docx", ".xlsx", ".xlsm", ".xls")
_DOC_EXT_RE = re.compile(r"\.(pdf|docx|xlsx|xlsm|xls)\b", re.I)
# Byte-level / hand-parsing reads of a document. Conservative on purpose: each pattern is a
# way to pull raw bytes or text out of a binary file in a shell, none of which produces
# defensible extraction. `convert_file` in the command exempts it before these are tried.
_HAND_PARSE_RE = re.compile(
    r"(?i)\b(get-content|readallbytes|readalltext|format-hex|certutil|strings|xxd|"
    r"hexdump|od|cat|head|tail|type|more|less)\b"
    r"|open\s*\([^)]*['\"]rb['\"]"
)
_LIVE_STATUSES = ("in_progress", "blocked", "closing")


def _pack_live(pack: Path) -> bool:
    state_file = pack / "engagement-state.json"
    if state_file.is_file():
        try:
            status = json.loads(state_file.read_text(encoding="utf-8")).get("status")
            if status in _LIVE_STATUSES:
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
    artifacts = _vsit_paths().engagements_dir(project_root)
    if not artifacts.is_dir():
        return False
    if _pack_live(artifacts):
        return True
    try:
        return any(p.is_dir() and _pack_live(p) for p in artifacts.iterdir())
    except OSError:
        return False


def _block(what: str) -> int:
    sys.stderr.write(
        f"Document-input redirect (team rule, operating guide 'Document inputs'): {what}\n"
        "Binary documents are never read or hand-parsed - the plugin bundles a converter "
        "with VENDORED dependencies (no pip, no installs, corporate-safe):\n"
        "  <python> -m scripts.convert_file <file>          # text/data + evidence report\n"
        "  <python> -m scripts.convert_file <file> --layout # PDFs with columns/tables\n"
        "  <python> -m scripts.convert_file <file> --list   # sheets/tables/pages inventory\n"
        "(plugin mode: invoke $PLUGIN_ROOT/scripts/convert_file.py by path; it is "
        "consent-free and allow-listed). If the report says pages are scanned/MISSING, ask "
        "the user for a text-bearing original - never transcribe by eye.\n"
    )
    return 2


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or Path.cwd())
    try:
        if not _engagement_live(root):
            return 0  # dormant session: standard Claude Code behaviour, untouched
        tool = data.get("tool_name") or ""
        tool_input = data.get("tool_input") or {}
        if tool == "Read":
            path = str(tool_input.get("file_path") or "")
            if path.lower().endswith(_DOC_EXTS):
                return _block(f"Read of binary document {Path(path).name!r} blocked.")
        elif tool == "Bash":
            command = str(tool_input.get("command") or "")
            if "convert_file" in command:
                return 0
            if _DOC_EXT_RE.search(command) and _HAND_PARSE_RE.search(command):
                return _block("shell/PowerShell hand-parsing of a binary document blocked.")
    except Exception:
        return 0  # quality redirect, not a guard: always fail open
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
