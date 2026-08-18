"""Content fingerprinting for codebase-map drift detection (ADR-007 Phase 1).

Import-only - no CLI, no `__main__` - so it never needs its own guard-allowlist entry
(scripts/repo_skeleton.py's `--fingerprint` mode and scripts/check_artifacts.py's `check_map()`
both import `compute_fingerprint` directly, so writer and verifier can never disagree on
hashing semantics).

A codebase-map §2 entry (or docs/codebase-map.d/<area>.md file) can declare a `Paths:` glob -
the set of files it describes. This module resolves that glob to an actual, sorted file list
and hashes it deterministically, so a later check can tell "has anything this entry describes
changed since it was written" without re-reading or re-verifying the entry's prose itself.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def resolve_globs(globs: list[str], repo_root: Path) -> list[str]:
    """Every file matching any of `globs` (as `Path.glob()` patterns) under `repo_root`, as a
    sorted, deduplicated list of forward-slash root-relative paths. A glob matching nothing is
    not an error here - an empty result is a legitimate answer that `compute_fingerprint`'s
    caller (MAP-DRIFT) can act on.

    A bare trailing `**` (e.g. `src/**`, the natural way a PM hand-writing a `Paths:` glob
    would expect "everything under src") only matches DIRECTORIES in stdlib pathlib - `**/*` is
    needed to also match files. Since this glob syntax is human-authored, not
    machine-generated, silently returning zero files for the obviously-intended pattern would
    be a real footgun (an entry with a `Paths:` glob that never actually matches anything can
    never show drift, which is worse than no glob at all - looks configured, isn't). So a
    pattern ending in a bare `**` is treated as `**/*` too."""
    matches: set[str] = set()
    for pattern in globs:
        effective = [pattern]
        if pattern == "**" or pattern.endswith("/**"):
            effective.append(f"{pattern}/*")
        for variant in effective:
            for path in repo_root.glob(variant):
                if path.is_file():
                    matches.add(path.relative_to(repo_root).as_posix())
    return sorted(matches)


def compute_fingerprint(globs: list[str], repo_root: Path) -> str:
    """sha256 over every file matched by `globs`, in sorted-path order, each entry keyed by
    its own path (not just its bytes) so a rename or an added/removed file changes the
    fingerprint even when every individual file's content is unchanged. `"sha256:" + hexdigest`
    - the prefix makes a fingerprint self-describing in the sidecar JSON, in case a future
    version adds a second algorithm."""
    files = resolve_globs(globs, repo_root)
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
