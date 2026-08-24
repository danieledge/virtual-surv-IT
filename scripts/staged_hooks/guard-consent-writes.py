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
    * `.claude/settings.json` / `.claude/settings.local.json` (permissions + hook wiring), or
    * `.pre-commit-config.yaml` (its hook entries execute via `git commit` - ADR-002 rec 14c), or
    * `.git/config` and `.git/hooks/` (audit 2026-08-01: CONSENT-EQUIVALENT execution config -
      `core.hooksPath` or an external diff/merge driver hands the next `git commit`/`git diff`
      arbitrary execution without ever writing the consent marker).
  Also BLOCK Write/Edit of the safety hooks themselves (`.claude/hooks/*`, `hooks/hooks.json`) -
  a model that can edit a guard can neuter it - and, on Bash, MUTATION of those paths
  (`sed -i`, `tee`, `cp`, `rm`, redirect); reads and static analysis of a hook stay allowed, which
  was the false-positive concern behind the original Write/Edit-only rule.

  ALLOW deleting the marker (closing the gate is always fail-safe: `rm .claude/.exec-consent`),
  and read-only inspection (ls/stat/cat/test/grep/echo without a redirect into a protected file).

Precision pass (2026-07-24, best-practice review gap: observed false blocks on read-only
commands whose ARGUMENT TEXT mentioned a protected filename):
  * the segment splitter is now QUOTE-AWARE - a `|` inside a quoted grep pattern
    (`grep -E 'a|b' .claude/settings.json`) no longer shatters the command into bogus segments
    that dodge the safe-verb check. `$(...)` and backticks still split even inside double quotes
    (they execute there), so command substitution cannot hide behind an outer safe verb;
  * `echo`/`printf` join the safe verbs - they cannot write without a redirect, and a redirect
    into a protected file is (still) checked FIRST on the whole segment;
  * a bare loop/conditional header (`for f in <files>`) is not a write; control-keyword prefixes
    (`do `, `then `, ...) are stripped before verb-matching so the BODY's verb is what's judged.
  The default-deny for unknown verbs touching a protected file is unchanged.

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

# The acting-session stamp behind guard session-scoping (2026-08-17): the execution gate
# arms only for the session whose id matches this file, so a model that could clobber or
# delete it would disarm that gate mid-engagement. Write-protected in EVERY session
# (dormant included), and unlike the consent marker, deleting it is NOT fail-safe - rm
# here is a disarm, not a close - so it gets its own mutation check past _SAFE_VERB.
# The sanctioned writers (engage_probe, engagement_state) write it from inside their own
# process, which a lexical Bash guard never sees - only a command that NAMES the file
# can be judged, and no legitimate command needs to.
_STAMP_RE = re.compile(r"artifacts[/\\]\.team-session\.json")
_STAMP_MUTATE_VERB = re.compile(r"^(rm|unlink|mv|truncate|shred)\b")

# .pre-commit-config.yaml is execution config: `git commit` runs its hook entries
# (`language: system` executes any command), so a model-writable config is a consent-free
# execution path (ADR-002 rec 14c). Write-protected; read-only inspection rides _SAFE_VERB.
_PRECOMMIT_RE = re.compile(r"\.pre-commit-config\.ya?ml\b")

# The guards themselves + their wiring: a model that can edit these can neuter every gate.
# Enforced on the precise Write/Edit channel; the Bash channel checks MUTATION only (see
# _HOOK_MUTATE) so legitimate static analysis (shellcheck/shfmt/ruff of the hooks) still runs.
# Maintenance goes through CST_ALLOW_CONFIG_EDIT.
#
# 2026-08-07 (found by a framework-wide audit, verified live before fixing):
# scripts/bash_hook_dispatcher.py is NOT under .claude/hooks/, so it matched neither branch
# below even though all four guards route through it (P4, 2026-07-31) - one Edit to its
# _CHECKS registry can neuter every guard via this "protected" channel, not just the
# already-documented Bash-lexical residual. Anchored to the LIVE copy only
# (scripts/bash_hook_dispatcher.py, end of path) - deliberately does NOT match
# scripts/staged_hooks/bash_hook_dispatcher.py, which the model must keep editing freely,
# same as every other staged_hooks/*.py file.
_HOOK_PATH_RE = re.compile(
    r"(\.claude[/\\]hooks[/\\]|(^|[/\\])hooks[/\\]hooks\.json$"
    r"|(^|[/\\])scripts[/\\]bash_hook_dispatcher\.py$)"
)

# `.git/config` and `.git/hooks/` are CONSENT-EQUIVALENT execution config (audit 2026-08-01).
# Nothing here writes the consent marker, so the "model cannot self-consent" property stayed
# technically true while its PURPOSE was defeated: point `core.hooksPath` at a model-written
# directory, or register an external diff/merge driver, and the next `git commit` / `git diff`
# executes arbitrary code with no marker and no gate. ADR-002 rec 14c recorded the external-driver
# shape as "adjacent unfixed" but left `.git/config` itself unprotected and never named
# `core.hooksPath`. Reads stay allowed (they ride _SAFE_VERB / _SAFE_GIT).
# Boundary is "not a word char, dot or hyphen" rather than "start or separator": the path can
# appear mid-command as a bare argument (`cp /tmp/evil .git/config`), where a space precedes it.
_GIT_CONFIG_RE = re.compile(r"(?:^|[^\w.-])\.git[/\\](?:config\b|hooks[/\\])")

# `git config` writing a key whose VALUE git later EXECUTES. Blocked regardless of verb, because
# the execution happens in a later git operation, not in this command - so the default-deny path
# (which only fires on a protected FILE token) would never see it.
# `config` must be the SUBCOMMAND, so only git's own global options may precede it. The first
# cut allowed any tokens before `config` ((?:\s+\S+)*?), which meant a commit message merely
# QUOTING the attack blocked the commit - `git commit -m "...git config core.hooksPath..."`.
# That is the fourth instance of the prose/argument false-positive class ADR-002 has already
# fixed three times (`make` in prose, `shellcheck a.sh b.sh`, the multi-.py launcher), and it
# was caught live on 2026-08-01 by the guard blocking the very commit that introduced it.
_GIT_CONFIG_CMD = re.compile(
    r"^git(?:\s+(?:-C\s+\S+|-c\s+\S+|--\S+(?:=\S+)?|-[pP]))*\s+config\b",
    re.IGNORECASE,
)

# `git -c <key>=<value> <any-subcommand>` applies config for ONE command, so it reaches the same
# execution keys without ever running `git config`. Same consent-equivalent effect, different
# spelling.
_GIT_INLINE_EXEC_CONFIG = re.compile(
    r"^git(?:\s+\S+)*?\s+-c\s+(?:core\.hookspath"
    r"|core\.(?:pager|editor|sshcommand|fsmonitor)"
    r"|[\w.-]*\.(?:external|textconv|command|driver|process|smudge|clean)"
    r"|alias\.[\w-]+)=",
    re.IGNORECASE,
)
_GIT_CONFIG_READ = re.compile(r"\s(?:--get(?:-all|-regexp|-urlmatch)?|--list|-l)\b", re.IGNORECASE)
_GIT_EXEC_KEY = re.compile(
    r"\b(?:core\.hookspath"
    r"|core\.(?:pager|editor|sshcommand|fsmonitor)"
    r"|[\w.-]*\.(?:external|textconv|command|driver|process|smudge|clean)"
    r"|alias\.[\w-]+)\b",
    re.IGNORECASE,
)

# A Bash write to a guard file neuters it (`sed -i 's/exit(2)/exit(0)/' .claude/hooks/...`).
# MUTATION verbs and redirects only - reading and static-analysing a hook stays allowed, which is
# the false-positive concern the Write/Edit-only rule was originally protecting. `rm` is included:
# unlike deleting the consent marker (which CLOSES the gate, fail-safe), deleting a guard DISARMS
# it.
#
# 2026-08-07: extended to the live dispatcher path too, same rationale as _HOOK_PATH_RE above -
# a Bash mutation of scripts/bash_hook_dispatcher.py is exactly as disarming as one on a guard
# under .claude/hooks/.
_HOOK_PATH_FRAGMENT = r"(?:\.claude[/\\]hooks[/\\]|scripts[/\\]bash_hook_dispatcher\.py)"
_HOOK_MUTATE = re.compile(
    rf">\s*\S*{_HOOK_PATH_FRAGMENT}"
    rf"|(?:^|[;&|\s])(?:sed\s+-i|tee|cp|mv|dd|install|ln|chmod|chown|truncate|rm)\b"
    rf"[^;&|]*{_HOOK_PATH_FRAGMENT}"
)

# Verbs that only read or delete the protected files - safe directions. Deleting the marker
# CLOSES the gate; reading config leaks nothing the model didn't already load. echo/printf
# cannot write without a redirect, and redirect-into-protected is checked BEFORE verbs.
_SAFE_VERB = re.compile(
    r"^(rm|unlink|ls|stat|test|\[|file|wc|cat|head|tail|grep|find|diff|jq|echo|printf)\b"
)

# A bare loop header only NAMES files; the loop BODY is judged as its own segment(s). BUT a
# body writing via the loop VARIABLE (`for f in <protected>; do touch $f`) is invisible to the
# per-segment protected-token check (variable indirection) - so a protected loop header is only
# safe when the WHOLE command contains no mutation verb / redirect at all.
_LOOP_HEADER = re.compile(r"^for\s+\S+\s+in\b[^;]*$")
_MUTATOR_ANYWHERE = re.compile(
    r"(?:^|[;&|`\s(])(?:touch|tee|cp|mv|dd|install|ln|chmod|chown|truncate)\b"
    r"|>|(?:^|\s)sed\s+-i\b|git\s+(?:checkout|restore|stash|config)\b"
)
# Control-keyword prefixes stripped before verb-matching, so `do grep ...` is judged as `grep ...`.
_CTRL_PREFIX = re.compile(r"^(?:do|then|else|elif|if|while|until)\s+")

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
    r">\s*\S*(\.exec-consent|\.claude[/\\]settings(\.local)?\.json|\.pre-commit-config\.ya?ml"
    r"|\.git[/\\]config\b|artifacts[/\\]\.team-session\.json)"
)

_WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


def _segments(cmd: str) -> list[str]:
    """Quote-aware split on shell separators (; | && || newline, backtick, $().

    Unlike the crude regex splitter, a separator inside QUOTES does not split - so a quoted
    grep pattern containing `|` stays part of its command and is judged with its real verb.
    Deliberate asymmetry: backticks and `$(` split even inside DOUBLE quotes, because command
    substitution executes there - an inner command must never hide behind an outer safe verb.
    Inside single quotes nothing executes, so nothing splits. Err toward MORE segments (fail-safe).
    """
    segs: list[str] = []
    buf: list[str] = []
    in_sq = in_dq = False
    i, n = 0, len(cmd)
    while i < n:
        ch = cmd[i]
        nxt = cmd[i + 1] if i + 1 < n else ""
        if ch == "\\" and not in_sq:
            buf.append(cmd[i : i + 2])
            i += 2
            continue
        if ch == "'" and not in_dq:
            in_sq = not in_sq
            buf.append(ch)
            i += 1
            continue
        if ch == '"' and not in_sq:
            in_dq = not in_dq
            buf.append(ch)
            i += 1
            continue
        if not in_sq:
            # command substitution executes even inside double quotes - always a boundary
            if ch == "`" or (ch == "$" and nxt == "("):
                segs.append("".join(buf))
                buf = []
                i += 2 if ch == "$" else 1
                continue
            if not in_dq:
                if ch == "\n" or ch == ";":
                    segs.append("".join(buf))
                    buf = []
                    i += 1
                    continue
                if ch in ("|", "&"):
                    segs.append("".join(buf))
                    buf = []
                    i += 2 if nxt == ch else 1
                    continue
        buf.append(ch)
        i += 1
    segs.append("".join(buf))
    return [s.strip() for s in segs if s.strip()]


def _truthy(val: str | None) -> bool:
    return bool(val) and val.strip().lower() not in ("", "0", "false", "no", "off")


def _protected(text: str, engaged: bool) -> bool:
    """Two tiers (2026-08-17, user decision). ALWAYS protected, every session: the
    consent marker (grant integrity - a dormant session could otherwise pre-forge it
    for a later engaged session to inherit), the session stamp (disarm channel),
    pre-commit config and git execution config (consent-equivalent execution a later
    engaged session would inherit the same way). ENGAGED sessions additionally protect
    settings*.json - harness config stays human-only while the team drives the
    session, but a dormant session managing its own permissions (or /doctor reading
    config through an interpreter, the 2026-08-17 live report) is plain Claude Code
    and is not interfered with."""
    norm = (text or "").replace("\\", "/")
    always = (
        _MARKER in norm
        or bool(_STAMP_RE.search(norm))
        or bool(_PRECOMMIT_RE.search(norm))
        or bool(_GIT_CONFIG_RE.search(norm))
    )
    if always:
        return True
    return engaged and bool(_SETTINGS_RE.search(norm))


def _team_invoked_this_session(payload) -> bool:
    """Same contract and fail direction as guard-code-execution's copy (see its
    docstring): positive stamp match arms; no stamp means the team was never invoked
    here (dormant); a payload with no session id fails toward armed."""
    sid = payload.get("session_id")
    if not sid:
        return True
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        stamp = json.loads(
            open(os.path.join(root, "artifacts", ".team-session.json"), encoding="utf-8").read()
        ).get("session")
    except Exception:
        return False
    return stamp == sid


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
        "This matches on the COMMAND TEXT, not on what the command would actually DO: a\n"
        "compound chain is blocked whole when ANY part names a protected path, and quoting\n"
        "or a heredoc body does not exempt it. So run the steps SEPARATELY, and keep\n"
        "protected paths out of command bodies that are not actually writing to them -\n"
        "both live causes (2026-08-21 and 2026-08-24: a documentation heredoc that merely\n"
        "mentioned the path, and a chain whose innocent steps were blocked with it).\n"
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
    engaged = _team_invoked_this_session(payload)

    if tool in _WRITE_TOOLS:
        target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if _protected(target, engaged):
            _block(f"the protected file targeted by {tool} ({target})")
        if _HOOK_PATH_RE.search((target or "").replace("\\", "/")):
            _block(f"the safety hooks themselves ({target}) - editing a guard can neuter it")
        sys.exit(0)

    if tool == "Bash":
        cmd = tool_input.get("command", "") or ""
        for seg in _segments(cmd):
            stripped = _CTRL_PREFIX.sub("", seg)
            # Consent-EQUIVALENT git execution config. Checked BEFORE the protected-token gate:
            # `git config core.hooksPath /tmp/h` names no protected FILE, so the default-deny
            # path below would never see it, yet it hands the next `git commit` arbitrary
            # execution. Reads (--get/--list) are allowed.
            if _GIT_INLINE_EXEC_CONFIG.match(stripped):
                _block(
                    "git one-shot execution config (`git -c <key>=<value>`) - git would execute "
                    f"this value on the command that follows ({seg[:100]})"
                )
            if (
                _GIT_CONFIG_CMD.match(stripped)
                and not _GIT_CONFIG_READ.search(seg)
                and _GIT_EXEC_KEY.search(seg)
            ):
                _block(
                    "git execution config (core.hooksPath / external diff-merge driver / alias) "
                    f"- git would execute this value on a later git command ({seg[:100]})"
                )
            # A Bash mutation of a guard file neuters the gate; reads/static analysis stay allowed.
            if _HOOK_MUTATE.search(seg):
                _block(
                    f"the safety hooks themselves via Bash ({seg[:120]}) - editing a guard "
                    "can neuter it"
                )
            if not _protected(seg, engaged):
                continue
            # A redirect can turn any verb into a write (`cat > marker`, `echo x >> settings`) -
            # but only when the redirect TARGET is protected (stderr-to-/dev/null is a read).
            if _REDIRECT_INTO_PROTECTED.search(seg):
                _block("consent-marker/config files via a shell redirect")
            if _FIND_MUTATE.search(seg):
                _block(f"consent-marker/config files via find -exec/-delete ({seg[:120]})")
            if _LOOP_HEADER.match(seg):
                if _MUTATOR_ANYWHERE.search(cmd):
                    _block(
                        "consent-marker/config files via a loop whose body mutates "
                        f"({seg[:80]} ...)"
                    )
                continue  # read-only loop over named files - the body is judged separately
            verb_seg = _CTRL_PREFIX.sub("", seg)
            if _SAFE_GIT.match(verb_seg):
                continue  # read-only git inspection of a protected path (ADR-002 rec 11)
            if _SAFE_VERB.match(verb_seg):
                # One carve-out from "delete is safe": deleting the SESSION STAMP is a
                # disarm (the execution gate keys on it), not a fail-safe close.
                if _STAMP_RE.search(seg) and _STAMP_MUTATE_VERB.match(verb_seg):
                    _block(
                        "the acting-session stamp (artifacts/.team-session.json) - "
                        "removing it disarms the session-scoped gates"
                    )
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
