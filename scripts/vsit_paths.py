#!/usr/bin/env python3
"""Where the team's files live in a project - the single source of truth.

WHY THIS EXISTS (plan-project-footprint-2026-08-27). The team writes into a host project in
several places, and every one of them was constructed inline at the point of use: 39 sites
building `<project>/artifacts`, 31 building the preferences path, more for the map, the
extensions contract and four caches. Moving any of them meant editing all of them, which is
why the layout had never been fixed despite `artifacts/` at a client's repository root being
a name collision waiting to happen.

With one resolver per location, the layout becomes a property of THIS file. Everything else
asks where something lives instead of deciding.

THE LAYOUT

    <project>/
      VSIT/
        shared/       what every engagement needs: the map, the derived tree
        engagements/  one folder per piece of work
        reports/      deliverables belonging to the project, not one engagement
        config/       this project's contract and preferences
        local/        machine-only caches, gitignored
      .claude/        the harness's own directory - NOT ours

LEGACY FALLBACK, AND WHY IT IS NOT OPTIONAL

Projects already carry the old layout: `artifacts/<slug>/`, `docs/codebase-map.md`,
`.claude/team-preferences.json`. Every resolver here therefore answers "where IS it", not
"where SHOULD it be": if the new location exists it wins; otherwise, if the legacy location
exists, that is the honest answer. Only when neither exists does the new layout win by
default, so a fresh project starts clean and an existing one keeps working untouched.

That ordering matters more than it looks. A resolver that returned the new path
unconditionally would silently orphan every existing engagement pack on upgrade - the files
would still be on disk, and nothing would be able to find them.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT_NAME = "VSIT"

# THE FLIP (plan-project-footprint-2026-08-27, stage 2).
#
# While False, a project with NEITHER layout present resolves to the legacy locations - so
# routing 70+ call sites through this module (stage 1) changes no behaviour anywhere, and a
# green suite across that refactor actually means something. Flipping it to True is stage 2:
# one line, one reviewable change, and the tests that encode the layout get updated
# deliberately rather than as collateral of a large refactor.
#
# Projects that ALREADY have VSIT/ are unaffected either way - an existing new-layout
# directory always wins, at both settings.
PREFER_NEW_LAYOUT = False

# New layout, relative to the project root.
_SHARED = (ROOT_NAME, "shared")
_ENGAGEMENTS = (ROOT_NAME, "engagements")
_REPORTS = (ROOT_NAME, "reports")
_CONFIG = (ROOT_NAME, "config")
_LOCAL = (ROOT_NAME, "local")

# Where each thing lived before. Kept explicit rather than derived: these are historical
# facts, and a reader should be able to see exactly what is being migrated from.
_LEGACY_ENGAGEMENTS = ("artifacts",)
_LEGACY_SHARED = ("docs",)
_LEGACY_CONFIG = (".claude",)
_LEGACY_LOCAL = (".claude",)


def project_root(explicit: Path | str | None = None) -> Path:
    """The project directory: an explicit argument, else CLAUDE_PROJECT_DIR, else cwd.

    Deliberately does NOT walk ancestors looking for a marker. CLAUDE_PROJECT_DIR is Claude
    Code's own notion of "the project" and is authoritative when set; walking above it can
    only escape the intended project, never refine it (the 2026-08-14 audit found exactly
    that: a project at /home/user/artifacts/myproject resolved its pack root to
    /home/user/artifacts, outside the project entirely)."""
    if explicit is not None:
        return Path(explicit).expanduser()
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env).expanduser() if env else Path.cwd()


def _resolve(root: Path, new: tuple, legacy: tuple, legacy_leaf: str = "") -> Path:
    """New location if it exists, else legacy if THAT exists, else new.

    "Else new" is the important half: a project with neither gets the new layout, so nothing
    has to be migrated before it can be used."""
    candidate = root.joinpath(*new)
    if candidate.exists():
        return candidate
    old = root.joinpath(*legacy)
    if legacy_leaf:
        old = old / legacy_leaf
    if old.exists():
        return old
    return candidate if PREFER_NEW_LAYOUT else old


def engagements_dir(project: Path | str | None = None) -> Path:
    """Where engagement workspaces live. Legacy: `artifacts/`."""
    root = project_root(project)
    return _resolve(root, _ENGAGEMENTS, _LEGACY_ENGAGEMENTS)


def shared_dir(project: Path | str | None = None) -> Path:
    """Where knowledge shared across engagements lives - the map and the derived tree.

    Legacy is `docs/`, which is the HOST PROJECT's directory, so the fallback is deliberately
    narrow: it points at docs/ only when a map is actually there, never merely because a
    docs/ folder exists. Almost every project has a docs/; very few have our map in it."""
    root = project_root(project)
    candidate = root.joinpath(*_SHARED)
    if candidate.exists():
        return candidate
    for legacy_map in ("codebase-map.md", "CODEBASE-MAP.md"):
        if (root / "docs" / legacy_map).is_file():
            return root / "docs"
    return candidate if PREFER_NEW_LAYOUT else root / "docs"


def reports_dir(project: Path | str | None = None) -> Path:
    """Project-level deliverables that belong to no single engagement.

    No legacy location: these previously landed loose at the root of `artifacts/`, which is
    how they became indistinguishable from engagement packs in the first place."""
    return project_root(project).joinpath(*_REPORTS)


def config_dir(project: Path | str | None = None) -> Path:
    """This project's team settings and extensions contract. Legacy: `.claude/`."""
    root = project_root(project)
    candidate = root.joinpath(*_CONFIG)
    if candidate.exists():
        return candidate
    if (root / ".claude" / "team-preferences.json").is_file():
        return root / ".claude"
    return candidate if PREFER_NEW_LAYOUT else root / ".claude"


def local_dir(project: Path | str | None = None) -> Path:
    """Machine-only caches. Legacy: `.claude/`.

    Never committed: these are derived from THIS checkout - file timestamps, resolved
    interpreter paths, which tools are on this machine's PATH - and are wrong everywhere
    else. Git does not preserve mtimes, so a shared copy would miss on every lookup."""
    root = project_root(project)
    candidate = root.joinpath(*_LOCAL)
    if candidate.exists():
        return candidate
    if (root / ".claude" / ".tool-availability").exists():
        return root / ".claude"
    return candidate if PREFER_NEW_LAYOUT else root / ".claude"


def preferences_file(project: Path | str | None = None) -> Path:
    """This project's team settings.

    `config/preferences.json` in the new layout, `.claude/team-preferences.json` in the old.
    The name loses its "team-" prefix on the way: inside VSIT/config/ the folder already
    says whose settings these are, and the prefix only existed to disambiguate them from
    Claude Code's own files when they shared a directory."""
    config = config_dir(project)
    if config.name == ".claude":
        return config / "team-preferences.json"
    return config / "preferences.json"


def extensions_file(project: Path | str | None = None) -> Path:
    """This project's extensions contract. Legacy: `docs/team-extensions.md`."""
    config = config_dir(project)
    if config.name == ".claude":
        # The legacy contract lived in the host project's docs/, not in .claude/.
        return project_root(project) / "docs" / "team-extensions.md"
    return config / "extensions.md"


def engagement_dir(slug: str, project: Path | str | None = None) -> Path:
    """One engagement's workspace."""
    return engagements_dir(project) / slug


def map_file(project: Path | str | None = None) -> Path:
    """The curated map. `map.md` in the new layout, `codebase-map.md` in the old one."""
    shared = shared_dir(project)
    if shared.name == "docs":
        for legacy in ("codebase-map.md", "CODEBASE-MAP.md"):
            if (shared / legacy).is_file():
                return shared / legacy
        return shared / "codebase-map.md"
    return shared / "map.md"


def is_legacy_layout(project: Path | str | None = None) -> bool:
    """True when this project still uses the pre-VSIT locations.

    Used by the migration offer, and by anything that wants to report the layout rather than
    silently pick one."""
    root = project_root(project)
    if root.joinpath(ROOT_NAME).exists():
        return False
    return (root / "artifacts").exists() or (root / "docs" / "codebase-map.md").is_file()
