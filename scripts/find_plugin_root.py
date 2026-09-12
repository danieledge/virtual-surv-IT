#!/usr/bin/env python3
"""Locate the compliance-surveillance-team plugin root, for the /engage step-0 bootstrap.

2026-08-04: replaces a hand-typed bash preamble in `.claude/skills/.shared/engage-open.md`
that mixed single- and double-quoted fragments (`grep -o '"installPath": *"[^"]*"' "$HOME/..."
| cut -d'"' -f4`) to hand-parse JSON - a live corp Windows report hit "unexpected EOF while
looking for matching '\"'" reproducing it, self-corrected, but the underlying design (the
model hand-types this from prose, with zero test coverage, every single /engage open) was
the actual risk, the same class of problem the rest of the step-0 probe was collapsed into
`engage_probe.py` to eliminate. This closes the gap for the one piece that couldn't simply
call that script, because locating IT is exactly the problem being solved here.

Two resolution methods, same priority order as the bash they replace:
  1. the install registry (~/.claude/plugins/installed_plugins.json): authoritative for every
     install source (GitHub marketplace, git URL, or a locally cloned directory added as a
     marketplace - install_helper.py's own default, `~/virtual-surv-IT`, has no
     "compliance-surveillance-team" path segment, so method 2 alone cannot find it).
     Schema-agnostic by design (a real registry nests installPath under
     plugins.<key>[].installPath, but the exact nesting isn't a stable contract) - recursively
     scans the parsed JSON for any "installPath" key at any depth, matching the old grep's own
     schema-agnostic behaviour rather than assuming today's shape is permanent.
  2. a filesystem search under ~/.claude/plugins/{cache,marketplaces} for this plugin's own
     marker file, for registries predating the current schema. Requires a literal
     "compliance-surveillance-team" path segment, so it is a fallback, never the primary.

Usage (invoked inline, not by path - see engage-open.md for why):
  python -c "<this file's source>" [--home PATH] [--cwd PATH]
Prints PLUGIN_ROOT= (empty string for repo-as-project) and nothing else on success.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_TEAM_NAME = "compliance-surveillance-team"


def _walk_install_paths(obj) -> list[str]:
    """Every string value found under any "installPath" key, at any nesting depth -
    schema-agnostic on purpose, see module docstring."""
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "installPath" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_walk_install_paths(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_walk_install_paths(item))
    return found


# The registry filename has drifted across Claude Code versions (2026-08-17 corp live
# report: a local-path install on v2.1.233 resolved to nothing, so the probe block died
# with no root while a direct --plugin-root call worked) - try every known name; the
# installPath walk below is schema-agnostic on purpose so a parse of ANY of them works.
_REGISTRY_NAMES = ("installed_plugins.json", "config.json", "plugins.json")


def _root_is_team_plugin(candidate: Path) -> bool:
    manifest = candidate / ".claude-plugin" / "plugin.json"
    try:
        text = manifest.read_text(encoding="utf-8-sig")
    except OSError:
        return False
    # Substring match, not a parsed "name" field - matches the old grep -q's own
    # crude-but-proven behaviour exactly, deliberately not tightened here.
    return _TEAM_NAME in text


def _root_is_usable(candidate: Path) -> bool:
    """Manifest names this plugin AND the probe script actually exists there. Corp debug
    session finding (2026-08-17): a registry entry can point at a partial or stale
    install - manifest present, scripts/ missing after a working-copy move or a broken
    update - and committing to it made the bootstrap exit with NO fallback while a
    healthy install sat unfound one resolver further down. Usability is checked before
    any resolver's answer is committed, so a broken candidate falls through to the next
    resolver instead of ending the search."""
    return _root_is_team_plugin(candidate) and (candidate / "scripts" / "engage_probe.py").is_file()


def _from_registry(home: Path) -> str:
    for name in _REGISTRY_NAMES:
        registry = home / ".claude" / "plugins" / name
        try:
            data = json.loads(registry.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        for install_path in _walk_install_paths(data):
            candidate = Path(install_path)
            if _root_is_usable(candidate):
                return str(candidate)
    return ""


_VERSION_KEY_RE = re.compile(r"(\d+)|(\D+)")


def _sort_key(path: Path) -> list:
    """Approximates `sort -V`: split into digit/non-digit runs, compare digit runs
    numerically. Not byte-identical to GNU sort -V for every edge case, but this is
    the fallback path (legacy registries only) - good enough to pick "the newest
    looking" candidate, same spirit as the bash it replaces."""
    parts = _VERSION_KEY_RE.findall(str(path))
    return [(int(d), "") if d else (-1, s) for d, s in parts]


# The install layouts put the marker at a FIXED shallow depth under each base -
# cache/<marketplace>/<plugin>/<version>/docs/... or marketplaces/<name>[/...]/docs/... -
# so glob exactly those depths and nothing deeper. The old unbounded rglob walked every
# unrelated plugin's full tree (this plugin alone vendors 306 files) on every cold open,
# a measured cost on AV-scanned corporate boxes and a README known-issue candidate
# (turn-0 trim, applied 2026-08-17).
_MARKER_DEPTH_PATTERNS = (
    "*/docs/team-operating-guide.md",
    "*/*/docs/team-operating-guide.md",
    "*/*/*/docs/team-operating-guide.md",
    "*/*/*/*/docs/team-operating-guide.md",
)


def _from_filesystem_search(home: Path) -> str:
    bases = (home / ".claude" / "plugins" / "cache", home / ".claude" / "plugins" / "marketplaces")
    candidates: list[Path] = []
    for base in bases:
        if not base.is_dir():
            continue
        for pattern in _MARKER_DEPTH_PATTERNS:
            for marker in base.glob(pattern):
                if _TEAM_NAME in marker.parts:
                    candidates.append(marker)
    usable = [m for m in candidates if _root_is_usable(m.parent.parent)]
    if not usable:
        return ""
    newest = max(usable, key=_sort_key)
    return str(newest.parent.parent)


def _from_installer_config(home: Path) -> str:
    """Last-resort resolver (2026-08-17 corp bug report): the Claude CLI's own update
    flow can leave the registry pointing at cache version dirs that were never
    populated, while the only healthy install is the source clone. install_helper.py
    records that clone's location in installer.json (repo_path) on every run - so when
    every registry and cache candidate has fallen through, the recorded clone is the
    one place left to look. Same usability validation as every other resolver."""
    base = os.environ.get("XDG_CONFIG_HOME")
    config = (Path(base) if base else home / ".config") / "virt-surv-it" / "installer.json"
    try:
        repo_path = json.loads(config.read_text(encoding="utf-8-sig")).get("repo_path") or ""
    except (OSError, ValueError):
        return ""
    if repo_path and _root_is_usable(Path(repo_path)):
        return str(repo_path)
    return ""


# Where this project's recorded identity lives: beside the go-written probe cache, in the
# project's own .claude/. Same directory, same lifetime, same thing to delete if it goes
# wrong.
_IDENTITY_FILE = "project-identity.json"
# How long a machine-level breadcrumb is worth warning about. Switching projects the next
# morning is ordinary; switching mid-session is the incident. Four hours is long enough to
# cover a working session and short enough that yesterday's project says nothing.
_FLIP_WINDOW_SECONDS = 4 * 60 * 60


def _git_fact(cwd: Path, args: list) -> str:
    """One short git answer about `cwd`, or "". Never raises and never blocks: this runs on
    the /engage step-0 path, where a slow answer costs the open."""
    import subprocess  # local: this module is also exec'd as a source string by the skill

    try:
        done = subprocess.run(  # fixed argv, shell=False  # nosec B603
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            # encoding+errors, never bare text=True: cp1252 consoles have undefined bytes
            # and git output carrying one raises inside subprocess's reader thread.
            encoding="utf-8",
            errors="replace",
            timeout=5,
            stdin=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001 - an identity fact is never worth a failure
        return ""
    return (done.stdout or "").strip() if done.returncode == 0 else ""


def project_identity(cwd: Path, mode: str = "") -> dict:
    """What this working directory IS: its path, its git remote, its git top-level.

    Path alone is not an identity - a checkout gets moved and renamed - and a remote alone
    is not either, since two clones of one repo are two projects. Recording all three lets
    a later run say which of them changed."""
    resolved = str(Path(cwd).resolve())
    return {
        "path": resolved,
        "remote": _git_fact(cwd, ["config", "--get", "remote.origin.url"]),
        "toplevel": _git_fact(cwd, ["rev-parse", "--show-toplevel"]),
        "mode": mode,
        "recorded_at": _now(),
    }


def _now() -> str:
    import datetime

    return datetime.datetime.now().isoformat(timespec="seconds")


def _identity_path(cwd: Path) -> Path:
    return Path(cwd) / ".claude" / _IDENTITY_FILE


def _atomic_json(path: Path, data: dict) -> None:
    """Write `data` to `path` so a reader sees the old file or the new one, never a mix.

    Prefers scripts/fsutil, which is the repo's one atomic writer. It falls back to an
    inline temp-and-replace for the reason stated at the top of this file and nowhere else
    in the repo: this module is invoked INLINE, as a source string handed to `python -c`,
    so there is no __file__ to hang a sibling import off and no scripts/ on sys.path. A
    breadcrumb that cannot be written in the one mode it exists to protect would be no
    breadcrumb at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fsutil

        fsutil.atomic_write_json(path, data)
        return
    except Exception:  # noqa: BLE001 - inline invocation has no sibling imports  # nosec B110 - a breadcrumb write is never worth failing the caller over; the atomic-write fallback below still runs
        pass
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _same_place(recorded: str, current: str) -> bool:
    """Path comparison that survives Windows. normcase folds case and separators, which is
    the difference between C:/Proj and c:\\proj being the same directory and looking like
    two."""
    return os.path.normcase(str(recorded)) == os.path.normcase(str(current))


def identity_warning(cwd: Path, mode: str) -> str:
    """Why the recorded identity for this directory no longer matches it, or "".

    WHY ANY OF THIS (2026-09-12 audit, W-21). Repo-vs-plugin mode was decided from a single
    `is_file()` test against Path.cwd() at invocation time, with the documented mitigation
    being a prose instruction - "never prepend cd" - and a named live incident (#19,
    2026-08-17) proving the instruction is not enough. A `cd` mid-session silently flips a
    plugin-mode session into repo-as-project, and every later answer is quietly about a
    different project.

    This does not override the detection - the cwd is still the truth, and a resolver that
    argued with reality would be worse than one that is occasionally surprised. It records
    what was resolved the first time and SAYS SO when the answer changes."""
    recorded = _read_identity(_identity_path(cwd))
    if not recorded:
        return ""
    current = project_identity(cwd, mode)
    if not _same_place(recorded.get("path", ""), current["path"]):
        return (
            f"this project was first resolved at {recorded.get('path')} and is now at "
            f"{current['path']} - if that was a move, delete .claude/{_IDENTITY_FILE}"
        )
    for key, label in (("remote", "git remote"), ("toplevel", "git top-level")):
        was, now = recorded.get(key) or "", current[key] or ""
        if was and now and was != now:
            return f"this project's {label} changed from {was} to {now}"
    if recorded.get("mode") and mode and recorded["mode"] != mode:
        return (
            f"this project resolved as {recorded['mode']} before and as {mode} now - "
            "a cd away from the project root does exactly this"
        )
    return ""


def _read_identity(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def remember_identity(cwd: Path, mode: str) -> None:
    """Record this project's identity at its FIRST resolution, and never again.

    First resolution only, because the point is to compare against what was true when the
    session started - a record rewritten on every call can never disagree with anything.
    Best-effort: a project whose .claude/ is not writable simply gets no check."""
    path = _identity_path(cwd)
    if path.is_file():
        return
    try:
        _atomic_json(path, project_identity(cwd, mode))
    except Exception:  # noqa: BLE001 - a breadcrumb is never worth a failure  # nosec B110 - a breadcrumb is never worth a failure
        pass


def _machine_config_path(home: Path) -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else home / ".config") / "virt-surv-it" / "installer.json"


def mode_flip_warning(home: Path, cwd: Path, mode: str) -> str:
    """Why the LAST resolution on this machine disagrees with this one, or "".

    The project-level record above cannot see incident #19 at all: a `cd` lands in a
    different directory, which has its own (or no) record. This breadcrumb is machine-level
    and short-lived on purpose - it fires when the previous resolution, within the last few
    hours, was a different directory in a different mode, which is what "a prior cd flipped
    the session" looks like from here and is not what switching projects tomorrow looks
    like."""
    config = _machine_config_path(home)
    previous = _read_identity(config).get("last_resolution")
    _remember_resolution(config, cwd, mode)
    if not isinstance(previous, dict):
        return ""
    if _same_place(previous.get("path", ""), str(Path(cwd).resolve())):
        return ""
    if not previous.get("mode") or previous["mode"] == mode:
        return ""
    try:
        import datetime

        age = datetime.datetime.now() - datetime.datetime.fromisoformat(
            str(previous.get("recorded_at"))
        )
    except (TypeError, ValueError):
        return ""
    if age.total_seconds() > _FLIP_WINDOW_SECONDS:
        return ""
    return (
        f"the previous resolution on this machine was {previous['mode']} in "
        f"{previous.get('path')} - if you changed directory mid-session, this answer is "
        "about a different project"
    )


def _remember_resolution(config: Path, cwd: Path, mode: str) -> None:
    """Overwrite the machine-level breadcrumb. Unlike the project record this IS rewritten
    every time: it answers "what did the last call resolve", which only the last call
    knows."""
    try:
        data = _read_identity(config)
        data["last_resolution"] = {
            "path": str(Path(cwd).resolve()),
            "mode": mode,
            "recorded_at": _now(),
        }
        _atomic_json(config, data)
    except Exception:  # noqa: BLE001 - a breadcrumb is never worth a failure  # nosec B110 - a breadcrumb is never worth a failure
        pass


def find_plugin_root(home: Path, cwd: Path) -> str:
    """Empty string means repo-as-project (the cwd IS the team repo).

    Resolution order (2026-08-17): repo-as-project first (unchanged), then the
    CLAUDE_PLUGIN_ROOT env var - plugin-mode hooks receive it directly from Claude Code,
    and it is the ONLY signal that covers every install shape including a local-path
    clone, which sits under neither the plugin cache nor the marketplaces dir (the corp
    live report's exact case) - validated against the manifest, never trusted bare; then
    the registry; then the bounded cache/marketplaces glob."""
    if (cwd / "docs" / "team-operating-guide.md").is_file():
        return ""
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or ""
    if env_root and _root_is_usable(Path(env_root)):
        return env_root
    return _from_registry(home) or _from_filesystem_search(home) or _from_installer_config(home)


def resolve(home: Path, cwd: Path) -> tuple:
    """(plugin_root, warnings) - the resolution plus anything worth saying about it.

    The entry point `main` uses. find_plugin_root stays exactly what it was, a pure
    function of home and cwd, because every existing caller and test depends on that;
    the identity bookkeeping lives here, on top of it, where it can be skipped."""
    root = find_plugin_root(home, cwd)
    mode = "plugin" if root else "repo-as-project"
    warnings = [w for w in (identity_warning(cwd, mode), mode_flip_warning(home, cwd, mode)) if w]
    remember_identity(cwd, mode)
    return root, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--home", default="")
    ap.add_argument("--cwd", default=".")
    args = ap.parse_args()

    home = Path(args.home) if args.home else Path.home()
    cwd = Path(args.cwd).resolve()
    root, warnings = resolve(home, cwd)
    # STDOUT CARRIES THE ANSWER AND NOTHING ELSE - the skill reads this line with a shell
    # capture, so a warning on stdout would be consumed as part of the path. Warnings go to
    # stderr, where the human can see them and the capture cannot.
    for warning in warnings:
        print(f"virt-surv: {warning}", file=sys.stderr)
    print(f"PLUGIN_ROOT={root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
