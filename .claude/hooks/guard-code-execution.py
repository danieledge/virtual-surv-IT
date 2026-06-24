#!/usr/bin/env python3
"""
PreToolUse guard: don't EXECUTE the code under review without human authorisation.

Reviewing code should be **static** (read it + analysers that parse it). Running it — its
tests, the script itself, or a profiler/benchmark — executes potentially untrusted code and is
a real risk (side effects, touching live systems, hostile code). This hook makes "static by
default" a harness-enforced rule, not just a prompt the model might forget (CLAUDE.md §7).

Policy (Bash tool) — ALLOW everything if execution has been authorised, else BLOCK code that
executes. Authorisation is granted by EITHER:
  * the consent marker file `<project>/.claude/.exec-consent` — the team writes this once the
    user answers "yes, you may execute" at intake (the convenient path), or
  * the env var CST_ALLOW_EXEC (truthy), set by the HUMAN in the launch environment / settings
    `env` (the harder override — the model cannot set it for this hook subprocess; also handy
    for CI).
Otherwise -> BLOCK (exit 2) commands that EXECUTE code: test runners, profilers/benchmarks, and
running a script/interpreter on a file. Static analysers, git and read-only utilities are
allowed, as are the team's own `scripts/` helpers.

Note on strength: the marker path is convenient but soft (the model *could* write the marker),
so this is consent-recording + a safety net, not a sandbox. The env-var path is the hard one.

FAIL-OPEN RESIDUAL RISK (Bash): string-matching arbitrary shell is advisory only — obscure
constructs can bypass any lexical check (indirection, subshells, eval). This is a strong
default, not a perfect sandbox. The real assurance is: static-by-default behaviour, the
consent/disclaimer at intake, this gate, and the user keeping genuinely dangerous code out of
the review. See CLAUDE.md §7 and docs/house-rules.md.

Protocol: read the PreToolUse JSON on stdin; exit 2 to block (stderr is fed to the model);
exit 0 to allow. Only the Bash tool is in scope.
"""
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


# Commands/patterns that EXECUTE code. Blocked unless CST_ALLOW_EXEC is set.
# Ordered, commented; each carries why it counts as "execution".
_EXEC_PATTERNS = [
    r"\bpytest\b",                       # Python test runner — runs the code
    r"\bpython3?\s+-m\s+pytest\b",       # same, module form
    r"\bunittest\b",                     # Python unit tests
    r"Invoke-Pester\b",                  # PowerShell tests
    r"Measure-Command\b",                # PowerShell timing — RUNS the script block
    r"\bpwsh\b|\bpowershell\b",          # running PowerShell
    r"\bpy-spy\b|\bscalene\b|\bpyinstrument\b|\bmemory_profiler\b",  # Python profilers
    r"\bpython3?\s+-m\s+cProfile\b",     # Python profiler
    r"\bhyperfine\b",                    # CLI benchmark — runs the command repeatedly
    r"\bnpm\s+(test|run|start)\b|\bnpx\b|\byarn\s+(test|start)\b",   # JS run/test
    r"\bnode\s+\S+\.[mc]?js\b|\bdeno\s+run\b|\bbun\s+run\b",         # run JS file
    r"\bgo\s+test\b|\bgo\s+run\b",       # Go
    r"\bdotnet\s+(run|test)\b",          # .NET
    r"\bmvn\b|\bgradle\b|\./gradlew\b",  # JVM build/test (executes)
    r"\bjava\s+(-jar\b|-cp\b|\S+\b)",    # run Java
    r"\bruby\s+\S+\.rb\b|\bperl\s+\S+\.pl\b",  # run Ruby/Perl scripts
    r"(^|\s|;|&&|\|)\./\S+",             # executing a file by path (./foo, ./x.sh)
    r"\b(bash|sh|zsh)\s+\S+\.(sh|bash)\b",      # running a shell script file
    r"\bpython3?\s+(?!-m\s+scripts\.|-c\b|-m\s+pytest)\S*\.py\b",    # run a .py FILE (not -m scripts., not -c)
]
_EXEC_RE = re.compile("|".join(_EXEC_PATTERNS), re.IGNORECASE)

# Explicit allow-exceptions: the team's OWN trusted tooling (not the code under review).
_TEAM_ALLOW = re.compile(
    r"python3?\s+-m\s+scripts\.|python3?\s+scripts/|bash\s+scripts/|scripts/check-review-tools\.sh",
    re.IGNORECASE,
)


def _block(cmd: str) -> None:
    sys.stderr.write(
        "Blocked (code-execution gate, CLAUDE.md §7): this command EXECUTES code, and review is "
        "static by default. Running the code under review (its tests, the script itself, or a "
        "profiler/benchmark) needs authorisation.\n"
        "To allow execution — ONLY for trusted code in a safe/dev or sandbox environment on "
        "synthetic data — confirm at intake so the team records consent (creates "
        ".claude/.exec-consent), or set CST_ALLOW_EXEC=1 in the launch environment. Otherwise "
        "keep findings static / 🧠 inferred.\n"
        f"Command: {cmd[:200]}\n"
    )
    sys.exit(2)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # malformed payload — never brick the session

    if payload.get("tool_name", "") != "Bash":
        sys.exit(0)

    # Execution authorised (consent marker written on "yes", or human env-var override).
    if _exec_authorised():
        sys.exit(0)

    cmd = (payload.get("tool_input", {}) or {}).get("command", "") or ""
    if not cmd:
        sys.exit(0)

    # Allow the team's own tooling even though it runs python.
    if _TEAM_ALLOW.search(cmd):
        sys.exit(0)

    if _EXEC_RE.search(cmd):
        _block(cmd)

    sys.exit(0)


if __name__ == "__main__":
    main()
