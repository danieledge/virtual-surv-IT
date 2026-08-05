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


def resolve_root(plugin_root: str, project_dir: Path) -> tuple[Path, str]:
    """(root_for_reading_plugin_files, PLUGIN_ROOT display string). Repo-as-project when
    plugin_root is empty AND the project itself looks like the team repo."""
    if plugin_root:
        return Path(plugin_root), plugin_root
    return project_dir, "repo-as-project"


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
    per the skill's own rule, never silently treated as "no change"."""
    if not prev_team_version:
        return "yes"
    return (
        "yes"
        if plugin_version and _bare_version(plugin_version) != _bare_version(prev_team_version)
        else "no"
    )


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
            text=True,
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
        data = json.loads((root / "virt-surv-it" / "installer.json").read_text(encoding="utf-8-sig"))
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


def run_tool_probe(root: Path, project_dir: Path) -> str:
    cached = _read_cached_tool_probe(project_dir)
    if cached is not None:
        return cached
    for candidate in (
        project_dir / "scripts" / "check-review-tools.sh",
        root / "scripts" / "check-review-tools.sh",
    ):
        if candidate.is_file():
            try:
                proc = subprocess.run(  # fixed argv, shell=False  # nosec B603
                    [_find_bash(), str(candidate)],
                    cwd=project_dir,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return proc.stdout
            except (OSError, subprocess.SubprocessError):
                return ""
    return ""


def run_extensions_show(root: Path, project_dir: Path) -> str:
    if not (project_dir / "docs" / "team-extensions.md").is_file():
        return ""
    ext = root / "scripts" / "extensions.py"
    if not ext.is_file():
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
            text=True,
            timeout=30,
        )
        return proc.stdout[:2000]  # same cap as the no-script fallback above
    except (OSError, subprocess.SubprocessError):
        return ""


def build_report(plugin_root_arg: str, project_dir: Path) -> str:
    root, pr_display = resolve_root(plugin_root_arg, project_dir)
    plugin_version = read_plugin_version(root)
    branch = git_branch(root)
    map_header, map_section3 = read_map(project_dir)
    prev_ver = last_team_version(map_section3) if map_section3 else ""
    changed = version_changed(plugin_version, prev_ver)
    # The skill's own what's-new rule is "no -> show nothing" - so don't even print it: this
    # used to land in the transcript on every open regardless of VERSION_CHANGED.
    changelog_entry = first_changelog_entry(root) if changed == "yes" else ""
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
    # map_skeleton (ADR-007 Phase 1 Chunk D): unlike large_context_review_split, this one
    # DOES have a machine-default tier - same key-presence-wins precedence as docx/citations.
    if "map_skeleton" in prefs:
        map_skeleton_on = prefs["map_skeleton"]
    else:
        map_skeleton_on = machine_defaults.get("default_map_skeleton", False)
    tool_report = run_tool_probe(root, project_dir)
    extensions_block = run_extensions_show(root, project_dir)

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
        f"MAP_SKELETON={'on' if map_skeleton_on else 'off'}",
    ]
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
