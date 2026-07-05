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
_PY = r"(?:python(?:3(?:\.\d+)?)?|py)"

# Path separator: forward slash OR backslash - Windows commands arrive with backslash paths
# (`python C:\plugin\scripts\render_html.py`) and a slash-only allow-list blocked them (0.4.1).
_SEP = r"[/\\]"

# Commands/patterns that EXECUTE code. Evaluated PER SEGMENT (see _segments). Each carries why
# it counts as "execution". (Hardened per docs/adr/ADR-002 Tier 1; false positives fixed in
# 0.4: `make` anchored to segment start - it blocked commit messages containing the word;
# `sh <file>.sh` given a lookbehind - `shellcheck a.sh b.sh` matched the ".sh " boundary.)
_EXEC_PATTERNS = [
    r"\bpytest\b",  # Python test runner - runs the code
    rf"\b{_PY}\s+-m\s+pytest\b",  # same, module form
    r"\bunittest\b",  # Python unit tests
    r"Invoke-Pester\b",  # PowerShell tests
    r"Measure-Command\b",  # PowerShell timing - RUNS the script block
    r"\bpwsh\b|\bpowershell\b",  # running PowerShell
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
    r"(^|\s)\./\S+",  # executing a file by path (./foo, ./x.sh)
    r"\bsource\s+\S+|(^|\s)\.\s+\S+\.(?:sh|bash)\b",  # sourcing a script
    # shell -c, or running a script file. The lookbehind stops the trailing "sh" of a FILENAME
    # (run-guard.sh) matching as the shell command when followed by another *.sh argument
    # (`shellcheck run-guard.sh install.sh` was blocked as if it were `sh install.sh`).
    r"(?<![\w.-])(?:bash|sh|zsh|dash|ksh)\s+(?:-c\b|\S+\.(?:sh|bash)\b)",
    rf"\b{_PY}\s+\S*\.py\b",  # run a .py FILE (team's scripts/ are allow-listed separately)
]
_EXEC_RE = re.compile("|".join(_EXEC_PATTERNS), re.IGNORECASE)

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
_TEAM_SCRIPT_NAMES = (
    r"(?:render_html|convert_file|ingest|gen_synthetic|synthesise|validate_masking|validate_manifest"
    r"|check_citations|eval_score|calibrate_spoofing|check_artifacts)\.py"
)
_TEAM_ALLOW = re.compile(
    rf"^(?:{_PY}\s+-m\s+scripts\."
    rf"|{_PY}\s+scripts{_SEP}"
    rf"|{_PY}\s+[\"']?\S*{_SEP}scripts{_SEP}{_TEAM_SCRIPT_NAMES}\b"
    rf"|bash\s+[\"']?\S*{_SEP}scripts{_SEP}check-review-tools\.sh\b"
    rf"|bash\s+scripts{_SEP}"
    rf"|scripts{_SEP}check-review-tools\.sh)",
    re.IGNORECASE,
)

# Shell separators we split on so an allow-listed segment can't wave through a blocked one chained
# after it. Splitting on `$(`/backtick is deliberately crude - it errs toward inspecting MORE,
# which for a guard means failing safe. (Lexical only; see ADR-002 for the irreducible residual.)
_SEGMENT_SPLIT = re.compile(r";|&&|\|\||\||\n|`|\$\(")


def _segments(cmd: str) -> list[str]:
    return [s.strip() for s in _SEGMENT_SPLIT.split(cmd) if s.strip()]


def _block(cmd: str, segment: str | None = None) -> None:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    marker = os.path.join(root, ".claude", ".exec-consent")
    sys.stderr.write(
        "Blocked (code-execution gate, CLAUDE.md §7): this command EXECUTES code, and review is "
        "static by default. Running the code under review (its tests, the script itself, or a "
        "profiler/benchmark) needs authorisation.\n"
        "To allow execution - ONLY for trusted code in a safe/dev or sandbox environment on "
        "synthetic data - the USER grants consent (the model cannot): run "
        f"`touch {marker}` in any terminal (or `! touch {marker}` as the first characters of "
        "the prompt line), or set CST_ALLOW_EXEC=1 in the launch environment. Otherwise keep "
        "findings static / 🧠 inferred.\n"
        f"Offending segment: {(segment or cmd)[:200]}\n"
    )
    sys.exit(2)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # malformed payload - never brick the session

    if payload.get("tool_name", "") != "Bash":
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
        if _TEAM_ALLOW.match(seg):
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
