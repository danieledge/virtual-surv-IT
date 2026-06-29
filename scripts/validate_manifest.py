"""
scripts/validate_manifest.py - validate the Claude Code plugin manifest against the repo.

A typo'd or deleted agent path (or a skill directory missing its SKILL.md) passes the
test suite today and only fails when a user installs the plugin. This check closes that
gap: it parses .claude-plugin/plugin.json and asserts that every declared component
actually exists on disk. Run locally or in CI; exits non-zero on any problem.

Usage:
  python -m scripts.validate_manifest
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PLUGIN_JSON = _ROOT / ".claude-plugin" / "plugin.json"
_MARKETPLACE_JSON = _ROOT / ".claude-plugin" / "marketplace.json"


def _check() -> list[str]:
    """Return a list of problems; empty list means the manifest is valid."""
    problems: list[str] = []

    if not _PLUGIN_JSON.is_file():
        return [f"missing manifest: {_PLUGIN_JSON.relative_to(_ROOT)}"]

    try:
        manifest = json.loads(_PLUGIN_JSON.read_text())
    except json.JSONDecodeError as exc:
        return [f"plugin.json is not valid JSON: {exc}"]

    # Required top-level fields.
    for field in ("name", "version", "description"):
        if not manifest.get(field):
            problems.append(f"plugin.json missing required field: {field!r}")

    # Every declared agent path must exist.
    agents = manifest.get("agents", [])
    if not isinstance(agents, list):
        problems.append("plugin.json 'agents' must be a list")
        agents = []
    for rel in agents:
        if not isinstance(rel, str):
            problems.append(f"plugin.json 'agents' entry is not a string: {rel!r}")
            continue
        if not (_ROOT / rel).is_file():
            problems.append(f"declared agent does not exist: {rel}")

    # Declared agents should match the files actually present in the agents dir.
    agents_dir = _ROOT / ".claude" / "agents"
    if agents_dir.is_dir():
        on_disk = {p.name for p in agents_dir.glob("*.md")}
        declared = {Path(rel).name for rel in agents}
        for missing in sorted(on_disk - declared):
            problems.append(f"agent file present but NOT declared in plugin.json: {missing}")
        for extra in sorted(declared - on_disk):
            problems.append(f"agent declared in plugin.json but file missing: {extra}")

    # Skills: each declared skills root must contain skill dirs, each with a SKILL.md.
    skills = manifest.get("skills", [])
    if not isinstance(skills, list):
        problems.append("plugin.json 'skills' must be a list")
        skills = []
    for rel in skills:
        skills_root = _ROOT / rel
        if not skills_root.is_dir():
            problems.append(f"declared skills directory does not exist: {rel}")
            continue
        # Skip helper dirs: __pycache__ etc. and hidden/dot dirs (e.g. .ipynb_checkpoints).
        skill_dirs = [
            d for d in skills_root.iterdir() if d.is_dir() and not d.name.startswith(("__", "."))
        ]
        if not skill_dirs:
            problems.append(f"skills directory has no skills: {rel}")
        for d in skill_dirs:
            if not (d / "SKILL.md").is_file():
                problems.append(f"skill missing SKILL.md: {d.relative_to(_ROOT)}")

    # Hooks: the standard hooks/hooks.json at the plugin root is AUTO-LOADED by Claude Code, so it
    # must NOT be declared in plugin.json - doing so double-loads it ("duplicate hook file"). The
    # `hooks` key should only reference ADDITIONAL hook files outside the standard location.
    hooks = manifest.get("hooks")
    hook_refs = [hooks] if isinstance(hooks, str) else (hooks if isinstance(hooks, list) else [])
    for ref in hook_refs:
        if str(ref).lstrip("./") == "hooks/hooks.json":
            problems.append(
                "plugin.json 'hooks' references the auto-loaded hooks/hooks.json - that "
                "double-loads it. Remove it (declare only ADDITIONAL hook files)."
            )
        elif not (_ROOT / ref).is_file():
            problems.append(f"declared hooks file does not exist: {ref}")

    # Marketplace cross-reference (best-effort): the plugin name should appear there.
    if _MARKETPLACE_JSON.is_file():
        try:
            market = json.loads(_MARKETPLACE_JSON.read_text())
            plugin_names = {p.get("name") for p in market.get("plugins", []) if isinstance(p, dict)}
            if manifest.get("name") and manifest["name"] not in plugin_names:
                problems.append(
                    f"plugin name {manifest['name']!r} not listed in marketplace.json plugins[]"
                )
        except json.JSONDecodeError as exc:
            problems.append(f"marketplace.json is not valid JSON: {exc}")

    return problems


def main() -> int:
    problems = _check()
    if problems:
        print("Plugin manifest validation FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("Plugin manifest OK: all declared agents and skills resolve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
