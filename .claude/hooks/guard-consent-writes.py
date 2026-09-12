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
import shlex
import sys

_MARKER = ".exec-consent"

# The human sign-off marker (W-2, 2026-09-12). Sign-off is the last gate in the Definition
# of Done and it is the HUMAN's word, so the file that records it belongs in the same
# always-protected tier as the consent marker: a model that can create it can sign off its
# own work. Matched on any path ending in the name, and lexically in a Bash command.
_SIGN_OFF = ".human-sign-off"

# ANCHORED at the extension (2026-09-12 audit, H-21). This was unanchored, so
# `.claude/settings.json.bak` and `.claude/settings.json.bak-2026-09-11` - both present in
# this repo - were protected as if they were live config, and every command naming a backup
# was blocked. A backup is not the wiring; the wiring is the file the harness reads.
_SETTINGS_RE = re.compile(r"\.claude[/\\]settings(\.local)?\.json(?![\w.-])", re.IGNORECASE)

# PATH NORMALISATION (2026-09-12 audit, H-7 and H-8). The only normalisation applied before
# matching was backslash -> slash, and every regex below was case-SENSITIVE. Two disarms
# followed directly:
#   * `Write(".claude/.EXEC-CONSENT")` passed this guard on a case-insensitive filesystem
#     (Windows, default macOS) while guard-code-execution's `os.path.isfile` resolved to the
#     same file and returned True - the model granting itself execution consent in one call;
#   * `Write(".claude/./hooks/guard-raw-data.py")` missed _HOOK_PATH_RE entirely and rewrote
#     a live guard, because `.` and `..` segments were never collapsed.
# guard-findings-pack-write.py had already fixed the `..` half for its own path check, with a
# comment describing this exact class of bug; the fix lived in one guard of the family and
# not the others. Case folding is applied on every platform, not just the case-insensitive
# ones: over-matching a path nobody legitimately writes is the safe direction, and the
# raw-data guard's marker has been IGNORECASE since ADR-002 rec 12 for the same reason.
_DOT_SEGMENT_RE = re.compile(r"/\./")
_LEADING_DOT_RE = re.compile(r"(?:^|(?<=[\s\"'=]))\./")
_PARENT_SEGMENT_RE = re.compile(r"(?!\.\.(?:/|$))[^/\s\"']+/\.\./")


def _norm(text: str) -> str:
    """Backslash-normalised, `.`/`..`-collapsed, case-folded text for path matching.

    Applied to a Write/Edit file_path and to a Bash SEGMENT alike, so it must be safe on a
    whole command string: it only ever rewrites path-shaped runs, and bounds its own
    iteration so a pathological input cannot spin here."""
    norm = (text or "").replace("\\", "/")
    for _ in range(8):
        collapsed = norm.replace("//", "/")
        collapsed = _DOT_SEGMENT_RE.sub("/", collapsed)
        collapsed = _LEADING_DOT_RE.sub("", collapsed)
        collapsed = _PARENT_SEGMENT_RE.sub("", collapsed)
        if collapsed == norm:
            break
        norm = collapsed
    return norm.lower()


# The acting-session stamp behind guard session-scoping (2026-08-17): the execution gate
# arms only for the session whose id matches this file, so a model that could clobber or
# delete it would disarm that gate mid-engagement. Write-protected in EVERY session
# (dormant included), and unlike the consent marker, deleting it is NOT fail-safe - rm
# here is a disarm, not a close - so it gets its own mutation check past _SAFE_VERB.
# The sanctioned writers (engage_probe, engagement_state) write it from inside their own
# process, which a lexical Bash guard never sees - only a command that NAMES the file
# can be judged, and no legitimate command needs to.
# The acting-session stamp, in EITHER layout. Named once so the reader below and this
# write-protection regex cannot disagree about where the file lives - they did, and the
# result was a stamp that was neither found nor protected in any project created since
# PREFER_NEW_LAYOUT became the default on 2026-08-28.
_STAMP_NAME = ".team-session.json"
_STAMP_RE = re.compile(
    r"(?:artifacts|VSIT[/\\]engagements)[/\\]\.team-session\.json", re.IGNORECASE
)
# `del` joins the list for Windows shells (2026-09-12, H-18) - Git Bash is the documented
# hook shell, but a Bash tool call can still reach cmd/PowerShell verbs on that platform.
_STAMP_MUTATE_VERB = re.compile(r"^(rm|unlink|del|mv|truncate|shred)\b", re.IGNORECASE)

# .pre-commit-config.yaml is execution config: `git commit` runs its hook entries
# (`language: system` executes any command), so a model-writable config is a consent-free
# execution path (ADR-002 rec 14c). Write-protected; read-only inspection rides _SAFE_VERB.
_PRECOMMIT_RE = re.compile(r"\.pre-commit-config\.ya?ml\b", re.IGNORECASE)

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
# WIDENED 2026-09-11. This protected the hook SCRIPTS and the dispatcher, and nothing else
# in the path that runs them. Three other files decide what executes on every hook call and
# were all writable:
#
#   .claude/.guard-interpreter, VSIT/local/guard-interpreter
#       run-guard.sh reads this and EXECUTES it, returning its exit code. A file holding
#       `/bin/true` made every hook exit 0, raw-data wall included, in every session.
#   scripts/guard_daemon.py, scripts/guard_daemon_client.py
#       with the daemon on, which is the default, these run on every hook call.
#   .claude/.guard-daemon-port
#       names where the client connects.
#
# Protecting the guards while leaving their launcher writable is not a boundary. run-guard.sh
# now also refuses a cached interpreter whose basename is not a python binary; that is the
# other half and neither is sufficient alone.
# WIDENED AGAIN 2026-09-12 (audit H-16). The list was still hand-maintained against the
# dispatcher of the day, and had gone stale against the wiring: `prompt_hook_dispatcher.py`
# and `stop_hook_dispatcher.py` are wired directly in settings.json/hooks.json,
# `locked_menu_guard.py` is a BLOCKING PreToolUse hook, `module_form_redirect.py` holds the
# permission-decision channel (it can emit `permissionDecision: allow`), and
# `enumeration_redirect.py`, `exploration_redirect.py`, `document_input_redirect.py`,
# `post_edit_lint.py`, `subagent_return_budget.py`, `session_resume_brief.py`,
# `persona_anchor.py`, `engage_probe_prefetch.py`, `dod_stop_gate.py` and
# `todo_panel_nudge.py` all run on a hook event. `vsit_paths.py` is imported by several of
# them. Every one was model-writable.
#
# Named as an explicit alternation rather than derived from settings.json at runtime: the
# wiring file is itself a thing this guard protects, so deriving the protected set FROM it
# would make the protection only as trustworthy as the file it protects. The cost is that a
# newly-registered hook has to be added here in the same change - stated, and covered by
# tests/test_guard_hook_registry.py.
_HOOK_SCRIPT_NAMES = (
    r"(?:bash_hook_dispatcher|prompt_hook_dispatcher|stop_hook_dispatcher"
    r"|guard_daemon|guard_daemon_client|locked_menu_guard|post_edit_lint"
    r"|subagent_return_budget|document_input_redirect|module_form_redirect"
    r"|enumeration_redirect|exploration_redirect|session_resume_brief|persona_anchor"
    r"|engage_probe_prefetch|dod_stop_gate|todo_panel_nudge|vsit_paths)"
)
_HOOK_PATH_RE = re.compile(
    r"(\.claude[/\\]hooks[/\\]|(^|[/\\])hooks[/\\]hooks\.json$"
    rf"|(^|[/\\])scripts[/\\]{_HOOK_SCRIPT_NAMES}\.py$"
    r"|(^|[/\\])\.claude[/\\]\.guard-[A-Za-z0-9._-]+$"
    r"|(^|[/\\])VSIT[/\\]local[/\\]guard-[A-Za-z0-9._-]+$)",
    re.IGNORECASE,
)

# The STAGING surface (2026-09-12 audit, H-2/W-16). `scripts/staged_hooks/*` and the
# `scripts/apply-*.sh` scripts that promote a staged file over a live guard are the one
# remaining way to replace every guard from inside a session: stage the edit, run the apply
# script. guard-code-execution now refuses to RUN an apply script at all; this is the other
# half, refusing to WRITE the thing it would install.
#
# Deliberately NOT protected in every session. The staging workflow is how guard fixes get
# authored, and a dormant or ordinary engaged session must keep doing it - that is the whole
# reason staged_hooks/ was carved OUT of the protection in the first place. The condition is
# engaged AND the execution-consent marker present: a session that already holds an execution
# grant must not ALSO be able to rewrite the gate that granted it. Those two capabilities in
# one session are the combination that turns a staged edit into a live one; either alone is
# the ordinary, intended workflow. Maintenance past this goes through CST_ALLOW_CONFIG_EDIT,
# which is human-set, like every other escape hatch here.
_STAGING_PATH_RE = re.compile(
    r"((^|[/\\])scripts[/\\]staged_hooks[/\\]|(^|[/\\])scripts[/\\]apply-[A-Za-z0-9._-]*\.sh)",
    re.IGNORECASE,
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
_GIT_CONFIG_RE = re.compile(r"(?:^|[^\w.-])\.git[/\\](?:config\b|hooks[/\\])", re.IGNORECASE)

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
_HOOK_PATH_FRAGMENT = (
    r"(?:\.claude[/\\]hooks[/\\]"
    rf"|scripts[/\\]{_HOOK_SCRIPT_NAMES}\.py"
    r"|\.claude[/\\]\.guard-[A-Za-z0-9._-]+"
    r"|VSIT[/\\]local[/\\]guard-[A-Za-z0-9._-]+)"
)
_MUTATE_VERBS = r"(?:sed\s+-i|tee|cp|mv|dd|install|ln|chmod|chown|truncate|rm|del)"
_HOOK_MUTATE = re.compile(
    rf">\s*\S*{_HOOK_PATH_FRAGMENT}"
    rf"|(?:^|[;&|\s]){_MUTATE_VERBS}\b[^;&|]*{_HOOK_PATH_FRAGMENT}",
    re.IGNORECASE,
)
# Same shape for the staging surface, applied only under the engaged+marker condition above.
_STAGING_PATH_FRAGMENT = r"(?:scripts[/\\]staged_hooks[/\\]|scripts[/\\]apply-[A-Za-z0-9._-]*\.sh)"
_STAGING_MUTATE = re.compile(
    rf">\s*\S*{_STAGING_PATH_FRAGMENT}"
    rf"|(?:^|[;&|\s]){_MUTATE_VERBS}\b[^;&|]*{_STAGING_PATH_FRAGMENT}",
    re.IGNORECASE,
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
    r">\s*\S*(\.exec-consent|\.human-sign-off"
    r"|\.claude[/\\]settings(\.local)?\.json|\.pre-commit-config\.ya?ml"
    r"|\.git[/\\]config\b|(?:artifacts|VSIT[/\\]engagements)[/\\]\.team-session\.json)",
    re.IGNORECASE,
)

_WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")

# An `env` key the guards read (2026-09-12 audit, H-1). settings.json's `env` block is
# exported into hook subprocesses, so writing `{"env": {"CST_ALLOW_EXEC": "1"}}` there opens
# the execution gate for every future session from inside the repo - the exact channel both
# guards' docstrings claim the model does not have. Blocked in EVERY session, engaged or not,
# because a dormant session must not pre-forge what a later engaged session inherits
# (CLAUDE.md's dormancy carve-out). Ordinary settings.json edits stay allowed in a dormant
# session by owner decision; only the CST_ env keys are lifted out of that.
_CST_KEY_RE = re.compile(r"[\"']?CST_[A-Za-z0-9_]*[\"']?\s*[:=]", re.IGNORECASE)
_CST_BASH_RE = re.compile(r"CST_ALLOW", re.IGNORECASE)

# Search verbs whose PATTERN operand is text ABOUT a path, not a path (2026-09-12, H-21).
# `grep -r '.git/config' docs/` was blocked as though it were writing git config. The
# raw-data guard fixed this same false-positive class for itself on 2026-08-01; this brings
# the consent guard in line.
_SEARCH_VERBS = ("grep", "egrep", "fgrep", "rg", "ag", "ack", "ripgrep")
_PATTERN_FLAGS = ("-e", "-f", "--regexp", "--file")

# Heredoc opener: `<<EOF`, `<<-EOF`, `<<'EOF'`, `<<"EOF"`.
_HEREDOC_START_RE = re.compile(r"<<-?\s*([\"']?)([A-Za-z_][A-Za-z0-9_]*)\1")

_OPERATOR_PREFIXES = (">", "<", "|", "&", ";", "$", "(", ")")


def _strip_heredoc_bodies(cmd: str) -> str:
    """Drop heredoc BODIES, keeping the opener and terminator lines.

    Reproduced live during the 2026-09-12 audit: `cat > /tmp/.../t2.py <<'PYEOF'` writing an
    unrelated analysis script into a scratchpad was blocked because the body happened to
    contain the literal string `.exec-consent`. The guard's own block message already
    conceded the case ("a documentation heredoc that merely mentioned the path"). A body is
    DATA being written somewhere, and where it is written is decided on the opener line,
    which is kept and still checked - including its redirect target.

    This does mean a mutation hidden inside a heredoc body is no longer read as one. That
    body only executes if it is fed to a shell (`bash <<'EOF' ... EOF`), and
    guard-code-execution blocks heredoc-into-interpreter outright as of the same audit
    (H-10), so the pair closes where each half alone would not.
    """
    lines = cmd.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for _quote, delim in _HEREDOC_START_RE.findall(line):
            while i < len(lines) and lines[i].strip() != delim:
                i += 1
            if i < len(lines):
                out.append(lines[i])
                i += 1
    return "\n".join(out)


def _search_residual(segment: str) -> str | None:
    """A search command minus its PATTERN operand, or None when it is not a search."""
    try:
        tokens = shlex.split(segment)
    except Exception:  # noqa: BLE001 - unparseable: judge the whole segment as before
        return None
    if not tokens or os.path.basename(tokens[0]) not in _SEARCH_VERBS:
        return None
    kept = [tokens[0]]
    pattern_taken = False
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        base = tok.split("=", 1)[0]
        if base in _PATTERN_FLAGS:
            pattern_taken = True
            kept.append(tok)
            if "=" not in tok:
                i += 2  # the flag's value IS the pattern (or a pattern file) - drop it
                continue
            i += 1
            continue
        if tok.startswith("-") and len(tok) > 1:
            kept.append(tok)
            i += 1
            continue
        if not pattern_taken:
            pattern_taken = True  # the first bare token is the pattern
            i += 1
            continue
        kept.append(tok)
        i += 1
    return " ".join(kept)


def _cd_target(segment: str) -> str | None:
    """The directory a `cd`/`pushd` segment moves to, or None."""
    match = re.match(r"^(?:cd|pushd)\s+(?:-\S+\s+)*([^\s;&|]+)\s*$", segment.strip(), re.IGNORECASE)
    if not match:
        return None
    target = match.group(1).strip("\"'")
    return target or None


def _requalify(text: str, cwd: str) -> str:
    """Re-attach *cwd* to the relative path operands of *text*.

    WHY (2026-09-12 audit, H-9). Every Bash check here matches the literal path string inside
    ONE segment, and `cd` in an earlier segment changes what a later bare filename means. Three
    disarms followed, none of which names a protected path in the segment that does the work:
    `cd artifacts && rm .team-session.json`, `cd .claude && printf ... > .guard-daemon-port`,
    and the raw-data guard's own `cd data && head raw/...`.

    Best-effort and lexical, like everything else here. The residual, stated: a cd through a
    variable, a subshell, `cd -`, or a path built at runtime is still invisible - this tracks
    the literal, single-segment `cd <dir>` form, which is the one the disarms above use. The
    verb (token 0) is never requalified, so the safe-verb and delete-is-fail-safe rules keep
    reading the real command.
    """
    tokens = text.split()
    if not tokens:
        return text
    out = [tokens[0]]
    base = cwd.rstrip("/")
    for tok in tokens[1:]:
        lead = ""
        rest = tok
        while rest[:1] in (">", "<"):
            lead += rest[0]
            rest = rest[1:]
        bare = rest.strip("\"'")
        if (
            not bare
            or rest.startswith("-")
            or bare[:1] in ("/", "~")
            or bare[:1] in _OPERATOR_PREFIXES
        ):
            out.append(tok)
            continue
        out.append(f"{lead}{base}/{bare}")
    return " ".join(out)


def _introduces_cst_env(text: str) -> bool:
    """Does this new settings content declare an `env` key starting CST_?

    A full document parses, so the `env` block is read precisely. An Edit carries a FRAGMENT
    that will not parse, so it falls back to a lexical scan - over-matching a CST_ key in a
    settings edit is the safe direction, and no legitimate settings edit needs to name one.
    """
    if not text:
        return False
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001 - a fragment, not a document
        return bool(_CST_KEY_RE.search(text))
    if isinstance(data, dict):
        env = data.get("env")
        if isinstance(env, dict):
            return any(str(key).upper().startswith("CST_") for key in env)
        return False
    return bool(_CST_KEY_RE.search(text))


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


def _declared_in_settings_env(name: str) -> bool:
    """Is *name* set through a settings.json `env` block rather than the launch environment?

    The twin of guard-code-execution's copy (see its docstring for the full reasoning, H-1):
    this guard's own docstring says CST_ALLOW_CONFIG_EDIT is human-only because "the model
    cannot set it for this hook subprocess", which is true of the launch environment and
    false of a settings `env` block. A failure to read means "not declared", so a project
    with no settings at all keeps the launch-environment override - this function only ever
    removes an authorisation, never grants one.
    """
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    for leaf in ("settings.json", "settings.local.json"):
        try:
            with open(os.path.join(root, ".claude", leaf), encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:  # noqa: BLE001 - absent/unreadable/unparseable: not declared  # nosec B112 - absent/unreadable/unparseable settings file: not declared
            continue
        env = data.get("env") if isinstance(data, dict) else None
        if isinstance(env, dict) and name in env:
            return True
    return False


def _exec_consent_present() -> bool:
    """Does this project hold the human execution-consent marker? (see _STAGING_PATH_RE)"""
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return os.path.isfile(os.path.join(root, ".claude", _MARKER))


def _protected(text: str, engaged: bool, staging_locked: bool = False) -> bool:
    """Two tiers (2026-08-17, user decision). ALWAYS protected, every session: the
    consent marker (grant integrity - a dormant session could otherwise pre-forge it
    for a later engaged session to inherit), the session stamp (disarm channel),
    pre-commit config and git execution config (consent-equivalent execution a later
    engaged session would inherit the same way). ENGAGED sessions additionally protect
    settings*.json - harness config stays human-only while the team drives the
    session, but a dormant session managing its own permissions (or /doctor reading
    config through an interpreter, the 2026-08-17 live report) is plain Claude Code
    and is not interfered with.

    2026-09-12 additions: the human sign-off marker joins the ALWAYS tier (W-2 - a model
    that can create it can sign off its own work), and `staging_locked` adds a third,
    narrower tier for `scripts/staged_hooks/**` and `scripts/apply-*.sh`, armed only when
    the session is BOTH engaged and already holding execution consent (see
    _STAGING_PATH_RE for why that pair, and not either alone)."""
    norm = _norm(text)
    always = (
        _MARKER in norm
        or _SIGN_OFF in norm
        or bool(_STAMP_RE.search(norm))
        or bool(_PRECOMMIT_RE.search(norm))
        or bool(_GIT_CONFIG_RE.search(norm))
    )
    if always:
        return True
    if staging_locked and _STAGING_PATH_RE.search(norm):
        return True
    return engaged and bool(_SETTINGS_RE.search(norm))


# See guard-code-execution.py's copy for the full rationale: the stamp used to hold ONE
# session id, so a second /engage disarmed the first session and a resume disarmed itself.
# It now carries a list, capped, newest last. Both formats are read.
_MAX_STAMPED_SESSIONS = 8


def _stamped_session_ids(stamp_path) -> tuple:
    """Every session id this stamp file arms, legacy and current formats alike."""
    try:
        with open(stamp_path, encoding="utf-8") as handle:
            data = json.loads(handle.read())
    except Exception:  # noqa: BLE001 - absent/unreadable/unparseable: arms nothing
        return ()
    if not isinstance(data, dict):
        return ()
    ids = []
    for key in ("session", "session_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            ids.append(value)
    sessions = data.get("sessions")
    if isinstance(sessions, list):
        for entry in sessions[-_MAX_STAMPED_SESSIONS:]:
            value = entry.get("id") if isinstance(entry, dict) else entry
            if isinstance(value, str) and value:
                ids.append(value)
    return tuple(ids)


def _team_invoked_this_session(payload) -> bool:
    """Same contract and fail direction as guard-code-execution's copy (see its
    docstring): positive stamp match arms; no stamp means the team was never invoked
    here (dormant); a payload with no session id fails toward armed."""
    sid = payload.get("session_id")
    if not sid:
        return True
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    # BOTH LAYOUTS since 2026-09-11, matching guard-code-execution. This read the legacy
    # path literally while the writers place the stamp through vsit_paths.engagements_dir(),
    # which resolves to VSIT/engagements/ for any project with neither layout present, the
    # default since PREFER_NEW_LAYOUT became true on 2026-08-28. So in every project created
    # since then the stamp was never found and this returned False, leaving the
    # settings write-protection off for engaged sessions.
    for stamp_path in (
        os.path.join(root, "VSIT", "engagements", _STAMP_NAME),
        os.path.join(root, "artifacts", _STAMP_NAME),
    ):
        if sid in _stamped_session_ids(stamp_path):
            return True
    return False


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

    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    engaged = _team_invoked_this_session(payload)
    staging_locked = engaged and _exec_consent_present()

    # The CST_ env-key rule is checked BEFORE the maintenance escape hatch, and before the
    # dormancy tiers: CST_ALLOW_CONFIG_EDIT is itself one of the variables settings.json's
    # `env` block can hand this subprocess, so honouring it first would let the very thing
    # being blocked authorise the block's removal (2026-09-12 audit, H-1).
    if tool in _WRITE_TOOLS:
        target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if _SETTINGS_RE.search(_norm(target)):
            new_text = tool_input.get("content") or tool_input.get("new_string") or ""
            if _introduces_cst_env(new_text):
                _block(
                    "a CST_* key in .claude/settings.json's `env` block - that block is "
                    "exported into hook subprocesses, so it is a way to grant execution or "
                    "config-edit consent to every future session from inside the repo. The "
                    "human sets CST_ variables in the LAUNCH environment"
                )
    elif tool == "Bash":
        raw_cmd = tool_input.get("command", "") or ""
        for seg in _segments(_strip_heredoc_bodies(raw_cmd)):
            if _SETTINGS_RE.search(_norm(seg)) and _CST_BASH_RE.search(seg):
                _block(
                    "a CST_ALLOW* variable in .claude/settings.json via Bash - the settings "
                    "`env` block is exported into hook subprocesses, so writing one there "
                    "grants consent to every future session. The human sets CST_ variables "
                    "in the LAUNCH environment"
                )

    if _truthy(os.environ.get("CST_ALLOW_CONFIG_EDIT")):
        if _declared_in_settings_env("CST_ALLOW_CONFIG_EDIT"):
            sys.stderr.write(
                "Ignoring CST_ALLOW_CONFIG_EDIT: it is declared in this project's "
                ".claude/settings.json `env` block, which is a file the model can write - so "
                "it is not the human-only launch-environment grant this guard accepts.\n"
            )
        else:
            sys.exit(0)

    if tool in _WRITE_TOOLS:
        target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if _protected(target, engaged, staging_locked):
            _block(f"the protected file targeted by {tool} ({target})")
        if _HOOK_PATH_RE.search(_norm(target)):
            _block(f"the safety hooks themselves ({target}) - editing a guard can neuter it")
        sys.exit(0)

    if tool == "Bash":
        cmd = _strip_heredoc_bodies(tool_input.get("command", "") or "")
        cwd = ""
        for seg in _segments(cmd):
            # Track a literal `cd`/`pushd` so a later bare filename is judged against the
            # directory it actually names (H-9). The cd segment itself is judged too.
            moved = _cd_target(seg)
            # The text the path checks see: the search PATTERN operand dropped (H-21), and a
            # second probe with the tracked cwd re-attached (H-9).
            scan = _search_residual(seg) or seg
            probes = [scan]
            if cwd:
                probes.append(_requalify(scan, cwd))
            if moved:
                cwd = (
                    moved
                    if moved.startswith("/")
                    else (f"{cwd.rstrip('/')}/{moved}" if cwd else moved)
                )
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
            # Judged over every probe so a preceding `cd .claude` cannot hide the path (H-9).
            if any(_HOOK_MUTATE.search(_norm(p)) for p in probes):
                _block(
                    f"the safety hooks themselves via Bash ({seg[:120]}) - editing a guard "
                    "can neuter it"
                )
            if staging_locked and any(_STAGING_MUTATE.search(_norm(p)) for p in probes):
                _block(
                    f"the staged hooks or an apply script via Bash ({seg[:120]}) - this "
                    "session already holds execution consent, so it must not also be able to "
                    "rewrite the gate that granted it"
                )
            if not any(_protected(p, engaged, staging_locked) for p in probes):
                continue
            # A redirect can turn any verb into a write (`cat > marker`, `echo x >> settings`) -
            # but only when the redirect TARGET is protected (stderr-to-/dev/null is a read).
            if any(_REDIRECT_INTO_PROTECTED.search(_norm(p)) for p in probes):
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
                # The carve-outs from "delete is safe". Deleting the CONSENT MARKER closes
                # the execution gate, which is why `rm` is a safe verb at all. Deleting
                # anything else protected is the opposite (2026-09-12 audit, H-18): removing
                # the session stamp disarms the session-scoped gates, and removing
                # settings.json takes the hook wiring AND the permissions.deny list that
                # guard-raw-data names as the real Read/Grep/Glob boundary with it. The stamp
                # was carved out in 2026-08-17 and the rest was left behind.
                if _STAMP_MUTATE_VERB.match(verb_seg) and any(
                    _STAMP_RE.search(_norm(p))
                    or _SETTINGS_RE.search(_norm(p))
                    or _PRECOMMIT_RE.search(_norm(p))
                    or _GIT_CONFIG_RE.search(_norm(p))
                    or _SIGN_OFF in _norm(p)
                    for p in probes
                ):
                    _block(
                        "config that deleting does not fail safe - the acting-session stamp, "
                        "settings.json (hook wiring plus the permissions.deny backstop), "
                        "pre-commit config, git execution config or the human sign-off "
                        f"marker ({seg[:100]})"
                    )
                continue  # read, or delete of the consent marker - safe direction
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
