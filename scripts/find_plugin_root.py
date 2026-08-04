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
import re
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


def _from_registry(home: Path) -> str:
    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(registry.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    for install_path in _walk_install_paths(data):
        candidate = Path(install_path)
        manifest = candidate / ".claude-plugin" / "plugin.json"
        try:
            text = manifest.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        # Substring match, not a parsed "name" field - matches the old grep -q's own
        # crude-but-proven behaviour exactly, deliberately not tightened here.
        if _TEAM_NAME in text:
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


def _from_filesystem_search(home: Path) -> str:
    bases = (home / ".claude" / "plugins" / "cache", home / ".claude" / "plugins" / "marketplaces")
    candidates: list[Path] = []
    for base in bases:
        if not base.is_dir():
            continue
        for marker in base.rglob("docs/team-operating-guide.md"):
            if _TEAM_NAME in marker.parts:
                candidates.append(marker)
    if not candidates:
        return ""
    newest = max(candidates, key=_sort_key)
    return str(newest.parent.parent)


def find_plugin_root(home: Path, cwd: Path) -> str:
    """Empty string means repo-as-project (the cwd IS the team repo)."""
    if (cwd / "docs" / "team-operating-guide.md").is_file():
        return ""
    return _from_registry(home) or _from_filesystem_search(home)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--home", default="")
    ap.add_argument("--cwd", default=".")
    args = ap.parse_args()

    home = Path(args.home) if args.home else Path.home()
    cwd = Path(args.cwd).resolve()
    print(f"PLUGIN_ROOT={find_plugin_root(home, cwd)}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
