#!/usr/bin/env python3
"""
PreToolUse guard: keep agents structurally downstream of masking.

Blocks tool calls that target raw, un-masked data (anything that resolves under a
`data/raw/` directory).  Agents must consume masked output (data/masked/, via
scripts/ingest.py) or synthetic data - never raw records, which would egress to the
model provider as prompt context (CLAUDE.md §5).

Protocol: read the PreToolUse JSON on stdin; exit 2 to block (stderr is fed back to
the model); exit 0 to allow.  The script errs on the side of blocking on ambiguous
input (fail-closed for path resolution errors).

STAGED CHANGES (audit 2026-08-01) - three coverage gaps closed, one false positive fixed:

  1. NON-ENUMERATED READ TOOLS (was ADR-002 rec 22, rated "architectural, not live").
     _extract_path_candidates returned [] for any tool outside {Read,Grep,Glob,Bash}, so a
     read tool outside that set reached data/raw with NOTHING checking it. The rec assumed no
     local-filesystem tool was installed; that assurance was weaker than stated, because
     WebFetch resolves `file://` URLs against the local filesystem and IS a live tool. Now:
     WebFetch and NotebookRead are handled explicitly, and any UNKNOWN tool gets a
     defence-in-depth substring scan of its string inputs rather than a free pass.

  2. ANCESTOR-ROOTED AND PATH-LESS Grep/Glob (was ADR-002 recs 7 and 15).
     `Grep(path="data")`, or a path-less Grep (which searches cwd), descends INTO data/raw
     while naming a path that does not resolve under it - so both the path check and the
     literal deny globs missed it. Now an ancestor-rooted search blocks, but ONLY when raw
     data actually exists on disk: with no raw data present (the overwhelmingly common case,
     and always true in a fresh clone) an ancestor-rooted grep egresses nothing, so blocking
     it would be pure false positive. The guard protects data, not directory names.

  3. READ-ONLY INSPECTION OF A FILE THAT MERELY MENTIONS THE MARKER (live false positive,
     observed 2026-08-01 during the audit: `grep -n "data/raw" .claude/settings.json`, a
     read of the DENY-LIST CONFIG, was blocked because the search PATTERN contained the
     marker string). This is the fourth instance of the prose-or-argument false-positive
     class ADR-002 has already fixed three times (`make` in prose, `shellcheck a.sh b.sh`,
     the multi-`.py` launcher). Now, for search verbs only, the PATTERN operand is
     distinguished from the FILE operands and exempted; a file operand under data/raw still
     blocks.

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

import hashlib
import json
import os
import re
import shlex
import sys
import time
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
RAW_MARKERS = ("data/raw/", "data\\raw\\")

# Word-bounded, case-insensitive marker: also catches `data/raw` WITHOUT a trailing slash
# (`cd data/raw && cat *`, `cp -r data/raw ...`) and case-folded variants (`DATA/RAW`), which
# the fixed-string RAW_MARKERS miss (ADR-002 rec 12). The lookbehind keeps it off unrelated
# paths like `metadata/rawlog` (preceded by a word char).
_RAW_MARKER_RE = re.compile(r"(?<![\w.-])data[/\\]raw(?![\w])", re.IGNORECASE)

# Search tools take a PATTERN operand that is not a path. A marker inside the pattern is a
# read ABOUT raw data, not a read OF it (fix 3 above).
_SEARCH_VERBS = ("grep", "egrep", "fgrep", "rg", "ag", "ack", "ripgrep")

# Tools that are DELIBERATELY out of scope, and must stay out of scope when the unknown-tool
# fallback below is applied. This guard exists to stop raw records reaching the MODEL's context
# (egress to the provider); writing to data/raw egresses nothing, and is covered separately by
# the `data/raw` write-protect in .claude/settings.json and by guard-consent-writes.py. Without
# this set the unknown-tool fallback would sweep up the write tools and change a documented,
# tested behaviour (tests/test_guards.py::test_raw_guard_ignores_out_of_scope_tool) as a side
# effect of closing a READ gap.
#
# 2026-09-12 audit (H-23): the justification above was checked against the deny list and did
# not hold. `.claude/settings.json` carries three `Edit(...)` entries for data/raw and NO
# `Write(...)` entry at all, so `Write(file_path="data/raw/x.csv")` was permitted by both the
# deny list and this guard. Write also has a second-order effect this comment missed: content
# the model creates under data/raw makes `_raw_data_present()` true, which then blocks
# legitimate ancestor-rooted searches for the rest of the session. The set is now empty -
# every tool is judged - and the deny-list entries stay as the OS-level backstop.
_OUT_OF_SCOPE_TOOLS = ()

# Search-tool flags that consume the FOLLOWING token as a value, so that token is neither the
# pattern nor a file operand. Conservative list - an unknown flag is treated as valueless,
# which at worst leaves an extra token in the file list (fail-closed direction).
_FLAGS_WITH_VALUE = {
    "-e",
    "-f",
    "-m",
    "-A",
    "-B",
    "-C",
    "-D",
    "-d",
    "--regexp",
    "--file",
    "--max-count",
    "--include",
    "--exclude",
    "--exclude-dir",
    "--after-context",
    "--before-context",
    "--context",
    "--devices",
    "--directories",
    "--color",
    "--colour",
    "-g",
    "--glob",
    "--type",
    "-t",
    "--type-not",
    "-T",
    "--max-depth",
}

# Of those, the flags whose value is a PATH the tool actually opens or SELECTS, not a pattern
# (2026-09-12 audit, H-17). Treated as file operands rather than discarded.
#
# `--exclude`/`--exclude-dir` are deliberately NOT here, and neither is a `!`-prefixed rg
# glob: their value names what the search must NOT touch, so reading one as a file operand
# would block the very command that keeps the search away from raw data - the same
# over-blocking H-21 catalogued for `find . -not -path './data/raw/*'`. A negated filter is
# handled in the loop below.
_FLAGS_WITH_PATH_VALUE = {
    "-f",
    "--file",
    "--include",
    "-g",
    "--glob",
}

# Compound-command segment splitter, mirroring guard-code-execution.py's _segments(): a
# multi-statement Bash command (`grep ...; echo "..."`, `a && b`, `a | b`) was previously
# shlex-split and judged as ONE invocation, so words from a LATER, unrelated statement
# became "file operands" of an EARLIER search verb - a live false positive during the
# 2026-08-03 token-usage audit itself (the audit's own multi-statement command got
# blocked). Each segment is now judged independently.
#
# 2026-08-07: kept as one combined tuple for readability even though `` ` ``/`$(` now get
# different quote-gating than the other four below - see _ORDINARY_DELIMS and _segments().
_SEGMENT_DELIMS = (";", "&&", "||", "|", "\n", "`", "$(")

# Of _SEGMENT_DELIMS, only these four are ordinary text inside a double-quoted string in
# real bash (`echo "a; b"` prints "a; b" literally) - `` ` ``/`$(` are handled separately
# in _segments() because command substitution EXECUTES even inside double quotes.
_ORDINARY_DELIMS = (";", "&&", "||", "|", "\n")

# `git commit`/`git tag -m <text>` (or --message=<text>): the message is prose the user
# wrote, not a file read, so it must not trip the marker scan just for MENTIONING the
# guard's own marker string (e.g. describing this very fix in a commit message) - the
# fourth instance of the prose/argument false-positive class this project keeps hitting.
# `-F <file>` (a message FILE) is deliberately NOT exempted here - that IS a real read.
_GIT_MESSAGE_VERBS = ("commit", "tag")

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
# normcase for the same reason _resolve applies it - both sides of every comparison have to
# be spelled the same way or the Windows case-insensitivity gap (H-7) reopens here instead.
_RAW_DIR = Path(os.path.normcase(str((Path(_project_root) / "data" / "raw").resolve())))
# RENAMED 2026-09-12 (audit H-15). It was `.claude/.raw-data-present`, which
# guard-consent-writes' `_HOOK_PATH_RE` does not match - it covers `.claude/.guard-*`. So the
# one file that decides whether an ancestor-rooted search is allowed to walk into the raw
# directory was freely writable. The `.guard-` prefix puts it inside the existing
# write-protection; the fingerprint validation below is the other half, and neither is
# sufficient alone. An old-named file left behind is simply ignored.
_RAW_PRESENT_CACHE = Path(_project_root) / ".claude" / ".guard-raw-present"
_RAW_PRESENT_CACHE_TTL_SECONDS = 30  # short enough to catch a mid-session data/raw
# addition quickly; long enough to collapse a burst of Grep/Glob calls into one real walk.


def _raw_data_present() -> bool:
    """True if the protected directory actually holds at least one file.

    Gates the ancestor-rooted search check ONLY (fix 2). An ancestor-rooted grep can only
    egress raw records if there are raw records to egress; with an absent or empty data/raw
    - a fresh clone, a synthetic-only project - blocking every repo-root search would be a
    pure false positive and would make the guard hated rather than respected. The precise
    path checks below are unconditional and do not consult this.

    Cached (2026-08-10, corp report): a path-less Grep/Glob call always roots at the
    project dir, which is trivially an ancestor of data/raw, so this ran a full os.walk()
    on nearly every real search - measurable overhead on a corporate Windows box with
    endpoint security scanning each filesystem op. A short-TTL file cache (same pattern as
    .claude/.guard-interpreter) collapses a burst of calls into one real walk. The cache is
    never load-bearing: any read/write failure falls straight through to a real check, and
    the fail-closed exception handler below is unchanged.

    VALIDATED (2026-09-12 audit, H-15). The cache was a bare "true"/"false" string that
    nothing checked, and the file was not write-protected: `Write(".claude/.raw-data-present",
    "false")` bought a 30-second window in which a path-less Grep or Glob walked into the raw
    directory and returned its contents, repeatable indefinitely. The cached answer now has to
    come with a FINGERPRINT of the directory it is an answer about - its own mtime and the
    sorted names directly inside it - and a mismatch, a malformed file or an expired TTL all
    fall through to the real walk. The model cannot be stopped from deleting the file, so
    deletion is equivalent to "no cached answer", which costs a walk and never grants one.

    The fingerprint is one listdir, not a walk, so the cache still does its job: collapsing a
    burst of Grep/Glob calls into one traversal on a box where every filesystem op is scanned.
    """
    try:
        if not _RAW_DIR.is_dir():
            return False
        fingerprint = _raw_dir_fingerprint()
        try:
            cached = json.loads(_RAW_PRESENT_CACHE.read_text(encoding="utf-8"))
            age = time.time() - _RAW_PRESENT_CACHE.stat().st_mtime
            if (
                isinstance(cached, dict)
                and age < _RAW_PRESENT_CACHE_TTL_SECONDS
                and cached.get("fingerprint") == fingerprint
                and isinstance(cached.get("present"), bool)
            ):
                return cached["present"]
        except (OSError, ValueError, TypeError):
            pass  # no valid cache - fall through to a real check
        result = False
        for _root, _dirs, files in os.walk(_RAW_DIR):
            if files:
                result = True
                break
        try:
            _RAW_PRESENT_CACHE.parent.mkdir(parents=True, exist_ok=True)
            _RAW_PRESENT_CACHE.write_text(
                json.dumps({"present": result, "fingerprint": fingerprint}), encoding="utf-8"
            )
        except OSError:
            pass  # cache write is an optimization only, never load-bearing
        return result
    except Exception:
        # Cannot tell - assume present so the stricter branch applies (fail closed).
        return True


def _raw_dir_fingerprint() -> str:
    """Cheap identity of the protected directory: its own stat plus its top-level listing.

    One listdir, not a walk - the whole point of the cache is to avoid the walk. Any failure
    yields a value that cannot match a stored fingerprint, so the caller falls through to the
    real check, which is the direction that never grants an unearned answer."""
    try:
        stat = _RAW_DIR.stat()
        names = sorted(os.listdir(_RAW_DIR))
        raw = f"{stat.st_mtime_ns}:{stat.st_size}:" + "|".join(names)
    except OSError:
        return ""
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:32]


def _resolve(candidate: str) -> Path:
    """Canonicalise *candidate*, resolving a RELATIVE path against the project root.

    os.path.realpath() alone resolves against the process working directory. For a hook
    subprocess that is normally the project directory, so the two agree in production - but
    relying on that coincidence made `Grep(path="data")` resolve to the wrong tree whenever
    they differ, which is precisely the ancestor case this guard now has to get right.
    Anchoring explicitly on _project_root removes the coincidence.
    """
    path = Path(candidate)
    if not path.is_absolute():
        path = Path(_project_root) / path
    # normcase on top of realpath (2026-09-12 audit, H-7): realpath collapses `.`/`..` and
    # symlinks but preserves CASE, and on Windows - where the filesystem does not - two
    # spellings of the same directory compared unequal. normcase is a no-op on POSIX, so the
    # Linux behaviour is byte-identical to before.
    return Path(os.path.normcase(os.path.realpath(str(path)))).resolve()


def _is_under_raw(candidate: str) -> bool:
    """
    Return True if *candidate* resolves to a path inside the raw data directory.

    Strategy:
      1. Canonicalise symlinks / relative components against the project root.
      2. Compare with _RAW_DIR using Path.is_relative_to (Python 3.9+).
      3. On any resolution error, fail CLOSED (return True = block).
    """
    if not candidate:
        return False
    try:
        resolved = _resolve(candidate)
        return resolved == _RAW_DIR or resolved.is_relative_to(_RAW_DIR)
    except Exception:
        # Cannot resolve - err on the side of caution: block.
        return True


def _is_ancestor_of_raw(candidate: str) -> bool:
    """True if a search rooted at *candidate* would descend into the raw directory.

    `Grep(path="data")` names a directory that does NOT resolve under data/raw, yet the
    search walks into it. This is the inverse containment test (ADR-002 recs 7 and 15).
    """
    if not candidate:
        return False
    try:
        resolved = _resolve(candidate)
        return _RAW_DIR.is_relative_to(resolved) and resolved != _RAW_DIR
    except Exception:
        # 2026-09-12 audit (H-27): fail CLOSED, matching _is_under_raw four lines above.
        # The two halves of the same containment question had opposite polarities, and only
        # the fail-OPEN one was undocumented - so a Grep rooted at something realpath could
        # not resolve skipped the ancestor check entirely. The module docstring has always
        # said this guard "errs on the side of blocking on ambiguous input".
        return True


def _search_file_operands(command: str) -> list[str] | None:
    """For a search command, return its FILE operands (pattern excluded), else None.

    `grep -n "data/raw" .claude/settings.json` reads the deny-list config and merely mentions
    the marker in its pattern; the file operand is what decides. Returns None when the command
    is not a recognisable search invocation, in which case the caller applies the ordinary
    whole-string marker check.
    """
    try:
        tokens = shlex.split(command)
    except Exception:
        return None
    if not tokens:
        return None
    verb = os.path.basename(tokens[0])
    if verb not in _SEARCH_VERBS:
        return None

    operands: list[str] = []
    pattern_taken = False
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--":
            i += 1
            continue
        if tok.startswith("-") and len(tok) > 1:
            base = tok.split("=", 1)[0]
            # An explicit -e/-f/--regexp supplies the pattern, so the first bare token after
            # it is a FILE, not the pattern.
            if base in ("-e", "-f", "--regexp", "--file"):
                pattern_taken = True
            # 2026-09-12 audit (H-17): a flag whose VALUE names a path is a READ of that
            # path, and the old `i += 2` discarded flag and value together. `grep -f
            # data/raw/patterns.txt .` and `grep --file=data/raw/p.txt .` both passed,
            # because grep opens that file to read the patterns out of it. Same for the
            # include/exclude/glob filters, which can name a raw path just as directly.
            # Only -e/--regexp genuinely carry a pattern rather than a path.
            if base in _FLAGS_WITH_PATH_VALUE:
                if "=" in tok:
                    value, step = tok.split("=", 1)[1], 1
                else:
                    value, step = (tokens[i + 1] if i + 1 < len(tokens) else ""), 2
                if value and not value.startswith("!"):  # `!` = an rg exclusion, not a read
                    operands.append(value)
                i += step
                continue
            if base in _FLAGS_WITH_VALUE and "=" not in tok:
                i += 2
                continue
            i += 1
            continue
        if not pattern_taken:
            pattern_taken = True  # this bare token is the search pattern - not a path
            i += 1
            continue
        operands.append(tok)
        i += 1
    return operands


_HEREDOC_START_RE = re.compile(r"<<-?\s*([\"']?)([A-Za-z_][A-Za-z0-9_]*)\1")


def _strip_heredoc_bodies(command: str) -> str:
    """Drop heredoc BODIES, keeping the opener and terminator lines (2026-09-12, H-21).

    A heredoc body is content being WRITTEN somewhere, not a path being read, and where it
    goes is decided on the opener line - which is kept, redirect and all. Without this, any
    documentation or commit-message body that merely names the raw directory blocked the
    command that carried it, which is the prose/argument false-positive class ADR-002 has
    already fixed three times elsewhere in this guard.
    """
    lines = command.split("\n")
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


def _find_exclusion_residual(segment: str) -> str | None:
    """A `find` segment with its NEGATED path/name filters removed, or None.

    `find . -not -path './data/raw/*'` is a command that deliberately stays OUT of the raw
    directory, and it was blocked as if it were reading it (2026-09-12, H-21 - the case named
    in the audit brief). The excluded pattern is dropped; every other token, including real
    file operands and any `-exec`, is kept and still judged.
    """
    try:
        tokens = shlex.split(segment)
    except Exception:  # noqa: BLE001 - unparseable: judge the whole segment as before
        return None
    if not tokens or os.path.basename(tokens[0]) != "find":
        return None
    kept: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("-not", "!") and i + 2 < len(tokens) and tokens[i + 1] in _FIND_FILTERS:
            i += 3  # the negation, the filter and the pattern it excludes
            continue
        kept.append(tok)
        i += 1
    return " ".join(kept)


_FIND_FILTERS = ("-path", "-ipath", "-name", "-iname", "-wholename", "-regex")


def _advance_cwd(cwd: str, moved: str) -> str:
    """Fold one tracked `cd` into the running relative prefix."""
    if moved.startswith("/") or moved.startswith("~"):
        return moved
    return f"{cwd.rstrip('/')}/{moved}" if cwd else moved


def _cd_target(segment: str) -> str | None:
    """The directory a literal `cd`/`pushd` segment moves to, or None."""
    match = re.match(r"^(?:cd|pushd)\s+(?:-\S+\s+)*([^\s;&|]+)\s*$", segment.strip())
    if not match:
        return None
    return match.group(1).strip("\"'") or None


def _requalify(text: str, cwd: str) -> str:
    """Re-attach *cwd* to the relative operands of *text* (2026-09-12, H-9).

    `cd data && head raw/customers.csv` reads raw records without either segment containing
    the string this guard matches on. Best-effort and lexical: a cd through a variable, a
    subshell or `cd -` is still invisible, and that residual is stated rather than hidden.
    The verb is never requalified, so the search-verb and git-message exemptions above keep
    reading the real command.
    """
    tokens = text.split()
    if not tokens:
        return text
    base = cwd.rstrip("/")
    out = [tokens[0]]
    for tok in tokens[1:]:
        bare = tok.strip("\"'")
        if not bare or tok.startswith("-") or bare[:1] in ("/", "~", ">", "<", "|", "&", "$"):
            out.append(tok)
            continue
        out.append(f"{base}/{bare}")
    return " ".join(out)


def _segments(command: str) -> list[str]:
    """Split a compound Bash command into independently-judged statements (mirrors
    guard-code-execution.py's _segments()). Without this, `grep ...; echo "..."` was judged
    as ONE search invocation, so words from the SECOND statement became "file operands" of
    the FIRST'S search verb.

    Quote-aware (2026-08-03, second fix): a purely lexical split chopped INSIDE a quoted
    argument too - a log-note/commit message using ';' or '&&' as ordinary punctuation
    ("...close as-is; no real source data exists...") became its own bogus mid-sentence
    segment, live in an eval run. Delimiters are only boundaries OUTSIDE '...' / "..." -
    still lexical, not a full shell parser (ADR-002's irreducible residual): an unclosed
    quote just folds the remainder into one segment, the safe direction.

    2026-08-07 fix: that "boundaries only outside quotes" rule is TRUE for `;`/`&&`/`||`/
    `|`/newline but FALSE for command substitution - `echo "$(cat data/raw/x.csv)"` really
    executes the inner `cat` in bash even though it's inside double quotes; only single
    quotes suppress it. The 2026-08-03 rewrite gated backtick/`$(` on the same quote check
    as the other four, so a substitution wrapped in double quotes never became its own
    segment - mirrors the identical fix in guard-code-execution.py's _segments(), found by
    the same framework-wide audit and applied to both guards together so the fix doesn't
    live in only one of them."""
    segments: list[str] = []
    current: list[str] = []
    in_single = in_double = False
    i, n = 0, len(command)
    while i < n:
        ch = command[i]
        if ch == "\\" and not in_single and i + 1 < n:
            if command[i + 1] == "\n":
                # Line continuation: real bash ERASES both chars (one continued logical
                # line), never keeps them as literal text - unlike every other escape.
                i += 2
                continue
            current.append(command[i : i + 2])
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
            if command.startswith("`", i):
                segments.append("".join(current))
                current = []
                i += 1
                continue
            if command.startswith("$(", i):
                segments.append("".join(current))
                current = []
                i += 2
                continue
            if not in_double:
                hit = next((d for d in _ORDINARY_DELIMS if command.startswith(d, i)), None)
                if hit is not None:
                    segments.append("".join(current))
                    current = []
                    i += len(hit)
                    continue
        current.append(ch)
        i += 1
    segments.append("".join(current))
    return [s.strip() for s in segments if s.strip()]


def _git_message_operands(segment: str) -> list[str] | None:
    """For a `git commit`/`git tag` segment, return every token EXCEPT the -m/--message
    VALUE (prose, not a file read) - the flag itself and every other token (including a
    `-F <file>` message-file argument, which IS a real read) are kept and still checked.
    Returns None when the segment is not recognisably a git commit/tag invocation, in which
    case the caller applies the ordinary whole-segment marker check."""
    try:
        tokens = shlex.split(segment)
    except Exception:
        return None
    if (
        len(tokens) < 2
        or os.path.basename(tokens[0]) != "git"
        or tokens[1] not in _GIT_MESSAGE_VERBS
    ):
        return None
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        base = tok.split("=", 1)[0]
        if base in ("-m", "--message"):
            if "=" not in tok and i + 1 < len(tokens):
                i += 2  # drop the flag AND its value
                continue
            i += 1  # inline --message=... form: drop just this one token
            continue
        out.append(tok)
        i += 1
    return out


def _extract_path_candidates(tool: str, tool_input: dict) -> list[str]:
    """
    Return the list of string path tokens to check for a given tool.

    Read        -> file_path
    Grep        -> path, glob/include (directory/glob the search is rooted in)
    Glob        -> pattern (the glob itself), path (directory root)
    NotebookRead-> notebook_path
    WebFetch    -> url (a file:// URL addresses the LOCAL filesystem)
    Bash        -> command (full shell string - advisory only, see module docstring)
    <unknown>   -> every string value in tool_input (defence in depth, ADR-002 rec 22)
    """
    if tool == "Read":
        return [tool_input.get("file_path") or ""]

    if tool == "Grep":
        # Grep exposes 'path' (directory to search) and a glob filter. The current tool names the
        # glob 'glob'; older configs used 'include' - check both so neither is a dead check. Any
        # resolving under raw/ is enough to block. Ancestor-rooted and path-less forms are handled
        # separately in main() (they do not resolve UNDER raw, they CONTAIN it).
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

    if tool == "NotebookRead":
        return [tool_input.get("notebook_path") or ""]

    if tool == "WebFetch":
        # `file:///abs/path` addresses the local filesystem, so WebFetch is a read tool for
        # local data whatever its name suggests. Strip the scheme so the ordinary path checks
        # apply to the real path.
        url = tool_input.get("url") or ""
        candidates = [url]
        if url.lower().startswith("file://"):
            local = url[7:]
            # file://localhost/path and file:///path both leave a leading slash on the path.
            if local.lower().startswith("localhost/"):
                local = local[len("localhost") :]
            candidates.append(local)
        return candidates

    if tool == "Bash":
        # Belt-and-braces substring scan of the raw command string.
        # This is ADVISORY - see module-level docstring for the residual risk note.
        return [tool_input.get("command") or ""]

    if tool in ("Write", "Edit", "MultiEdit"):
        # 2026-09-12 (H-23). Writes ARE judged now - see _OUT_OF_SCOPE_TOOLS for why the
        # "covered separately by settings.json" justification did not survive checking.
        return [tool_input.get("file_path") or ""]

    if tool in _OUT_OF_SCOPE_TOOLS:
        # Deliberately unjudged - see _OUT_OF_SCOPE_TOOLS (currently empty).
        return []

    # Unknown tool (a future local-filesystem MCP reader, NotebookRead variants, ...). Rather
    # than the previous free pass, scan every string input for the marker. Advisory, but a
    # coverage gap that returns [] is how a read tool reaches raw data with nothing checking it.
    return [v for v in tool_input.values() if isinstance(v, str)]


def _block(reason: str) -> None:
    sys.stderr.write(
        f"Blocked ({reason}): this targets raw, un-masked data (data/raw/). "
        "Agents must not read raw records into context (CLAUDE.md §5) - they "
        "would be sent to the model provider. "
        "Run `python -m scripts.ingest` to produce masked data under data/masked/, "
        "then use that (or synthetic data from scripts/gen_synthetic.py) instead.\n"
    )
    sys.exit(2)


def _block_ancestor(root: str) -> None:
    sys.stderr.write(
        f"Blocked (search rooted at '{root}' would descend into data/raw/): this project "
        "currently holds raw, un-masked records, and a search from here would read them into "
        "context (CLAUDE.md §5). Scope the search below the raw directory (for example "
        "data/masked/), or pass an explicit path that excludes data/raw/.\n"
    )
    sys.exit(2)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        # Malformed hook payload - fail open so we never brick a session. In repo-as-project
        # mode the settings.json deny list still backs Read/Grep/Glob; a plugin install ships no
        # deny list, so recreate it in the host project (docs/house-rules.md, ADR-002 rec 10).
        sys.exit(0)

    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    # --- Bash: judge each statement of a compound command independently (segment fix),
    # then apply the search-verb pattern exemption (fix 3) or the git-message exemption
    # per segment - never the whole compound command as if it were one invocation.
    if tool == "Bash":
        cwd = ""
        for segment in _segments(_strip_heredoc_bodies(tool_input.get("command") or "")):
            moved = _cd_target(segment)
            operands = _search_file_operands(segment)
            if operands is not None:
                for operand in operands:
                    for probe in (operand, f"{cwd.rstrip('/')}/{operand}" if cwd else operand):
                        if _is_under_raw(probe) or _RAW_MARKER_RE.search(probe):
                            _block(f"raw-data path in search operand - tool={tool}")
                if moved:
                    cwd = _advance_cwd(cwd, moved)
                continue
            msg_operands = _git_message_operands(segment)
            if msg_operands is not None:
                residual = " ".join(msg_operands)
                if any(marker in residual for marker in RAW_MARKERS) or _RAW_MARKER_RE.search(
                    residual
                ):
                    _block(f"raw-data path in git commit/tag argument - tool={tool}")
                if moved:
                    cwd = _advance_cwd(cwd, moved)
                continue
            # A `find` that EXCLUDES the raw directory is the opposite of a read of it, so
            # its negated filters are dropped before matching (H-21).
            scan = _find_exclusion_residual(segment)
            if scan is None:
                scan = segment
            probes = [scan]
            if cwd:
                probes.append(_requalify(scan, cwd))
            for probe in probes:
                if any(marker in probe for marker in RAW_MARKERS) or _RAW_MARKER_RE.search(probe):
                    _block(f"raw-data marker in input - tool={tool}")
            if moved:
                cwd = _advance_cwd(cwd, moved)
        sys.exit(0)

    # --- Ancestor-rooted / path-less search (fix 2): only when raw data actually exists.
    if tool in ("Grep", "Glob"):
        root = tool_input.get("path") or ""
        if not root:
            # A path-less search is rooted at the working directory.
            root = _project_root
        if _is_ancestor_of_raw(root) and _raw_data_present():
            _block_ancestor(tool_input.get("path") or "(no path: working directory)")

    candidates = _extract_path_candidates(tool, tool_input)
    if not candidates:
        # Tool exposed no string inputs - allow.
        sys.exit(0)

    for candidate in candidates:
        if not candidate:
            continue
        # 1. Normalised path check (primary for Read / Grep / Glob).
        if _is_under_raw(candidate):
            _block(f"resolved path under data/raw/ - tool={tool}")
        # 2. Substring fallback (catches relative refs and Bash commands).
        if any(marker in candidate for marker in RAW_MARKERS) or _RAW_MARKER_RE.search(candidate):
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
