"""
scripts/engage_probe.py - the engage skill's step-0 open-time probe, as code.

Audit finding #5/#6/#8 (2026-07-30): the step-0 probe used to be an 18-line hand-assembled
bash compound the MODEL had to reproduce verbatim, every single engage - the skill file
itself documented a prior recovery-turn failure from exactly this kind of prose-driven
reconstruction. Collapsing the logic into one tested script means:
  - the model generates ONE short invocation instead of ~18 lines of bash (#5, real token
    savings on every engage open - the biggest single item in the audit);
  - the version-changed decision is COMPUTED here (#8: emits VERSION_CHANGED=yes|no plus
    both version strings) instead of the model doing a string-compare wrapped in prose logic;
  - PLUGIN_ROOT is printed in a form set-runtime can persist verbatim, closing the gap where
    it previously lived only in conversational memory for the whole session until step 4 (#6).

PLUGIN_ROOT itself is still resolved by a short bash preamble in the skill file (unavoidable:
locating THIS script in plugin mode is the bootstrapping problem the probe exists to solve,
and $CLAUDE_PLUGIN_ROOT is documented elsewhere as unreliable in the Bash tool's own
subshell) - everything downstream of "where is the plugin" lives here instead.

Usage:
  python -m scripts.engage_probe [--plugin-root PATH] [--project-dir PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess  # fixed argv, shell=False, invoking our own sibling scripts  # nosec B404
import sys
import time
from pathlib import Path

_TEAM_VER_ROW_RE = re.compile(
    r"^\|\s*(\d{4}-\d{2}-\d{2}|<[^|]*>)\s*\|[^|]*\|\s*([^|]+?)\s*\|", re.MULTILINE
)

# Known repo glyphs get a readable ASCII substitute rather than falling through to the
# generic replace-with-'?' below.
_ASCII_GLYPH_MAP = {
    "🎩": "[Morgan]",
    "📊": "[observed]",
    "🧠": "[inferred]",
    "→": "->",
    "✓": "[x]",
    "✗": "[ ]",
    "…": "...",
    "–": "-",
    "—": "-",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
}


def _ascii_safe(text: str) -> str:
    """Guarantee pure-ASCII stdout for the probe's report.

    The report round-trips through a shell $(...) capture, then Claude Code's own
    Bash-tool output pipe, before the model ever sees it. PYTHONIOENCODING=utf-8 (set
    by the caller) only controls how THIS process encodes its own stdout - it says
    nothing about how that downstream pipe decodes the bytes back into text. On a
    Windows cp1252 console that decode step can raise UnicodeDecodeError outright for
    specific UTF-8 byte sequences (some emoji land on cp1252's undefined single-byte
    codepoints), even though this process wrote perfectly valid UTF-8 (live corp
    report, 2026-08-04). The report is built from user-editable project files
    (codebase-map.md, CHANGELOG.md, team-extensions.md) whose content isn't under this
    script's control, so known repo glyphs get a readable substitute and everything
    else falls back to a generic ascii-encode - the output is provably pure ASCII
    regardless of what a project's own docs contain.
    """
    for glyph, sub in _ASCII_GLYPH_MAP.items():
        text = text.replace(glyph, sub)
    return text.encode("ascii", errors="replace").decode("ascii")


_TEAM_NAME = "compliance-surveillance-team"


def _looks_like_team_repo(project_dir: Path) -> bool:
    """Same check scripts/find_plugin_root.py's own registry search already uses: a
    substring match for the team name in plugin.json - crude but proven, deliberately
    not tightened to a parsed field (matches that existing convention exactly)."""
    manifest = project_dir / ".claude-plugin" / "plugin.json"
    try:
        text = manifest.read_text(encoding="utf-8-sig")
    except OSError:
        return False
    return _TEAM_NAME in text


def resolve_root(plugin_root: str, project_dir: Path) -> tuple[Path, str, bool]:
    """(root_for_reading_plugin_files, PLUGIN_ROOT display string, root_is_trusted).

    2026-08-14 Fable-model audit finding (C1): this used to return project_dir as root
    whenever plugin_root arrived empty - UNCONDITIONALLY. The docstring claimed this
    only happened "when the project itself looks like the team repo", but the code
    never actually checked that. If the skill's own bash preamble ever failed to
    resolve --plugin-root (a documented, expected failure mode - the module docstring
    above notes $CLAUDE_PLUGIN_ROOT is unreliable) while running in genuine PLUGIN mode
    against a FOREIGN project, this silently treated that foreign, untrusted project as
    if it were the plugin's own trusted source - the same class of bug run_tool_probe's
    fix just above closes, reached via a different path (an empty --plugin-root rather
    than tool-probe's own candidate ordering).

    root_is_trusted is False exactly when plugin_root arrived empty AND project_dir does
    not genuinely look like the team repo - the true "we don't actually know where the
    plugin is" case. Callers that execute anything found under `root` (run_tool_probe,
    run_extensions_show) must refuse to trust root-derived paths when this is False,
    never silently execute a guess. root still gets set to project_dir even when
    untrusted (there is nothing better to fall back to for the REST of this report -
    version/branch/changelog reads are display-only, not execution), only the
    execution-sensitive callers need to gate on the trust bit specifically."""
    if plugin_root:
        return Path(plugin_root), plugin_root, True
    if _looks_like_team_repo(project_dir):
        return project_dir, "repo-as-project", True
    return project_dir, "repo-as-project", False


def read_plugin_version(root: Path) -> str:
    manifest = root / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        return str(data.get("version", "")).strip()
    except (OSError, ValueError):
        return ""


def last_team_version(map_text: str) -> str:
    """The Team ver column of the LAST row in '## 3. Engagement history'. Empty string
    when there is no map, no §3 table, or the table is still template placeholders."""
    m = re.search(r"(?ms)^## 3\..*?(?=^## 4\.|\Z)", map_text)
    if not m:
        return ""
    rows = _TEAM_VER_ROW_RE.findall(m.group(0))
    # Skip the header/separator and any placeholder row (date column still "<YYYY-MM-DD>").
    real = [ver for date, ver in rows if not date.startswith("<") and not ver.startswith("<")]
    return real[-1] if real else ""


def _bare_version(v: str) -> str:
    """Strip a leading v/V - `plugin.json`'s "version" field is always bare ('0.33.7'), but
    `docs/templates/codebase-map.md`'s own Team-ver placeholder is `<vX.Y.Z>`, WITH the
    prefix. Without normalising, a same-release row written per the template's own
    convention never string-equals plugin_version, so version_changed always says "yes" -
    the what's-new banner (and the changelog print gated on it) would fire on literally
    every single engagement, forever, never correctly detecting "no change" (found while
    testing the changelog-gating fix, 2026-08-03)."""
    return v[1:] if v[:1] in ("v", "V") else v


def version_changed(plugin_version: str, prev_team_version: str) -> str:
    """'yes' | 'no'. No prior record (empty prev) counts as changed - "first engagement"
    per the skill's own rule, never silently treated as "no change".

    M5 (2026-08 Fable audit): an EMPTY plugin_version is not "no change" either -
    read_plugin_version() returns "" on ANY read/parse failure of plugin.json
    (unreadable, missing, corrupt), and `plugin_version and ...` used to let that flow
    straight into "no", indistinguishable from a confirmed same-version read. A failure
    to determine the plugin's current version proves nothing about whether it changed -
    fail toward showing the what's-new banner (the same conservative default the
    no-prior-record branch above already uses), not toward silently suppressing it."""
    if not prev_team_version or not plugin_version:
        return "yes"
    return "yes" if _bare_version(plugin_version) != _bare_version(prev_team_version) else "no"


_SECTION3_MAX_ROWS = 5


def _cap_section3_rows(section3: str, max_rows: int = _SECTION3_MAX_ROWS) -> str:
    """Keep every non-table line plus the table's header/separator and only the LAST
    max_rows data rows - one engagement close appends one row, forever, and the probe used
    to print the whole thing every single open regardless of age. Only the last row ever
    feeds the version-changed computation, so capping here never changes that result."""
    lines = section3.splitlines()
    table_idx = [i for i, ln in enumerate(lines) if ln.lstrip().startswith("|")]
    if len(table_idx) <= 2 + max_rows:
        return section3  # header + separator + <=max_rows data rows already
    head = table_idx[:2]  # header row, separator row
    tail = table_idx[-max_rows:]
    omitted = len(table_idx) - len(head) - len(tail)
    out: list[str] = []
    kept = set(head) | set(tail)
    for i, ln in enumerate(lines):
        if i in kept or i not in table_idx:
            out.append(ln)
        elif i == min(t for t in table_idx if t not in kept):
            out.append(f"*(… {omitted} earlier row(s) omitted - full history in the map itself)*")
    return "\n".join(out)


def read_map(project_dir: Path) -> tuple[str, str]:
    """(header_and_section2_intro_text, section3_text) for the just-in-time print, plus
    used internally for the version-changed computation. Empty strings when no map."""
    for name in ("docs/codebase-map.md", "CODEBASE-MAP.md"):
        p = project_dir / name
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            header = "\n".join(text.splitlines()[:20])
            m = re.search(r"(?ms)^## 3\..*?(?=^## 4\.|\Z)", text)
            section3 = _cap_section3_rows(m.group(0).rstrip()) if m else ""
            return header, section3
    return "", ""


def _resolve_globs_probe(globs: list, repo_root: Path) -> list:
    """Duplicated from scripts/map_fingerprint.py::resolve_globs (kept byte-identical in
    behaviour - see _compute_fingerprint_probe for why this is duplicated rather than
    imported). A bare trailing `**` is treated as `**/*` too, same reasoning as the
    original: stdlib pathlib's `**` alone only matches directories, and silently returning
    zero files for the obviously-intended pattern would make an entry's drift check
    permanently blind."""
    matches = set()
    for pattern in globs:
        effective = [pattern]
        if pattern == "**" or pattern.endswith("/**"):
            effective.append(f"{pattern}/*")
        for variant in effective:
            for path in repo_root.glob(variant):
                if path.is_file():
                    matches.add(path.relative_to(repo_root).as_posix())
    return sorted(matches)


def _compute_fingerprint_probe(globs: list, repo_root: Path) -> str:
    """Duplicated from scripts/map_fingerprint.py::compute_fingerprint - MUST stay
    byte-identical to that function (same algorithm, same "sha256:" prefix) or every
    entry would show as spuriously drifted here even when check_artifacts.py's own
    check_map() (the authoritative, close-time check) says otherwise. Duplicated rather
    than imported because engage_probe.py must stay runnable standalone, before any
    plugin-mode import of a sibling scripts/ module is guaranteed reliable - same
    rationale as read_machine_defaults() re-deriving preference precedence instead of
    importing install_helper.py's."""
    files = _resolve_globs_probe(globs, repo_root)
    digest = hashlib.sha256()
    for rel_path in files:
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update((repo_root / rel_path).read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


_FP_PROBE_CACHE_FILENAME = ".map-fingerprint-probe-cache.json"


def _file_signature(files: list, repo_root: Path) -> list:
    """[[rel_path, mtime, size], ...] for every file in `files` (already sorted by
    _resolve_globs_probe) - cheap stat() calls only, never file content. A file whose
    stat() fails (permissions, a TOCTOU race) gets [rel_path, None, None] instead of
    being skipped, so a transition to/from unreadable is itself a detectable signature
    change rather than silently ignored."""
    sig = []
    for rel_path in files:
        try:
            st = (repo_root / rel_path).stat()
            sig.append([rel_path, st.st_mtime, st.st_size])
        except OSError:
            sig.append([rel_path, None, None])
    return sig


def _load_fp_probe_cache(project_dir: Path) -> dict:
    path = project_dir / ".claude" / _FP_PROBE_CACHE_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}  # missing/corrupt cache is never load-bearing - falls through to a real compute


def _save_fp_probe_cache(project_dir: Path, cache: dict) -> None:
    """Best-effort - a failed write just means the next call recomputes from scratch,
    never a reason to raise (this cache is a pure performance aid, never authoritative -
    codebase-map.fingerprints.json remains the one sidecar drift is actually judged
    against)."""
    path = project_dir / ".claude" / _FP_PROBE_CACHE_FILENAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass


def _fingerprint_with_mtime_shortcut(area: str, globs: list, repo_root: Path, cache: dict):
    """M5 (2026-08-14 perf audit): _compute_fingerprint_probe re-reads and re-hashes
    every mapped file's FULL BYTES on every call, even when nothing has changed since
    the last check - a real, repeated disk-I/O cost on every open/Stop cycle while
    map_skeleton is on. Cached here by a cheap (path, mtime, size) SIGNATURE, never by
    content: when every matched file's signature matches what is cached for this area
    (same file set too - an added/removed/renamed file changes `files` itself, which
    changes the signature), the previously computed fingerprint is reused verbatim with
    zero file reads or hashing this call. The moment ANY file's mtime OR size differs -
    both are checked, so a filesystem that doesn't move mtime on some writes, or a
    truncated file with an unchanged mtime, still invalidates via the size half - this
    falls straight through to an ordinary, UNMODIFIED _compute_fingerprint_probe call:
    same algorithm, same output, byte-identical to today on every path. This is a pure
    disk-I/O shortcut, never a change to the hashing algorithm itself, so it stays
    byte-identical to scripts/map_fingerprint.py::compute_fingerprint (the authoritative
    function check_artifacts.py's close-time check uses) exactly as
    _compute_fingerprint_probe's own docstring requires - a DIFFERENT algorithm here
    (e.g. caching per-file hashes and combining them, which cannot reproduce the same
    single cumulative digest) would risk exactly the "spuriously drifted... even when
    check_artifacts.py's own check_map() says otherwise" bug that docstring warns
    against, so this deliberately does not do that.

    Returns (fingerprint, cache_changed) - the caller only pays a sidecar write when
    something was actually recomputed."""
    files = _resolve_globs_probe(globs, repo_root)
    signature = _file_signature(files, repo_root)
    entry = cache.get(area)
    if isinstance(entry, dict) and entry.get("sig") == signature:
        return entry.get("fingerprint", ""), False
    fingerprint = _compute_fingerprint_probe(globs, repo_root)
    cache[area] = {"sig": signature, "fingerprint": fingerprint}
    return fingerprint, True


def map_drift_summary(project_dir: Path, map_skeleton_on: bool) -> str:
    """Minimal, standalone open-time drift check (2026-08-07 user request: surface drift at
    OPEN, not only at close, so Morgan can factor it into how she briefs agents - "otherwise
    it's not adding value", her words, echoed by the user). Deliberately duplicates a
    MINIMAL subset of check_artifacts.check_map()'s MAP-DRIFT logic (column-driven §2-table
    scan, sha256 fingerprint compare) instead of importing it - see
    _compute_fingerprint_probe's docstring for the standalone-runnability rationale.

    Root map only (docs/codebase-map.md / CODEBASE-MAP.md) - docs/codebase-map.d/ area
    files are not scanned here (scope kept minimal per explicit user instruction; the
    close-time check_map() sweep remains the authoritative, complete check across both).

    Returns "" when there is nothing to report - toggle off, no map, no Paths-glob entries,
    or nothing drifted - a silent no-op, matching the toggle's off-by-default contract."""
    if not map_skeleton_on:
        return ""
    map_path = None
    for name in ("docs/codebase-map.md", "CODEBASE-MAP.md"):
        candidate = project_dir / name
        if candidate.is_file():
            map_path = candidate
            break
    if map_path is None:
        return ""
    try:
        lines = map_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    rows = []  # (area, globs)
    columns = None
    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith("|"):
            columns = None
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells or set("".join(cells)) <= {"-", ":", " "}:
            continue  # |---| divider
        lowered = [c.lower() for c in cells]
        if any("basis" in c for c in lowered):
            columns = {name: i for i, name in enumerate(lowered)}
            continue  # the header row itself
        if columns is None:
            continue  # a table without a Basis column (history, deprecated, doc control)
        paths_idx = next((i for n, i in columns.items() if "paths" in n), None)
        if paths_idx is None or paths_idx >= len(cells) or not cells[paths_idx]:
            continue  # no Paths glob on this entry - nothing to fingerprint
        area_idx = next((i for n, i in columns.items() if "area" in n), None)
        if area_idx is None:
            area_idx = next((i for n, i in columns.items() if n == "id"), None)
        area = cells[area_idx] if area_idx is not None and area_idx < len(cells) else "?"
        globs = [g.strip() for g in cells[paths_idx].split(",") if g.strip()]
        if globs:
            rows.append((area, globs))
    if not rows:
        return ""
    sidecar_path = map_path.parent / "codebase-map.fingerprints.json"
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8")).get("entries") or {}
    except (OSError, ValueError):
        sidecar = {}
    fp_cache = _load_fp_probe_cache(project_dir)
    fp_cache_changed = False
    drifted = []
    for area, globs in rows:
        recorded = sidecar.get(area)
        current, changed = _fingerprint_with_mtime_shortcut(area, globs, project_dir, fp_cache)
        fp_cache_changed = fp_cache_changed or changed
        if recorded is None or current != recorded.get("fingerprint"):
            drifted.append(area)
    if fp_cache_changed:
        _save_fp_probe_cache(project_dir, fp_cache)
    if not drifted:
        return ""
    shown = ", ".join(drifted[:5]) + (", ..." if len(drifted) > 5 else "")
    return f"{len(drifted)} of {len(rows)} area(s): {shown}"


def first_changelog_entry(root: Path) -> str:
    path = root / "CHANGELOG.md"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = text.splitlines()
    out: list[str] = []
    seen = 0
    for ln in lines:
        if ln.startswith("## ["):
            seen += 1
            if seen > 1:
                break
        if seen:
            out.append(ln)
        if len(out) >= 30:
            break
    return "\n".join(out)


def git_branch(root: Path) -> str:
    """The checked-out branch, or "" when it can't be known - never a guess.

    Plugin installs are usually a plain file COPY into ~/.claude/plugins/cache (no .git
    at all - confirmed empirically 2026-07-30), so branch detection only works in
    repo-as-project mode or when installPath happens to point at a real clone. Detached
    HEAD (git prints the literal "HEAD") is also reported as unknown, not as a branch
    name that doesn't exist."""
    if not (root / ".git").exists():  # a file for worktrees, a dir for a normal clone
        return ""
    try:
        proc = subprocess.run(  # fixed argv, shell=False, literal "git" on PATH  # nosec B603 B607
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            encoding="utf-8",  # not text=True - see run_tool_probe's comment below
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    branch = proc.stdout.strip()
    return branch if proc.returncode == 0 and branch and branch != "HEAD" else ""


def read_team_preferences(project_dir: Path) -> dict:
    p = project_dir / ".claude" / "team-preferences.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def read_machine_defaults() -> dict:
    """~/.config/virt-surv-it/installer.json (honouring XDG_CONFIG_HOME) - THIS
    machine's defaults, written by install_helper.py's "Project preferences"/"Machine
    defaults" steps. Mirrors install_helper.py's config_path()/load_config(), deliberately
    re-derived here rather than imported (see _find_bash's comment) so this script stays
    runnable standalone. Consulted by the docx/citations fallback below - 2026-08-05 user
    request: "project should default to machine default but can be overridden at project
    level" - previously this machine's default was only ever a one-time SEED value copied
    into a project at configure-time, never a genuine runtime fallback for a project that
    was enabled without ever running Configure/Project preferences at all."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    try:
        data = json.loads(
            (root / "virt-surv-it" / "installer.json").read_text(encoding="utf-8-sig")
        )
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _find_bash() -> str:
    """bash for the tool probe, surviving Git for Windows' default PATH (installer adds
    Git\\cmd, not Git\\bin - `bash` misses even though Git is fully installed; see
    install_helper.py's find_bash, same root cause, deliberately re-derived here so this
    script stays runnable standalone without importing the installer)."""
    hit = shutil.which("bash")
    if hit:
        return hit
    if sys.platform != "win32":
        return "bash"  # let the subprocess call fail with a clear error on POSIX
    candidates = []
    git = shutil.which("git")
    if git:
        root = Path(git).resolve().parent.parent
        candidates += [root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"]
    for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "Git" / "bin" / "bash.exe")
    for c in candidates:
        try:
            if c.is_file():
                return str(c)
        except OSError:
            continue
    return "bash"


def _allowlist_line(project_dir: Path) -> str:
    """Mirrors check-review-tools.sh's allowlist_line() exactly - computed fresh every
    call (never cached: the user may add the entry minutes after being tipped)."""
    settings = project_dir / ".claude" / "settings.json"
    present = False
    if settings.is_file():
        try:
            text = settings.read_text(encoding="utf-8", errors="replace")
            present = bool(re.search(r"python3? -m scripts\.\*", text))
        except OSError:
            present = False
    if present:
        return "ALLOWLIST: present"
    return (
        "ALLOWLIST: missing - fewer permission prompts if added; the user runs:\n"
        "  python <clone>/install_helper.py --permissions ."
    )


def _read_cached_tool_probe(project_dir: Path) -> str | None:
    """check-review-tools.sh's own cache-hit branch, read directly instead of shelling
    out to it - on Windows, spawning Git Bash just to `cat` a file and check its mtime
    cost ~2.2s on every single warm /engage (P3, live corp report 2026-07-31), even
    though the cache-hit path inside the script does no real work. None means "no fresh
    cache" - the caller falls through to the real script (first run, stale, or missing)."""
    cache_env = os.environ.get("CST_TOOLCHECK_CACHE") or ".claude/.tool-availability"
    cache = Path(cache_env)
    if not cache.is_absolute():
        cache = project_dir / cache
    try:
        ttl_days = int(os.environ.get("CST_TOOLCHECK_TTL_DAYS") or 7)
    except ValueError:
        ttl_days = 7
    try:
        mtime = cache.stat().st_mtime
    except OSError:
        return None
    if time.time() - mtime >= ttl_days * 86400:
        return None  # stale - let the real script re-probe and re-cache
    try:
        report = cache.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return (
        report.rstrip("\n")
        + "\n\n"
        + f"(cached - from a probe within the last {ttl_days} day(s); re-run with --refresh after\n"
        + " installing or removing analysers.)\n"
        + _allowlist_line(project_dir)
        + "\n"
    )


def run_tool_probe(root: Path, project_dir: Path, root_is_trusted: bool = True) -> str:
    """2026-08-14 Fable-model audit finding, BLOCKER: this used to check project_dir's
    own check-review-tools.sh BEFORE root's - harmless in project/dogfood mode (root ==
    project_dir, same file either way), but a genuine consent-gate bypass in plugin
    mode: engage_probe.py is on guard-code-execution.py's own _TEAM_ALLOW list (trusted
    team tooling, no consent prompt), and that guard has no visibility into what an
    ALLOWED script subsequently executes internally via subprocess.run() - so a project
    brought in for review that plants its own scripts/check-review-tools.sh gets it
    executed the moment /engage runs, no consent marker, no prompt, directly
    contradicting CLAUDE.md §7's non-negotiable ("never execute the code under review
    without authorisation") and ADR-002's "never untrusted provenance". Every existing
    test for this function passed root == project_dir, so the divergent (actually
    security-relevant) case had zero coverage.

    Fix: when root and project_dir genuinely differ (plugin mode against a foreign
    project - the only case this distinction can matter), ONLY the plugin's own
    trusted copy is ever considered; the project's copy is not even looked at, let
    alone executed. When they're the same directory (project/dogfood mode), behaviour
    is unchanged - there is no trust boundary to cross when reviewing this repo
    against itself. root_is_trusted (from resolve_root's own trust bit, see its
    docstring) must ALSO hold before the project's own copy is ever considered - a
    root that only equals project_dir because resolution genuinely failed (not because
    this really is dogfood mode) must not be treated as safe either; defaults True for
    any caller that hasn't been updated to pass it (this function's own project-mode
    tests, which never exercise the divergent case at all)."""
    cached = _read_cached_tool_probe(project_dir)
    if cached is not None:
        return cached
    if not root_is_trusted:
        # root came from a FAILED resolution (resolve_root's fallback), which means it
        # equals project_dir despite not being genuinely verified - "only check root's
        # copy" would silently check the untrusted project's copy anyway under a
        # different variable name. Nothing under either root is safe to execute here;
        # refuse the probe entirely rather than guess.
        return ""
    try:
        same_root = project_dir.resolve() == root.resolve()
    except OSError:
        same_root = project_dir == root
    candidates = (
        (
            project_dir / "scripts" / "check-review-tools.sh",
            root / "scripts" / "check-review-tools.sh",
        )
        if same_root
        else (root / "scripts" / "check-review-tools.sh",)
    )
    for candidate in candidates:
        if candidate.is_file():
            try:
                proc = subprocess.run(  # fixed argv, shell=False  # nosec B603
                    [_find_bash(), str(candidate)],
                    cwd=project_dir,
                    capture_output=True,
                    # Not text=True: on Windows that decodes with cp1252, whose
                    # undefined bytes (0x81/0x8d/...) raise UnicodeDecodeError inside
                    # subprocess's own reader thread ("Exception in Thread-N ...") -
                    # live corp report, 2026-08-12, check-review-tools.sh's own ✓/✗
                    # marks or an analyser's output tripping it. install_helper.py's
                    # run_cmd hit and fixed the identical failure mode on 2026-07-30;
                    # this call is independent of run_cmd (this script runs standalone,
                    # without importing install_helper - see _find_bash's docstring) so
                    # it needed the same fix applied separately here.
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                return proc.stdout
            except (OSError, subprocess.SubprocessError):
                return ""
    return ""


def run_extensions_show(root: Path, project_dir: Path, root_is_trusted: bool = True) -> str:
    """2026-08-14 Fable-model audit finding (C1), same class as run_tool_probe just
    above: this always executes `root / "scripts" / "extensions.py"` - fine when root
    is genuinely the plugin's own directory, but if resolve_root's own resolution
    failed (see its docstring), root silently became project_dir, and this would
    execute the FOREIGN, untrusted project's own extensions.py, triggered by nothing
    more than the project containing docs/team-extensions.md. root_is_trusted (from
    resolve_root's own trust bit) gates the execution branch - untrusted root falls
    back to the safe, non-executing "just read the markdown" path instead, same as
    the script-genuinely-absent case already does."""
    if not (project_dir / "docs" / "team-extensions.md").is_file():
        return ""
    ext = root / "scripts" / "extensions.py" if root_is_trusted else None
    if not ext or not ext.is_file():
        try:
            return (project_dir / "docs" / "team-extensions.md").read_text(
                encoding="utf-8", errors="replace"
            )[:2000]
        except OSError:
            return ""
    try:
        proc = subprocess.run(  # fixed argv, shell=False  # nosec B603
            [sys.executable, str(ext), "show"],
            cwd=project_dir,
            capture_output=True,
            encoding="utf-8",  # not text=True - see run_tool_probe's comment above
            errors="replace",
            timeout=30,
        )
        return proc.stdout[:2000]  # same cap as the no-script fallback above
    except (OSError, subprocess.SubprocessError):
        return ""


def resolve_preferences(project_dir: Path) -> dict:
    """Resolve the 5 team-preferences flags through the project -> machine-default ->
    built-in precedence chain. Pulled out of build_report() (2026-08-08) so a point-in-time
    snapshot of "what was enabled" can be taken independently of the open-time probe banner
    (engagement_state._cmd_init stores the result as state["settings_snapshot"]).

    Returns {"extra_formats": list[str], "regulatory_citations": bool,
    "large_context_review_split": bool, "parallel_dispatch_via_workflow": bool,
    "standards_critique": bool, "map_skeleton": bool}."""
    prefs = read_team_preferences(project_dir)
    # Project setting wins if this project has ever explicitly set it (even to "off" -
    # write_team_preferences always records extra_formats/regulatory_citations once a
    # human has been through Configure/Project preferences once, so key-PRESENCE, not
    # truthiness, is the right test for "has this project made its own choice"). A
    # project that was enabled without ever running either falls back to this machine's
    # default, then finally the built-in default (docx off, citations on).
    machine_defaults = read_machine_defaults()
    if "extra_formats" in prefs:
        extra_formats = prefs.get("extra_formats") or []
    else:
        extra_formats = ["docx"] if machine_defaults.get("default_docx") else []
    if "regulatory_citations" in prefs:
        citations_on = prefs["regulatory_citations"]
    else:
        citations_on = machine_defaults.get("default_regulatory_citations", True)
    review_split_on = prefs.get("large_context_review_split", False)
    # parallel_dispatch_via_workflow: on by default when absent (unlike review_split) -
    # only an explicit false in team-preferences.json turns it off. No machine-wide tier.
    workflow_dispatch_on = prefs.get("parallel_dispatch_via_workflow", True)
    # standards_critique: off by default when absent - same no-machine-wide-tier precedent
    # as large_context_review_split/parallel_dispatch_via_workflow. It gates the DoD
    # "Critiqued against the named standard" pass (a second, independent review of a
    # finished review), not a universal expectation.
    standards_critique_on = prefs.get("standards_critique", False)
    # map_skeleton (ADR-007 Phase 1 Chunk D): unlike large_context_review_split, this one
    # DOES have a machine-default tier - same key-presence-wins precedence as docx/citations.
    if "map_skeleton" in prefs:
        map_skeleton_on = prefs["map_skeleton"]
    else:
        map_skeleton_on = machine_defaults.get("default_map_skeleton", False)
    return {
        "extra_formats": extra_formats,
        "regulatory_citations": citations_on,
        "large_context_review_split": review_split_on,
        "parallel_dispatch_via_workflow": workflow_dispatch_on,
        "standards_critique": standards_critique_on,
        "map_skeleton": map_skeleton_on,
    }


def build_report(plugin_root_arg: str, project_dir: Path) -> str:
    root, pr_display, root_is_trusted = resolve_root(plugin_root_arg, project_dir)
    plugin_version = read_plugin_version(root)
    branch = git_branch(root)
    map_header, map_section3 = read_map(project_dir)
    prev_ver = last_team_version(map_section3) if map_section3 else ""
    changed = version_changed(plugin_version, prev_ver)
    # The skill's own what's-new rule is "no -> show nothing" - so don't even print it: this
    # used to land in the transcript on every open regardless of VERSION_CHANGED.
    changelog_entry = first_changelog_entry(root) if changed == "yes" else ""
    resolved = resolve_preferences(project_dir)
    extra_formats = resolved["extra_formats"]
    citations_on = resolved["regulatory_citations"]
    review_split_on = resolved["large_context_review_split"]
    workflow_dispatch_on = resolved["parallel_dispatch_via_workflow"]
    standards_critique_on = resolved["standards_critique"]
    map_skeleton_on = resolved["map_skeleton"]
    tool_report = run_tool_probe(root, project_dir, root_is_trusted)
    extensions_block = run_extensions_show(root, project_dir, root_is_trusted)
    drift = map_drift_summary(project_dir, map_skeleton_on)

    lines = [
        f"PLUGIN_ROOT={pr_display}",
        f"OS={'Windows' if sys.platform == 'win32' else 'POSIX'}",
        f"PYTHON_VERSION={sys.version.split()[0]}",
        f"PLUGIN_VERSION={plugin_version}",
        f"BRANCH={branch}",
        f"PREV_TEAM_VERSION={prev_ver}",
        f"VERSION_CHANGED={changed}",
        f"EXTRA_FORMATS={','.join(extra_formats)}",
        f"REGULATORY_CITATIONS={'on' if citations_on else 'off'}",
        f"LARGE_CONTEXT_REVIEW_SPLIT={'on' if review_split_on else 'off'}",
        f"PARALLEL_DISPATCH_VIA_WORKFLOW={'on' if workflow_dispatch_on else 'off'}",
        f"STANDARDS_CRITIQUE={'on' if standards_critique_on else 'off'}",
        f"MAP_SKELETON={'on' if map_skeleton_on else 'off'}",
    ]
    if drift:
        # Only appended when there's something to say - map_skeleton off, no map, no
        # Paths-glob entries, or nothing drifted all mean this line doesn't exist at all,
        # matching the toggle's "off means zero added output" contract everywhere else.
        lines.append(f"MAP_DRIFT={drift}")
    if tool_report:
        lines += ["", tool_report.rstrip()]
    if map_header:
        lines += [
            "",
            map_header,
            "...(map section 2 body read just-in-time on demand; "
            "section 3 history below for the version compare:)",
            map_section3,
        ]
    if changelog_entry:
        lines += ["", changelog_entry]
    if extensions_block:
        lines += ["", extensions_block.rstrip()]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plugin-root", default="")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument(
        "--interpreter-name",
        default="",
        help="the literal command word (python3/python/py) the caller invoked THIS "
        "script with - echoed back as INTERPRETER= so later commands use the same "
        "one, since sys.executable's own path is not always what should be typed",
    )
    args = ap.parse_args()
    report = build_report(args.plugin_root, Path(args.project_dir).resolve())
    if args.interpreter_name:
        report = f"INTERPRETER={args.interpreter_name}\n" + report
    print(_ascii_safe(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
