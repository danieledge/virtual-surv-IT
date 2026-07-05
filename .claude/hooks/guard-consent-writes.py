#!/usr/bin/env python3
"""
PreToolUse guard: the model must not grant itself execution consent or edit harness config.

ADR-002 Tier-1 rec 5. The execution gate (guard-code-execution.py) can be opened by the marker
file `.claude/.exec-consent` - and until this guard existed, the model itself wrote that marker
when the user answered "yes" at intake. ADR-002 named that the gate's central weakness: nothing
distinguished user-authorised marker-writing from a confused or prompt-injected model writing it
spontaneously. This guard closes the loop:

  BLOCK (exit 2) any model-driven Write/Edit/NotebookEdit - and, lexically, any Bash write -
  targeting:
    * `.exec-consent` (the execution-consent marker), or
    * `.claude/settings.json` / `.claude/settings.local.json` (permissions + hook wiring).
  Also BLOCK Write/Edit of the safety hooks themselves (`.claude/hooks/*`, `hooks/hooks.json`) -
  a model that can edit a guard can neuter it. (Write/Edit channel only: Bash rules for hook
  paths would false-positive on legitimate static analysis and are advisory anyway, ADR-002.)

  ALLOW deleting the marker (closing the gate is always fail-safe: `rm .claude/.exec-consent`),
  and read-only inspection (ls/stat/cat/test/grep without a redirect into a protected file).

How consent is granted now (human-only paths):
  * the user runs `touch <project>/.claude/.exec-consent` in any terminal (or with the `!`
    prefix as the first characters of the Claude prompt line), or
  * the user sets CST_ALLOW_EXEC=1 in the launch environment (the hard override).

Maintenance escape hatch: CST_ALLOW_CONFIG_EDIT=1 (human-set in the launch environment - the
model cannot set it for this hook subprocess) permits config edits for deliberate maintenance
sessions, mirroring CST_ALLOW_EXEC.

FAIL-OPEN RESIDUAL RISK (Bash): as with the other guards, string-matching shell is advisory -
see ADR-002. The Write/Edit path check is the strong control; the Bash rules are belt-and-braces.
Protocol: PreToolUse JSON on stdin; exit 2 blocks (stderr fed to the model); exit 0 allows.
Unexpected crashes fail CLOSED (exit 2) - see ADR-002 §exit-code semantics.
"""

from __future__ import annotations

import json
import os
import re
import sys

_MARKER = ".exec-consent"
_SETTINGS_RE = re.compile(r"\.claude[/\\]settings(\.local)?\.json")

# The guards themselves + their wiring: a model that can edit these can neuter every gate.
# Enforced on the precise Write/Edit channel only - Bash rules for these paths would false-
# positive on legitimate static analysis (shellcheck/shfmt of the hooks) and stay advisory
# anyway (ADR-002). Maintenance goes through CST_ALLOW_CONFIG_EDIT.
_HOOK_PATH_RE = re.compile(r"(\.claude[/\\]hooks[/\\]|(^|[/\\])hooks[/\\]hooks\.json$)")

# Same crude-on-purpose splitter as guard-code-execution.py: err toward inspecting MORE.
_SEGMENT_SPLIT = re.compile(r";|&&|\|\||\||\n|`|\$\(")

# Verbs that only read or delete the protected files - safe directions. Deleting the marker
# CLOSES the gate; reading config leaks nothing the model didn't already load.
_SAFE_VERB = re.compile(r"^(rm|unlink|ls|stat|test|\[|file|wc|cat|head|tail|grep|find|diff|jq)\b")

# Read-only git subcommands may legitimately touch a protected path (e.g. `git check-ignore
# .claude/.exec-consent`, `git diff .claude/settings.json`) - they inspect, never mutate. Only
# unambiguously read-only subcommands: NOT checkout/restore/stash/config, which can revert or
# rewrite the protected file (ADR-002 rec 11).
_SAFE_GIT = re.compile(
    r"^git\s+(status|diff|log|show|blame|ls-files|check-ignore|cat-file|rev-parse|describe)\b"
)
# `find ... -exec/-execdir/-delete` mutates - it must NOT ride the safe `find` verb above.
_FIND_MUTATE = re.compile(r"^find\b.*\s-(?:exec(?:dir)?|delete)\b")

# A redirect is only a write to a protected file if its TARGET is one - `ls x 2>/dev/null` is a
# read with a harmless stderr redirect (a real false positive found in live use, 2026-07-01).
_REDIRECT_INTO_PROTECTED = re.compile(
    r">\s*\S*(\.exec-consent|\.claude[/\\]settings(\.local)?\.json)"
)

_WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


def _truthy(val: str | None) -> bool:
    return bool(val) and val.strip().lower() not in ("", "0", "false", "no", "off")


def _protected(text: str) -> bool:
    norm = (text or "").replace("\\", "/")
    return _MARKER in norm or bool(_SETTINGS_RE.search(norm))


def _block(what: str) -> None:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    marker = os.path.join(root, ".claude", ".exec-consent")
    sys.stderr.write(
        "Blocked (consent-write gate, ADR-002 rec 5): the model must not create or modify "
        f"{what}. Execution consent and harness config are HUMAN-only:\n"
        f"- to grant execution consent, the USER runs `touch {marker}` in any terminal (or "
        f"`! touch {marker}` as the first characters of the prompt line), or sets "
        "CST_ALLOW_EXEC=1 in the launch environment;\n"
        "- config/hook edits need CST_ALLOW_CONFIG_EDIT=1 set by the human in the launch "
        "environment.\n"
        "Deleting the marker (closing the gate) and read-only inspection remain allowed.\n"
    )
    sys.exit(2)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # malformed payload - never brick the session (matches the other guards)

    if _truthy(os.environ.get("CST_ALLOW_CONFIG_EDIT")):
        sys.exit(0)

    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    if tool in _WRITE_TOOLS:
        target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if _protected(target):
            _block(f"the protected file targeted by {tool} ({target})")
        if _HOOK_PATH_RE.search((target or "").replace("\\", "/")):
            _block(f"the safety hooks themselves ({target}) - editing a guard can neuter it")
        sys.exit(0)

    if tool == "Bash":
        cmd = tool_input.get("command", "") or ""
        for seg in (s.strip() for s in _SEGMENT_SPLIT.split(cmd) if s.strip()):
            if not _protected(seg):
                continue
            # A redirect can turn any verb into a write (`cat > marker`, `echo x >> settings`) -
            # but only when the redirect TARGET is protected (stderr-to-/dev/null is a read).
            if _REDIRECT_INTO_PROTECTED.search(seg):
                _block("consent-marker/config files via a shell redirect")
            if _FIND_MUTATE.search(seg):
                _block(f"consent-marker/config files via find -exec/-delete ({seg[:120]})")
            if _SAFE_GIT.match(seg):
                continue  # read-only git inspection of a protected path (ADR-002 rec 11)
            if _SAFE_VERB.match(seg):
                continue  # read or delete - safe direction
            # Default-deny: unknown verb touching a protected file (touch/cp/mv/sed -i/git
            # checkout/...) - opening the gate or mutating config must come from the human.
            _block(f"consent-marker/config files via Bash ({seg[:120]})")

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Exit 1 would be treated as NON-blocking (the write would proceed) - fail CLOSED,
        # consistent with the other guards (ADR-002 §exit-code semantics).
        sys.stderr.write(
            "guard-consent-writes crashed unexpectedly; failing closed (blocked). "
            "See docs/adr/ADR-002-safety-hook-threat-model.md.\n"
        )
        sys.exit(2)
