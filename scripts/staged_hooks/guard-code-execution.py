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


def _declared_in_settings_env(name: str) -> bool:
    """Is *name* set through a settings.json `env` block rather than the launch environment?

    WHY (2026-09-12 audit, H-1). Both this guard and guard-consent-writes.py assert in their
    own docstrings that CST_ALLOW_EXEC / CST_ALLOW_CONFIG_EDIT are human-only "because the
    model cannot set it for this hook subprocess". That is true of the launch environment and
    false of `.claude/settings.json`, whose `env` block Claude Code exports into hook
    subprocesses - and which a dormant session may edit. So the variable is authoritative
    only when the project's settings do NOT declare it: a value that arrived through a
    model-writable file is exactly the channel the "human-only" claim excludes.

    Reads both settings files because either one can carry `env`. Any read/parse failure
    means "not declared", which keeps the launch-environment override working on a project
    with no settings at all - the common case, and the safe direction here (this function
    only ever REMOVES an authorisation, never grants one).
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


def _exec_authorised() -> bool:
    """Execution is permitted if the human set CST_ALLOW_EXEC, or the consent marker exists."""
    if _truthy(os.environ.get("CST_ALLOW_EXEC")):
        if _declared_in_settings_env("CST_ALLOW_EXEC"):
            sys.stderr.write(
                "Ignoring CST_ALLOW_EXEC: it is declared in this project's .claude/settings.json "
                "`env` block, which is a file the model can write - so it is not the human-only "
                "launch-environment grant this gate accepts. Set it in the launch environment, "
                "or have the USER create .claude/.exec-consent.\n"
            )
        else:
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

# The acting-session stamp's filename. Named once so the two layout paths below cannot
# disagree with each other.
_STAMP_NAME = ".team-session.json"

# The interpreter as the TEAM_ALLOW list sees it: a bare name, OR a full path to one, with
# or without .exe, quoted or not (2026-08-26 live report, corp Windows). Plugin mode on a
# box with an unreliable PATH resolves `<python>` to an absolute interpreter - the real
# command was `"C:/Python313/python.exe" "C:/Users/.../virtual-surv-IT/scripts/
# engagement_state.py" init ...` - and bare-name-only matching meant _TEAM_ALLOW did not
# recognise the team's OWN front-door script. CLAUDE.md §7 is explicit that the gate covers
# the code under review and never the team's tooling, so this was the gate breaking its own
# contract, and on the one platform least able to work around it.
#
# The security property is UNCHANGED because it never lived in the interpreter token: trust
# comes from the SCRIPT side - a basename on _TEAM_SCRIPT_NAMES, directly inside a
# `scripts/` directory. `<any python> <allow-listed team script>` is exactly as trusted as
# `python <allow-listed team script>`; `<any python> /tmp/evil.py` stays blocked, and the
# pinning tests below assert precisely that.
#
# Deliberately NOT used in _EXEC_PATTERNS - see the note there.
_PY_ANY = (
    rf"(?:\"[^\"]*{_SEP}(?:python(?:3(?:\.\d+)?)?|py)(?:\.exe)?\""
    rf"|'[^']*{_SEP}(?:python(?:3(?:\.\d+)?)?|py)(?:\.exe)?'"
    rf"|(?![\"'])\S*{_SEP}(?:python(?:3(?:\.\d+)?)?|py)(?:\.exe)?"
    rf"|{_PY}(?:\.exe)?)"
)


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
    # STDIN-FED EXECUTION (2026-09-12 audit, H-10). The interpreter patterns above only ever
    # recognised `-c`, a trailing bare `-`, and a `.py` filename, so every form that feeds the
    # code in through stdin ran unblocked: `python3 <<'EOF' ... EOF`, `python3 < evil.py`, and
    # `cat evil.py | python3`. All three execute exactly the code under review, which is the
    # one thing this gate exists to stop.
    rf"\b{_PY}\s+(?:\S+\s+)*<<-?",  # heredoc into an interpreter
    r"(?<![\w.-])(?:bash|sh|zsh|dash|ksh)\s+(?:\S+\s+)*<<-?",  # heredoc into a shell
    rf"\b{_PY}\s+(?:-\S+\s+)*<\s*\S",  # python < file
    r"(?<![\w.-])(?:bash|sh|zsh|dash|ksh)\s+(?:-\S+\s+)*<\s*\S",  # sh < file
    # A pipe is a SEGMENT boundary, so `cat evil.py | python3` reaches this check as the bare
    # segment `python3` - an interpreter with no script and no flags reads its program from
    # stdin. `python --version` / `python -V` keep working: they carry a flag, and this
    # alternative requires the segment to be the bare token.
    rf"^{_PY}\s*$",
    r"^(?:bash|sh|zsh|dash|ksh|node|ruby|perl)\s*$",
]
_EXEC_RE = re.compile("|".join(_EXEC_PATTERNS), re.IGNORECASE)

# Wrapper commands that change nothing about WHAT runs, only how (2026-09-12 audit, H-10).
# Five of the patterns above are anchored with `^(?:\w+=\S+\s+)*` - which permits a VAR=value
# prefix and nothing else - so `sudo pytest`, `nice -n 10 pytest`, `timeout 60 pytest`,
# `env pytest`, `command pytest` and `nohup pytest &` all ran unblocked. Stripping the wrapper
# chain before re-testing restores the anchor's intent without unanchoring the patterns, which
# is what made `make` and `pytest` match prose in the first place (ADR-002's recurring
# false-positive class). `xargs` and `stdbuf` are deliberately NOT here: xargs rewrites the
# argument list rather than just prefixing it, so stripping it would judge a command that is
# not the one that runs.
_WRAPPER_PREFIX_RE = re.compile(
    r"^(?:"
    r"sudo(?:\s+-\S+)*"
    r"|env"
    r"|command"
    r"|exec"
    r"|nohup"
    r"|nice(?:\s+-n\s+\S+)?"
    r"|timeout(?:\s+-\S+)*\s+\S+"
    r"|\w+=\S+"
    r")\s+",
    re.IGNORECASE,
)


def _strip_wrappers(segment: str) -> str:
    """Peel leading wrapper tokens so the anchored _EXEC_PATTERNS see the real command.

    Bounded iteration: a pathological `sudo sudo sudo ...` line must not spin here."""
    out = segment
    for _ in range(8):
        stripped = _WRAPPER_PREFIX_RE.sub("", out, count=1)
        if stripped == out:
            break
        out = stripped
    return out


def _executes(segment: str) -> bool:
    """Does this segment execute code, as written OR once its wrappers are peeled off?"""
    return bool(_EXEC_RE.search(segment) or _EXEC_RE.search(_strip_wrappers(segment)))


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
    r"|engage_probe|repo_skeleton|explain_rule|render_evidence_room"
    # 2026-08-25: launch_terminal, which opens a session in its own window. Without it a
    # plugin-mode user gets a consent prompt for the team's OWN tooling - the exact live
    # defect found on 2026-08-01 when engage_probe was missing from this list.
    # workflow_trace and render_workflow were added the same day and removed the same day
    # with the transcript reader; names for scripts that no longer exist are dead config,
    # and dead config in a SECURITY allow-list is worse than dead config anywhere else.
    # 2026-08-30: tier_probe, the read-only "why is the new interface not drawing?"
    # diagnostic. It imports and prints; it executes nothing under review. Without the
    # entry a plugin-mode user is asked for execution consent to run a tool whose whole
    # job is answering a support question about the plugin itself.
    # 2026-08-31: audit_screens, the read-only "is every menu option wired?" report. It
    # parses install_helper with ast and imports the two tier modules to compare their
    # signatures; it executes nothing under review and writes nothing. Same reasoning as
    # tier_probe - without the entry, a plugin-mode user is asked for execution consent to
    # run a tool whose whole job is answering a question about the plugin itself.
    r"|launch_terminal|tier_probe|audit_screens)\.py"
)

# NEVER consent-free, checked BEFORE the allow-list (2026-09-12 audit, H-2 and H-4).
#
# H-2: `scripts/staged_hooks/*` is deliberately left writable so the model can stage guard
# fixes; the apply-*.sh scripts are what copy a staged file over the LIVE guard, and promotion
# is a HUMAN act (ADR-002 rec 5). `bash scripts/apply-all-staged.sh` was matched by _TEAM_ALLOW's
# `bash scripts/` branch and resolved inside the plugin's own scripts dir, so the whole chain
# - edit the staged guard, run the apply script, every guard replaced - ran with no consent
# prompt and no human in the loop. The only control was a prose note in user memory. This makes
# it mechanical.
_APPLY_SCRIPT_RE = re.compile(r"(?:^|[\s/\\])apply-[A-Za-z0-9._-]*\.sh(?![\w.-])", re.IGNORECASE)

# H-4: scripts the plugin ships that must never run consent-free from a model turn, even
# though they sit in the plugin's own scripts directory. `guard_daemon` binds the socket the
# other guards route their decisions through; `headless_run`, `launch_terminal`,
# `virt_team_launcher`, `launcher_app`, `launcher_textual` and `launcher_tiers` spawn further
# Claude sessions or terminals; `installer_app` rewrites harness config; `eval_engage` drives
# whole engagements; `release_gate` runs the release pipeline. None is a front-door script a
# skill invokes on the user's behalf mid-turn, so none needs the consent-free allowance, and
# every one of them is a way to reach further execution without ever naming it.
_MODULE_DENY = frozenset(
    {
        "guard_daemon",
        "guard_daemon_client",
        "headless_run",
        "launch_terminal",
        "installer_app",
        "eval_engage",
        "virt_team_launcher",
        "launcher_app",
        "launcher_textual",
        "launcher_tiers",
        "release_gate",
    }
)
_MODULE_FORM_RE = re.compile(r"-m\s+scripts\.([A-Za-z_][A-Za-z0-9_]*)")
_SCRIPT_PATH_RE = re.compile(rf"scripts{_SEP}([A-Za-z_][A-Za-z0-9_]*)\.py(?![\w.-])")

# A path the shell has not expanded yet: `$VAR`, `${VAR}` (POSIX) or `%VAR%` (CMD). These are
# the only forms _resolves_into_plugin_scripts cannot resolve, and therefore the only ones the
# basename whitelist still covers - see its docstring.
_UNEXPANDED_VAR_RE = re.compile(r"\$\{?\w|%[A-Za-z_][A-Za-z0-9_]*%")


def _denied_outright(seg: str) -> str | None:
    """The reason this segment is refused before the allow-list even runs, or None.

    Only ever fires on a segment that would otherwise RUN the named file - either because
    the allow-list would have waved it through, or because it matches an execution shape.
    Without that condition this denied reading and static analysis too (`ruff check
    scripts/guard_daemon.py`, `cat scripts/apply-all-staged.sh`), which is the prose/argument
    false-positive class ADR-002 has already fixed four times in this family.
    """
    if not (_TEAM_ALLOW.match(seg) or _executes(seg)):
        return None
    if _APPLY_SCRIPT_RE.search(seg):
        return (
            "an apply-*.sh script, which installs a model-edited staged hook over a LIVE "
            "guard. Promoting a staged guard is a HUMAN act (ADR-002 rec 5) - ask the user "
            "to run it"
        )
    # Both spellings of the same script: `-m scripts.guard_daemon` and `scripts/guard_daemon.py`.
    for match in (_MODULE_FORM_RE.search(seg), _SCRIPT_PATH_RE.search(seg)):
        if match and match.group(1) in _MODULE_DENY:
            return (
                f"scripts.{match.group(1)}, which is shipped tooling but not a front-door "
                "script: it spawns sessions, rewrites harness config, or serves the guards "
                "themselves, so it is never consent-free from a model turn"
            )
    return None


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
    rf"^(?:\w+=\S+\s+)*(?:{_PY_ANY}\s+-m\s+scripts\."
    rf"|{_PY_ANY}\s+scripts{_SEP}"
    rf"|{_PY_ANY}\s+\"[^\"]*{_SEP}scripts{_SEP}{_TEAM_SCRIPT_NAMES}\""
    rf"|{_PY_ANY}\s+'[^']*{_SEP}scripts{_SEP}{_TEAM_SCRIPT_NAMES}'"
    # Unquoted branch REJECTS a leading quote (0.29.1 tightening): the old [\"']?\S* let a
    # half-quoted `"path/scripts/render_html.py evil.py"` match without its closing quote -
    # quoted forms must now fully match the strict quoted branches above.
    rf"|{_PY_ANY}\s+(?![\"'])\S*{_SEP}scripts{_SEP}{_TEAM_SCRIPT_NAMES}\b"
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


def _block_denied(reason: str, segment: str) -> None:
    """Refusal for the never-consent-free set - deliberately NOT the consent message.

    Telling the model "the USER can grant consent" would be wrong here: consent does not
    open these, and the earlier version of this gate taught (correctly, for inline `-c`) that
    a block message which implies a consent question sends the session to ask for one."""
    sys.stderr.write(
        f"Blocked (code-execution gate, CLAUDE.md §7): this command runs {reason}.\n"
        "This is NOT a consent question - the execution-consent marker does not open it, and "
        "asking the user to create one will not help.\n"
        f"Offending segment: {segment[:200]}\n"
    )
    sys.exit(2)


def _stamp_candidates(root):
    """Every place the acting-session stamp may live, newest layout first.

    Kept as a literal pair rather than resolved through vsit_paths, for the reason given at
    the call site: a hook must stay importable-independent of the scripts package.
    """
    return (
        os.path.join(root, "VSIT", "engagements", _STAMP_NAME),
        os.path.join(root, "artifacts", _STAMP_NAME),
    )


# How many stamped sessions a single stamp file may arm (2026-09-12 audit, H-13). The stamp
# used to hold ONE session id, so a second /engage in the same project silently disarmed the
# first session mid-engagement, and a resume after compaction disarmed itself. It now carries a
# list; the cap keeps an abandoned session from arming the gate forever, and keeps the file's
# size bounded. Newest entries win - the writer appends, so the tail is the live set.
_MAX_STAMPED_SESSIONS = 8


def _stamped_session_ids(stamp_path) -> tuple:
    """Every session id this stamp file arms, across both formats.

    Legacy: {"session": "<id>"} - one session, still honoured so a stamp written before the
    format change keeps working. Current: {"session_id": "<latest>", "sessions": [{"id": ...,
    "stamped_at": ...}, ...]}. Anything unreadable or unparseable yields no ids, which is the
    dormant direction for this reader (the ARMED-on-no-session-id decision is made by the
    caller, not here)."""
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
    # BOTH LAYOUTS since 2026-09-11. This read the legacy path literally while the writers
    # place the stamp through vsit_paths.engagements_dir(), which has resolved to
    # VSIT/engagements/ for any project with neither layout present since PREFER_NEW_LAYOUT
    # became true on 2026-08-28. So in every project created since then the stamp was never
    # found, this returned False, and the gate was OFF: an engaged session could run the
    # code under review with no consent. The plugin's own repo is on the legacy layout,
    # which is why it went unnoticed, and no test here carried a new-layout path.
    #
    # A literal pair, not an import of vsit_paths: a hook must not depend on the scripts
    # package being importable. Checking both costs one stat on a file that usually is not
    # there.
    for stamp_path in _stamp_candidates(root):
        if sid in _stamped_session_ids(stamp_path):
            return True
    return False  # no stamp anywhere = the team was never invoked here - dormant


def _resolves_into_plugin_scripts(seg: str) -> bool:
    """Does this segment name a script inside the PLUGIN'S OWN scripts directory?

    WHY (2026-09-11 review). Three _TEAM_ALLOW branches carried no name check at all:

        python -m scripts.<anything>
        python scripts/<anything>
        bash scripts/<anything>

    _TEAM_SCRIPT_NAMES applied only to the quoted and absolute forms. So in plugin mode,
    reviewing a client repo with its own scripts directory - which is very common -
    `python scripts/deploy.py` and `bash scripts/run_all.sh` ran with no consent prompt.
    Executing the code under review is the one thing this gate exists to stop.

    The name list cannot fix it alone: it holds 24 names while the plugin ships 64 scripts,
    so tightening those branches against it would break /dashboard and /run-evals, and
    extending it to all 64 creates a hand-maintained list that goes stale, which is already
    a standing problem here.

    Location is the better discriminator and it is available. This file sits two levels
    below the plugin root, so the plugin's own scripts directory is computable. A relative
    `scripts/x.py` resolves against the invocation's cwd, which in plugin mode is the CLIENT
    project, so it lands outside the plugin and is refused; the same command inside the
    plugin's own repo resolves inside and is allowed.

    Residual, stated rather than hidden: a lexical guard cannot resolve `-m` lookups through
    sys.path, so the module form falls back to "does the plugin actually ship that script".
    This narrows a wide hole, it does not close it. ADR-002 covers the general residual.

    2026-09-12 audit (H-3), the ordering inverted. The basename whitelist was checked FIRST
    and `continue`d on a hit, so LOCATION was never enforced for any whitelisted name. The
    model holds an unrestricted Write tool: `Write /tmp/scripts/ingest.py` followed by
    `python /tmp/scripts/ingest.py` was arbitrary, consent-free code execution. The
    docstring conceded "a hostile file named render_html.py in a scripts/ dir would pass" as
    an external-attacker residual, but the model is the party this gate constrains and it can
    create the file itself.

    The whitelist still exists for the one case it was added for and the only case that
    genuinely cannot be resolved: a path carrying an UNEXPANDED shell/CMD variable
    (`"$CLAUDE_SKILL_DIR/../../../scripts/render_html.py"`,
    `"%CLAUDE_PLUGIN_ROOT%\\scripts\\render_html.py"`). A path with nothing to expand IS
    resolvable, so it is resolved, and it must land inside the plugin's own scripts
    directory whatever it is called.
    """
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        plugin_scripts = os.path.realpath(os.path.join(here, "..", "..", "scripts"))
    except Exception:  # noqa: BLE001
        return False  # cannot locate ourselves: do not hand out the allowance

    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    saw_path = False
    # The opening delimiter accepts a quote as well as whitespace (2026-09-12, H-3): a QUOTED
    # path never matched this pattern at all, so `python3 "/tmp/scripts/render_html.py"` -
    # which _TEAM_ALLOW's quoted branch accepts on its basename - reached this function, found
    # no path to judge, and was allowed. The quoted form is the bundled-plugin form; it has to
    # be judged by the same rule as the unquoted one.
    for match in re.finditer(r"(?:^|[\s\"'])([^\s\"']*scripts[/\\][^\s\"']+)", seg):
        saw_path = True
        referenced = match.group(1)
        # Split on BOTH separators, never os.path.basename: this guard runs on Linux too,
        # where basename does not treat a backslash as a separator, so a Windows command
        # (`py C:\plugin\scripts\check_artifacts.py`) came back whole and matched nothing.
        # The rest of this file is careful about `[/\\]` everywhere for the same reason.
        leaf = re.split(r"[/\\]", referenced)[-1]
        if _UNEXPANDED_VAR_RE.search(referenced):
            # Nothing can resolve this - not this guard, not a reader. The basename is the
            # only discriminator there is, so it is the one that applies, exactly as before.
            if re.fullmatch(_TEAM_SCRIPT_NAMES, leaf):
                continue
            return False
        # Fully literal: resolvable, therefore resolved. A relative `scripts/x.py` resolves
        # against the invocation's project, which in plugin mode is the CLIENT repo, so it
        # lands outside the plugin and is refused; the same command inside the plugin's own
        # repo resolves inside and is allowed.
        try:
            resolved = os.path.realpath(os.path.join(root, referenced))
        except Exception:  # noqa: BLE001
            return False
        if os.path.dirname(resolved) != plugin_scripts:
            return False
    if saw_path:
        return True

    # `-m scripts.<name>` carries no path to resolve, so judge it by whether the plugin
    # actually ships that script. The deny set (_MODULE_DENY) is applied earlier, in
    # _denied_outright, so it cannot be reached through this allowance either.
    module = _MODULE_FORM_RE.search(seg)
    if module:
        return os.path.isfile(os.path.join(plugin_scripts, module.group(1) + ".py"))
    return True


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

    cmd = (payload.get("tool_input", {}) or {}).get("command", "") or ""
    if not cmd:
        sys.exit(0)

    # The never-consent-free set is checked BEFORE the authorisation shortcut, deliberately.
    # Execution consent authorises running the code UNDER REVIEW in a sandbox; it was never a
    # grant to replace the guards or to spawn further sessions, and an execution-authorised
    # engaged session must not also be able to rewrite the gate that authorised it.
    for seg in _segments(cmd):
        reason = _denied_outright(seg)
        if reason:
            _block_denied(reason, seg)

    # Execution authorised (human-created consent marker, or human env-var override).
    if _exec_authorised():
        sys.exit(0)

    # Evaluate each segment independently: allow the team's own tooling, block anything that
    # executes code. A blocked segment anywhere in the command blocks the whole command.
    for seg in _segments(cmd):
        if (_TEAM_ALLOW.match(seg) and _resolves_into_plugin_scripts(seg)) or _company_allowed(seg):
            continue
        if _executes(seg):
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
