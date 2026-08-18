#!/usr/bin/env python3
"""
PreToolUse guard: don't EXECUTE the code under review without human authorisation.

Reviewing code should be **static** (read it + analysers that parse it). Running it - its
tests, the script itself, or a profiler/benchmark - executes potentially untrusted code and is
a real risk (side effects, touching live systems, hostile code). This hook makes "static by
default" a harness-enforced rule, not just a prompt the model might forget (CLAUDE.md §7).

Policy (Bash tool) - ALLOW everything if execution has been authorised, else BLOCK code that
executes. Authorisation is granted by EITHER:
  * the consent marker file `<project>/.claude/.exec-consent` - HUMAN-created (the model is
    blocked from writing it by guard-consent-writes.py, ADR-002 rec 5), or
  * the env var CST_ALLOW_EXEC (truthy), set by the HUMAN in the launch environment / settings
    `env` (the harder override - the model cannot set it for this hook subprocess; also handy
    for CI).
Otherwise -> BLOCK (exit 2) commands that EXECUTE code: test runners, profilers/benchmarks, and
running a script/interpreter on a file. Static analysers, git and read-only utilities are
allowed, as are the team's own `scripts/` helpers - including the plugin's bundled copies
invoked by absolute path from a foreign project (basename-whitelisted; see _TEAM_ALLOW), with
Windows backslash paths and the `py` launcher covered (0.4.1).

Note on strength: consent is human-only since ADR-002 rec 5; this gate plus the consent-write
gate is consent-recording + a safety net, not a sandbox.

FAIL-OPEN RESIDUAL RISK (Bash): string-matching arbitrary shell is advisory only - obscure
constructs can bypass any lexical check (indirection, subshells, eval). This is a strong
default, not a perfect sandbox. The real assurance is: static-by-default behaviour, the
consent/disclaimer at intake, this gate, and the user keeping genuinely dangerous code out of
the review. See CLAUDE.md §7 and docs/house-rules.md.

Protocol: read the PreToolUse JSON on stdin; exit 2 to block (stderr is fed to the model);
exit 0 to allow. Only the Bash tool is in scope.
"""

from __future__ import annotations

# ^ Makes the PEP 604/585 annotations below (str | None, list[str]) lazy strings, so the
# module still *imports* on older interpreters instead of crashing at def-time - a crash
# would exit 1, which Claude Code treats as NON-blocking (the command would proceed).

import json
import os
import re
import sys


def _truthy(val: str | None) -> bool:
    return bool(val) and val.strip().lower() not in ("", "0", "false", "no", "off")


def _exec_authorised() -> bool:
    """Execution is permitted if the human set CST_ALLOW_EXEC, or the consent marker exists."""
    if _truthy(os.environ.get("CST_ALLOW_EXEC")):
        return True
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return os.path.isfile(os.path.join(root, ".claude", ".exec-consent"))


# Interpreter token: python / python3 / python3.11 (ADR-002: the old `python3?` let
# `python3.11 evil.py` slip past because `.11` broke the `\s` anchor) - and, since 0.4.1, the
# Windows `py` launcher: without it, `py evil.py` was not blocked AND `py -m scripts.x` was
# not allow-listed, so Windows sessions were wrong in both directions.
# The bare `py` alternative carries a negative lookbehind: it must be a standalone token, not
# the tail of a filename/word (`a.py b.py` blocked read-only git/grep/wc over two .py files -
# the third prose/argument FP, after `make` and `sh <file>.sh`; ADR-002 rec 14a).
_PY = r"(?:python(?:3(?:\.\d+)?)?|(?<![\w.-])py)"

# Path separator: forward slash OR backslash - Windows commands arrive with backslash paths
# (`python C:\plugin\scripts\render_html.py`) and a slash-only allow-list blocked them (0.4.1).
_SEP = r"[/\\]"

# Commands/patterns that EXECUTE code. Evaluated PER SEGMENT (see _segments). Each carries why
# it counts as "execution". (Hardened per docs/adr/ADR-002 Tier 1; false positives fixed in
# 0.4: `make` anchored to segment start - it blocked commit messages containing the word;
# `sh <file>.sh` given a lookbehind - `shellcheck a.sh b.sh` matched the ".sh " boundary.)
_EXEC_PATTERNS = [
    r"^(?:\w+=\S+\s+)*pytest\b",  # test runner - anchored so 'pytest' in prose is not the command
    rf"\b{_PY}\s+-m\s+pytest\b",  # same, module form
    r"^(?:\w+=\S+\s+)*unittest\b",  # bare unittest command (anchored, see pytest)
    rf"\b{_PY}\s+-m\s+unittest\b",  # python -m unittest
    r"^(?:\w+=\S+\s+)*pre-commit\b",  # pre-commit runs arbitrary hook entries (rec 14c)
    r"Invoke-Pester\b",  # PowerShell tests
    r"Measure-Command\b",  # PowerShell timing - RUNS the script block
    r"^(?:\w+=\S+\s+)*(?:pwsh|powershell)\b",  # running PowerShell (anchored, see pytest)
    r"\bpy-spy\b|\bscalene\b|\bpyinstrument\b|\bmemory_profiler\b",  # Python profilers
    rf"\b{_PY}\s+-m\s+cProfile\b",  # Python profiler
    r"\bhyperfine\b",  # CLI benchmark - runs the command repeatedly
    # Inline code / stdin - these RUN code without a file: `python -c "..."`, `python -` (stdin/heredoc).
    rf"\b{_PY}\s+(?:\S+\s+)*-c\b",
    rf"\b{_PY}\s+-\s*$",
    r"\bnode\s+-e\b|\bdeno\s+(?:run|eval)\b|\bbun\s+run\b",  # JS inline / run
    r"\bruby\s+-e\b|\bperl\s+-e\b|\bphp\s+-r\b",  # Ruby/Perl/PHP inline
    r"\bnpm\s+(test|run|start)\b|\bnpx\b|\byarn\s+(test|start)\b|\bpnpm\b",  # JS run/test
    r"\bnode\s+\S+\.[mc]?js\b|\btsx\s+\S|\bts-node\b",  # run JS/TS file
    r"\bgo\s+test\b|\bgo\s+run\b",  # Go
    r"\bdotnet\s+(run|test)\b",  # .NET
    r"\bmvn\b|\bgradle\b|\./gradlew\b",  # JVM build/test (executes)
    r"\bjava\s+(?!-version\b|--version\b|-help\b|--help\b|-h\b)(-jar\b|-cp\b|\S+\b)",  # run Java
    r"\bruby\s+\S+\.rb\b|\bperl\s+\S+\.pl\b|\bRscript\b",  # run Ruby/Perl/R scripts
    # Task runners / build tools that execute project code. `make` is anchored to the segment
    # start: as a bare \b pattern it blocked any text containing the word (e.g. a commit
    # message "docs: make the case" inside a heredoc line becomes its own segment).
    r"\buv\s+run\b|\bpoetry\s+run\b|\bpipenv\s+run\b|\btox\b|\bnox\b|^make\b|\bdocker\s+run\b",
    r"\bcargo\s+(?:run|test|bench)\b|\bswift\s+(?:run|test)\b|\bbundle\s+exec\b",  # rec 12
    r"\bjest\b|\bvitest\b|\bphp\s+\S+\.php\b|\bjulia\s+\S+\.jl\b|\blua\s+\S+\.lua\b",  # rec 12
    r"(^|\s)\./\S+",  # executing a file by path (./foo, ./x.sh)
    r"\bsource\s+\S+|(^|\s)\.\s+\S+\.(?:sh|bash)\b",  # sourcing a script
    # shell -c, or running a script file. The lookbehind stops the trailing "sh" of a FILENAME
    # (run-guard.sh) matching as the shell command when followed by another *.sh argument
    # (`shellcheck run-guard.sh install.sh` was blocked as if it were `sh install.sh`).
    r"(?<![\w.-])(?:bash|sh|zsh|dash|ksh)\s+(?:-c\b|\S+\.(?:sh|bash)\b)",
    rf"\b{_PY}(?:\s+-\S+)*\s+\S*\.py\b",  # run a .py FILE, flags ok: `py -3 f.py` (rec 14a)
]
_EXEC_RE = re.compile("|".join(_EXEC_PATTERNS), re.IGNORECASE)

# Subset of _EXEC_PATTERNS covering "ad hoc inline diagnostic" shapes specifically
# (`python -c "..."`, `python -`, `node -e`, `ruby -e`, `perl -e`, `php -r`) - checked
# separately so _block() can add a MORE TARGETED note for exactly this class. Live report,
# recurring (2026-08-04, 2026-08-07): a session hits a hiccup (a step-0 /engage probe
# failure, or anything else), reaches for "let me just check X directly" as an ad hoc
# inline command, and gets blocked - correctly, but the GENERIC block message gave no hint
# that (a) this specific shape is always blocked regardless of consent, so granting consent
# won't help, and (b) if this followed a probe failure, the fix is retrying the exact probe
# block, not improvising a replacement. `.claude/skills/engage/references/probe-contract.md`
# already said this, but it's a just-in-time reference the model may never open before
# reaching for the ad hoc command in the first place - this note fires AT THE BLOCK ITSELF,
# which the model has already seen by definition.
_INLINE_CODE_RE = re.compile(
    rf"\b{_PY}\s+(?:\S+\s+)*-c\b|\b{_PY}\s+-\s*$|\bnode\s+-e\b|\bruby\s+-e\b|\bperl\s+-e\b|\bphp\s+-r\b",
    re.IGNORECASE,
)

# The team's OWN trusted tooling - allowed even though it runs python. ANCHORED at the start of
# a segment (ADR-002: the old `.search()` matched anywhere, so `echo "scripts."; pytest` waved
# the whole line through). Two forms:
#   * repo-as-project: `python -m scripts.x` / `python scripts/x.py` / `bash scripts/x.sh`
#   * plugin install in a foreign project: the bundled copy invoked by path
#     (`python "$CLAUDE_SKILL_DIR/../../../scripts/render_html.py"`, or a Windows
#     `py "C:\...\scripts\render_html.py"`) - allowed only for the team's own script BASENAMES
#     below, so `python /tmp/scripts/evil.py` stays blocked.
#     (Lexical, like everything here: a hostile file *named* render_html.py in a scripts/ dir
#     would pass - accepted residual, consistent with ADR-002's threat model.)
#     MAINTENANCE RULE: every new scripts/ tool must be added here in the SAME change that
#     creates it, or plugin-mode users get an execution-consent prompt for the team's own
#     tooling - which CLAUDE.md §7 explicitly forbids. Found live on 2026-08-01: engage_probe
#     was missing, so /engage step 0 tripped the gate on its own front door.
_TEAM_SCRIPT_NAMES = (
    r"(?:render_html|render_findings|render_docx|convert_file|ingest|gen_synthetic|synthesise"
    r"|validate_masking|validate_manifest|validate_rtm|validate_references|check_citations|eval_score"
    r"|calibrate_spoofing|check_artifacts|engagement_state|extensions|convert_sarif"
    r"|engage_probe|repo_skeleton|explain_rule)\.py"
)

# 0.32 (ADR-009): the COMPANY tool allowlist - literal command PREFIXES the human curates in
# CST_COMPANY_ALLOW ('|'-separated), set in the launch environment or the settings `env`
# block. Both are HUMAN-only surfaces: the model cannot set env for this hook subprocess,
# and settings edits are blocked by guard-consent-writes (CST_ALLOW_CONFIG_EDIT is likewise
# launch-env-only). Literal prefix match (no regex, no expansion) so a registered wrapper
# like `python scripts/publish_pack.py` runs consent-free while `python evil.py` does not;
# segments are still split first, so a chained command after an allowed prefix is inspected
# on its own. Empty/unset -> no change from stock behaviour.
_COMPANY_ALLOW_PREFIXES = tuple(
    p.strip() for p in os.environ.get("CST_COMPANY_ALLOW", "").split("|") if p.strip()
)


def _company_allowed(segment: str) -> bool:
    return any(segment.startswith(prefix) for prefix in _COMPANY_ALLOW_PREFIXES)


# 0.29.1: two plugin-mode fixes, both observed live (a consent prompt for the team's OWN
# tooling forces exec consent for internal validations - the exact thing §7 says the gate
# must not cover):
#   * `engagement_state.py` joined the basename list (new in 0.29.0, missed here);
#   * quoted paths CONTAINING SPACES now match - plugin installs live under paths like
#     "~/Library/Application Support/..." and the old `[\"']?\S*` could never span a space,
#     blocking even long-allow-listed scripts. The quoted branches require the closing quote
#     immediately after `.py`, so the quoted argument IS the script path - same basename
#     trust as the unquoted form (lexical residual per ADR-002; a quoted path containing a
#     segment separator splits in _segments and fails safe to the exec check).
#
# 2026-08-04: a leading `VAR=value ` env-var prefix (e.g. `PYTHONIOENCODING=utf-8 python
# ".../engage_probe.py"`, needed on Windows cp1252 terminals) broke the anchor - the segment
# no longer STARTS with the python token, so this pattern failed to match while the unanchored
# _EXEC_RE still caught "python ... .py" further into the string, blocking the team's own
# allow-listed script. `_EXEC_PATTERNS` already carries this exact `(?:\w+=\S+\s+)*` prefix for
# pytest/unittest/pre-commit/powershell for the same reason - applied here too, zero or more
# repetitions so chained env vars (`A=1 B=2 python ...`) also pass.
_TEAM_ALLOW = re.compile(
    rf"^(?:\w+=\S+\s+)*(?:{_PY}\s+-m\s+scripts\."
    rf"|{_PY}\s+scripts{_SEP}"
    rf"|{_PY}\s+\"[^\"]*{_SEP}scripts{_SEP}{_TEAM_SCRIPT_NAMES}\""
    rf"|{_PY}\s+'[^']*{_SEP}scripts{_SEP}{_TEAM_SCRIPT_NAMES}'"
    # Unquoted branch REJECTS a leading quote (0.29.1 tightening): the old [\"']?\S* let a
    # half-quoted `"path/scripts/render_html.py evil.py"` match without its closing quote -
    # quoted forms must now fully match the strict quoted branches above.
    rf"|{_PY}\s+(?![\"'])\S*{_SEP}scripts{_SEP}{_TEAM_SCRIPT_NAMES}\b"
    rf"|bash\s+\"[^\"]*{_SEP}scripts{_SEP}check-review-tools\.sh\""
    rf"|bash\s+'[^']*{_SEP}scripts{_SEP}check-review-tools\.sh'"
    rf"|bash\s+(?![\"'])\S*{_SEP}scripts{_SEP}check-review-tools\.sh\b"
    rf"|bash\s+scripts{_SEP}"
    rf"|scripts{_SEP}check-review-tools\.sh)",
    re.IGNORECASE,
)

# Shell separators we split on so an allow-listed segment can't wave through a blocked one chained
# after it. Splitting on `$(`/backtick is deliberately crude - it errs toward inspecting MORE,
# which for a guard means failing safe. (Lexical only; see ADR-002 for the irreducible residual.)
#
# 2026-08-07 (found live by a framework-wide audit, verified by hand before this fix):
# `` ` `` and `$(` are split out from _SEGMENT_DELIMS proper because they need DIFFERENT
# quote-gating than the other four - see _segments()'s in_single-only check below. Kept in
# one combined tuple here anyway (rather than folded entirely into the loop) so a reader
# scanning top-of-file constants still sees every boundary token in one place.
_SEGMENT_DELIMS = (";", "&&", "||", "|", "\n", "`", "$(")

# Of _SEGMENT_DELIMS, only these four are ordinary text inside a double-quoted string in
# real bash (`echo "a; b"` prints "a; b" literally) - so only these stay gated on
# `not in_double` too. `` ` `` and `$(` are handled separately in the loop below.
_ORDINARY_DELIMS = (";", "&&", "||", "|", "\n")


def _segments(cmd: str) -> list[str]:
    """Split a compound command into per-statement segments, quote-aware.

    A purely lexical split (the old approach: regex over the raw string) chops INSIDE a
    quoted argument - a log-note or commit message using ';' or '&&' as ordinary
    punctuation ("...close as-is; no real source data exists...") got sliced into a bogus
    mid-sentence fragment, which then spuriously matched an unrelated block pattern (live,
    2026-08-03: a chained `engagement_state log-note "..."` call). Delimiters are only
    boundaries OUTSIDE '...' / "..." - inside a quote they are just text. Still lexical,
    not a full shell parser (ADR-002's irreducible residual): unclosed quotes just fold
    the remainder into one segment, which is the safe direction (inspecting MORE as one
    unit, never less).

    2026-08-07 fix: that "inside a quote they are just text" rule is TRUE for `;`/`&&`/
    `||`/`|`/newline but FALSE for command substitution - `echo "$(pytest)"` and the
    equivalent backtick form both actually RUN pytest in real bash; only single quotes
    suppress substitution. The 2026-08-03 quote-awareness rewrite above gated backtick/`$(` on the
    same `not in_single and not in_double` condition as the other four, so a command
    wrapped in double quotes silently escaped every anchored `_EXEC_PATTERNS`/`_TEAM_ALLOW`
    check (`^pytest`, `^make`, etc. - segment-start anchors that never saw the real command
    because it never became its own segment). `guard-consent-writes.py`'s own `_segments`-
    equivalent already had this right (its own comment: "command substitution executes even
    inside double quotes - always a boundary") - this brings the other two guards in line
    with it instead of leaving the fix live in only one of the three.
    """
    segments: list[str] = []
    current: list[str] = []
    in_single = in_double = False
    i, n = 0, len(cmd)
    while i < n:
        ch = cmd[i]
        if ch == "\\" and not in_single and i + 1 < n:
            if cmd[i + 1] == "\n":
                # Line continuation: real bash ERASES both chars (one continued logical
                # line), never keeps them as literal text - unlike every other escape.
                i += 2
                continue
            current.append(cmd[i : i + 2])
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
            i += 1
            continue
        if not in_single:
            # Command substitution executes even inside double quotes - always a boundary
            # regardless of in_double, unlike the four ordinary delimiters below.
            if cmd.startswith("`", i):
                segments.append("".join(current))
                current = []
                i += 1
                continue
            if cmd.startswith("$(", i):
                segments.append("".join(current))
                current = []
                i += 2
                continue
            if not in_double:
                hit = next((d for d in _ORDINARY_DELIMS if cmd.startswith(d, i)), None)
                if hit is not None:
                    segments.append("".join(current))
                    current = []
                    i += len(hit)
                    continue
        current.append(ch)
        i += 1
    segments.append("".join(current))
    return [s.strip() for s in segments if s.strip()]


def _block(cmd: str, segment: str | None = None) -> None:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    marker = os.path.join(root, ".claude", ".exec-consent")
    inline_note = ""
    if segment and _INLINE_CODE_RE.search(segment):
        inline_note = (
            "This looks like an ad hoc inline diagnostic (`-c`/stdin code execution) - it is "
            "ALWAYS blocked here, unconditionally, no matter how harmless it looks. This is NOT "
            "a consent question: granting consent will not change this, since inline execution "
            "is blocked regardless of authorisation state. Two live-report shapes this has "
            "recurred as: (1) retrying after a step-0 /engage probe failure by improvising a "
            "replacement instead of re-running the exact probe block character for character "
            "(see PROBE_FAILED in .claude/skills/engage/references/probe-contract.md); (2) "
            "checking a JSON/text file (e.g. verifying a findings pack parses and counting its "
            'entries) by running `python -c "...json.load..."` instead of just reading the '
            "file - it is already text you can Read and count directly, no execution needed "
            "(docs/team-operating-guide.md's findings-count-verification guidance). If you "
            "genuinely need the interpreter's own path or version, use `python --version` or "
            "`python -V` instead - never `-c`.\n"
        )
    sys.stderr.write(
        "Blocked (code-execution gate, CLAUDE.md §7): this command EXECUTES code, and review is "
        "static by default. Running the code under review (its tests, the script itself, or a "
        "profiler/benchmark) needs authorisation.\n"
        f"{inline_note}"
        "To allow execution - ONLY for trusted code in a safe/dev or sandbox environment on "
        "synthetic data - the USER grants consent (the model cannot): run "
        f"`touch {marker}` in any terminal (or `! touch {marker}` as the first characters of "
        "the prompt line), or set CST_ALLOW_EXEC=1 in the launch environment. Otherwise keep "
        "findings static / 🧠 inferred.\n"
        f"Offending segment: {(segment or cmd)[:200]}\n"
    )
    sys.exit(2)


def _team_invoked_this_session(payload) -> bool:
    """Session scoping (2026-08-17, user decision): this gate protects the TEAM'S review
    workflow - never execute the code under review without a human grant - so it arms
    only in sessions that actually invoked the team. A session in an enabled project
    that never ran /engage is plain Claude Code and runs its own tests freely (the live
    complaint: /doctor and ordinary dev work blocked in dormant sessions). The
    acting-session stamp (artifacts/.team-session.json) is written by engage_probe at
    /engage step 0 and by every engagement_state mutation; arming requires a positive
    match, with ONE deliberate inversion versus the advisory lifecycle hooks: a payload
    carrying NO session id (an older Claude Code) cannot be told apart from an engaged
    session, and a SAFETY gate fails toward ARMED. The stamp file itself is
    write-protected in every session by guard-consent-writes (a disarm-by-clobbering
    channel otherwise). The raw-data wall is NOT session-scoped - data protection holds
    in every session by design."""
    sid = payload.get("session_id")
    if not sid:
        return True  # cannot tell - fail toward armed
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        stamp = json.loads(
            open(os.path.join(root, "artifacts", ".team-session.json"), encoding="utf-8").read()
        ).get("session")
    except Exception:
        return False  # no stamp = the team was never invoked here - dormant
    return stamp == sid


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # malformed payload - never brick the session

    if payload.get("tool_name", "") != "Bash":
        sys.exit(0)

    # Dormant session (team never invoked): plain Claude Code, no execution gate.
    if not _team_invoked_this_session(payload):
        sys.exit(0)

    # Execution authorised (human-created consent marker, or human env-var override).
    if _exec_authorised():
        sys.exit(0)

    cmd = (payload.get("tool_input", {}) or {}).get("command", "") or ""
    if not cmd:
        sys.exit(0)

    # Evaluate each segment independently: allow the team's own tooling, block anything that
    # executes code. A blocked segment anywhere in the command blocks the whole command.
    for seg in _segments(cmd):
        if _TEAM_ALLOW.match(seg) or _company_allowed(seg):
            continue
        if _EXEC_RE.search(seg):
            _block(cmd, seg)

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Any unexpected crash would exit 1, which Claude Code treats as a NON-blocking error
        # - the command would PROCEED, silently disarming the gate. Unlike the raw-data guard,
        # this gate has no permissions.deny backstop (there are no Bash() deny entries), so a
        # crash here must fail CLOSED. The deliberate exit-0 for malformed JSON in main() is
        # unaffected (sys.exit raises SystemExit, which is not an Exception).
        sys.stderr.write(
            "guard-code-execution crashed unexpectedly; failing closed (blocked). "
            "See docs/adr/ADR-002-safety-hook-threat-model.md.\n"
        )
        sys.exit(2)
